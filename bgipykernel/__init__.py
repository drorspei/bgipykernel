import asyncio
from contextlib import nullcontext
import ctypes
from threading import Lock, Thread
import threading
from ipykernel.ipkernel import IPythonKernel
from IPython import get_ipython
from IPython.core.magic import register_line_magic
from IPython.core.magic_arguments import argument, magic_arguments, parse_argstring


def async_raise(thread_id, exception):
    """Raise an exception in a thread by its thread ID."""
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(thread_id), 
        ctypes.py_object(exception)
    )
    if res == 0:
        raise ValueError("Invalid thread ID")
    elif res > 1:
        # If it returns more than 1, you need to revert the action
        ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, None)
        raise SystemError("PyThreadState_SetAsyncExc failed")


def pretty(s: str) -> str:
    ss = s.strip().splitlines()
    if len(ss) > 1:
        return f"{ss[0][:50]}..."
    elif len(ss) == 1:
        if len(ss[0]) > 53:
            return f"{ss[0][:50]}..."
        return ss[0]
    return ""


class CorrectExecutionCountsIPythonKernel(IPythonKernel):
    async def do_execute(self, *args, **kwargs):
        shell = self.shell
        assert shell is not None
        execution_count = shell.execution_count
        reply_content = await super().do_execute(*args, **kwargs)
        reply_content['execution_count'] = execution_count
        return reply_content


class NoAsyncLockIPythonKernel(CorrectExecutionCountsIPythonKernel):
    def start(self):
        super().start()
        self.nolocks = False

    async def shell_main(self, *args, **kwargs):
        if not self.nolocks:
            self.nolocks = True
            from contextlib import nullcontext
            self.shell_channel_thread.asyncio_lock = nullcontext()
            self._main_asyncio_lock = nullcontext()
        return await super().shell_main(*args, **kwargs)


class Job:
    def __init__(self, job_id, thread, loop, lock, code=None, aborted=False):
        self.job_id = job_id
        self.thread = thread
        self.loop = loop
        self.code = code
        self.aborted = aborted
        self.lock = lock


