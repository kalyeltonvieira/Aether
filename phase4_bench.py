"""Compatibility entry point for ``benchmarks.phase4.phase4_bench``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.phase4.phase4_bench", run_name="__main__")
else:
    from benchmarks.phase4.phase4_bench import *  # noqa: F401,F403
