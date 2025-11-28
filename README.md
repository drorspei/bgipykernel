# bgipykernel - %bg in jupyter

Install using `pip install bgipykernel`

Add the following line to your `ipython_kernel_config.py` file:

```
c.IPKernelApp.kernel_class = 'bgipykernel.NoAsyncLockBgIPythonKernel'
```

if you can't find your config file, run `ipython profile locate`.

## features

- Move running cells to the background by running `%bg`
- List background cells using `%jobs`
- Kill them using `%kill`

https://github.com/user-attachments/assets/3d46fe32-dc1b-4876-8317-1721b5d683cb

- Run multiple cells with `await` concurrently

https://github.com/user-attachments/assets/b6ebdabd-9e84-45d4-8f0e-8b56e49eee41

## available configurations

* If you just want to use `await` in multiple cells concurrently, use `bgipykernel.NoAsyncLockIPythonKernel`
* If you just want `%bg`, use `bgipykernel.BgIPythonKernel`
* If you want both, use `bgipykernel.NoAsyncLockBgIPythonKernel`

## trouble

When using a `%bg` variant (i.e. `BgIPythonKernel` or `NoAsyncLockBgIPythonKernel`), interrupting the kernel can only happen at the byte code level, meaning functions like `time.sleep` don't get interrupted. 
