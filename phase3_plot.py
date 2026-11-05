"""Compatibility entry point for ``benchmarks.phase3.phase3_plot``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.phase3.phase3_plot", run_name="__main__")
else:
    from benchmarks.phase3.phase3_plot import *  # noqa: F401,F403
