"""Compatibility entry point for ``benchmarks.phase5.phase5_plot``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.phase5.phase5_plot", run_name="__main__")
else:
    from benchmarks.phase5.phase5_plot import *  # noqa: F401,F403
