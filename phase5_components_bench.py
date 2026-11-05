"""Compatibility entry point for ``benchmarks.phase5.phase5_components_bench``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.phase5.phase5_components_bench", run_name="__main__")
else:
    from benchmarks.phase5.phase5_components_bench import *  # noqa: F401,F403
