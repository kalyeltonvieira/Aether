"""Compatibility entry point for ``benchmarks.phase2.phase2_bench``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.phase2.phase2_bench", run_name="__main__")
else:
    from benchmarks.phase2.phase2_bench import *  # noqa: F401,F403