class BgIPythonKernel(NoAsyncLockIPythonKernel):
    registered_magic = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.registered_handler = False
        
        self.done_object = object()

        self.jobs = {}
        self.lock = Lock()

        self.messages_queue = asyncio.Queue()
        self.messages_io = asyncio.new_event_loop()
        self.messages_thread = None
                
        if not BgIPythonKernel.registered_magic:
            BgIPythonKernel.registered_magic = True
            @register_line_magic
            def bg(_):
                if self.messages_thread is None:
                    async def messages_loop():
                        while True:
                            msg = await self.messages_queue.get()
                            if msg is self.done_object:
                                break
                            # actually print the message to frontend
                            print(msg)
                    self.messages_thread = Thread(target=self.messages_io.run_until_complete, args=(messages_loop(),))
                    self.messages_thread.start()

            @register_line_magic
            def jobs(_):
                with self.lock:
                    if len(self.jobs) > 1:
                        message = "\n".join(f"[{job.job_id}] `{pretty(job.code)}`" for job in list(self.jobs.values())[:-1])
                    else:
                        message = "bgipykernel: no jobs"
                asyncio.run_coroutine_threadsafe(self.messages_queue.put(message), self.messages_io)

            @register_line_magic
            @magic_arguments()
            @argument("job_id", type=int, help="Id of job to kill")
            def kill(arg):
                args = parse_argstring(kill, arg)
                with self.lock:
                    cur_id = max(self.jobs)
                    job = self.jobs.get(args.job_id, None)
                if job is None or cur_id == args.job_id:
                    asyncio.run_coroutine_threadsafe(self.messages_queue.put(f"kill: {args.job_id}: no such job"), self.messages_io)
                else:
                    async_raise(job.thread.ident, KeyboardInterrupt)

    def start(self):
        self.new_execution()
        super().start()
        loop = asyncio.get_event_loop()
        import signal
        def handler(*_):
            with self.lock:
                if self.count:
                    thread = self.jobs[max(self.jobs)].thread
                    async_raise(thread.ident, KeyboardInterrupt)
        loop.add_signal_handler(signal.SIGINT, handler)

    async def _execute_request(self, stream, ident, parent, job):
        async with job.lock:
            if job.aborted:
                self._send_abort_reply(stream, msg, ident)
            else:
                job.code = parent.get("content", {}).get("code", None)
                await super(BgIPythonKernel, self).execute_request(stream, ident, parent)
            with self.lock:
                if job.job_id == max(self.jobs):
                    self.count -= 1

    def new_execution_lock(self):
        return asyncio.Lock()

    def new_execution(self):
        loop = asyncio.new_event_loop()

        def run(self, job):
            try:
                job.loop.run_forever()
            finally:
                job.loop.run_until_complete(job.loop.shutdown_asyncgens())
                job.loop.close()
                with self.lock:
                    del self.jobs[job.job_id]
                asyncio.run_coroutine_threadsafe(self.messages_queue.put(f"[{job.job_id}] done `{pretty(job.code)}`"), self.messages_io)

        with self.lock:
            job_id = max(self.jobs, default=0) + 1
            self.jobs[job_id] = job = Job(job_id=job_id, thread=None, loop=loop, lock=self.new_execution_lock())
            thread = Thread(target=run, args=(self, job))
            job.thread = thread
            self.count = 0
            thread.start()
            self.execution_io, self.execution_thread = loop, thread

    async def interrupt_request(self, *args, **kwargs):
        with self.lock:
            if self.jobs:
                thread = self.jobs[max(self.jobs)].thread
            else:
                thread = None
        if thread is not None:
            async_raise(thread.ident, KeyboardInterrupt)
        await super().interrupt_request(*args, **kwargs)

    def _abort_queues(self, _):
        # find current thread in threads, mark it aborted, if its the front thread then call new_execution
        thread = threading.current_thread()
        do_new = False
        with self.lock:
            for job in self.jobs.values():
                if job.thread is thread:
                    job.aborted = True
                    if job.job_id == max(self.jobs):
                        do_new = True
                    break
        if do_new:
            self.new_execution()

    async def execute_request(self, stream, ident, parent):
        """handle an execute_request"""
        if not self.session:
            return

        if parent.get("content", {}).get("code") == "%bg":
            exec_io = self.execution_io
            if self.count:
                with self.lock:
                    job = self.jobs[max(self.jobs)]
                self.new_execution()
                asyncio.run_coroutine_threadsafe(self.messages_queue.put(f"[{job.job_id}] `{pretty(job.code)}`"), self.messages_io)
                async def stop():
                    exec_io.stop()
                asyncio.run_coroutine_threadsafe(stop(), exec_io)
            else:
                asyncio.run_coroutine_threadsafe(self.messages_queue.put("%bgipykernel: nothing is running"), self.messages_io)

        with self.lock:
            job = self.jobs[max(self.jobs)]
            self.count += 1
        asyncio.run_coroutine_threadsafe(self._execute_request(stream, ident, parent, job), job.loop)

    async def _at_shutdown(self):
        self.log.debug("%bgipykernel: Stopping job threads")
        with self.lock:
            for job in self.jobs.values():
                async def stop(loop=job.loop):
                    loop.stop()
                asyncio.run_coroutine_threadsafe(stop(), job.loop)
        asyncio.run_coroutine_threadsafe(self.messages_queue.put(self.done_object), self.messages_io)

        async def wait_for_thread(thread, name):
            for _ in range(100):
                if not thread.is_alive():
                    break
                await asyncio.sleep(0.01)
            else:
                self.log.debug(f"%bgipykernel: Failed to stop thread `{name}`")

        with self.lock:
            cos = [wait_for_thread(job.thread, f"job-{k}") for k, job in self.jobs.items()]
        if self.messages_thread is not None:
            cos.append(wait_for_thread(self.messages_thread, "messages"))

        await asyncio.gather(super()._at_shutdown(), *cos)


class NoAsyncLockBgIPythonKernel(BgIPythonKernel):
    def new_execution_lock(self):
        return nullcontext()
