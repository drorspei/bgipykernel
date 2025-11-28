# bgipykernel - %bg in jupyter

Install using `pip install bgipykernel`

Add the following line to your `ipython_kernel_config.py` file:

```
c.IPKernelApp.kernel_class = 'bgipykernel.NoAsyncLockBgIPythonKernel'
```

if you can't find your config file, run `ipython profile locate`.

## features

Move running cells to the background by running `%bg`

-

Kill background cells using `%kill`

-

See what cells are running in the background using `%jobs`

-

Run multiple cells with `await` concurrently

-

## available configurations

* If you just want to use `await` in multiple cells concurrently, use `bgipykernel.NoAsyncLockIPythonKernel`
* If you just want `%bg, use `bgipykernel.BgIPythonKernel`
* If oyu want both, use `bgipykernel.NoAsyncLockBgIPythonKernel`

## trouble

When using a `%bg` variant (i.e. `BgIPythonKernel` or `NoAsyncLockBgIPythonKernel`), interrupting the kernel can only happen at the byte code level, meaning functions like `time.sleep` don't get interrupted. 
