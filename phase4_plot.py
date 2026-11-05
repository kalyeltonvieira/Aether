"""Compatibility entry point for ``benchmarks.phase4.phase4_plot``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.phase4.phase4_plot", run_name="__main__")
else:
    from benchmarks.phase4.phase4_plot import *  # noqa: F401,F403
