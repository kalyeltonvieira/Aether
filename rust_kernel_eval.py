"""Compatibility entry point for ``benchmarks.phase3.rust_kernel_eval``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.phase3.rust_kernel_eval", run_name="__main__")
else:
    from benchmarks.phase3.rust_kernel_eval import *  # noqa: F401,F403
