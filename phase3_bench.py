"""Compatibility entry point for ``benchmarks.phase3.phase3_bench``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.phase3.phase3_bench", run_name="__main__")
else:
    from benchmarks.phase3.phase3_bench import *  # noqa: F401,F403
