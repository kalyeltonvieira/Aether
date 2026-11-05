"""Compatibility entry point for ``benchmarks.phase8.phase8_bench``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.phase8.phase8_bench", run_name="__main__")
else:
    from benchmarks.phase8.phase8_bench import *  # noqa: F401,F403
