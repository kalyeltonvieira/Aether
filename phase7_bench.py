"""Compatibility entry point for ``benchmarks.phase7.phase7_bench``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.phase7.phase7_bench", run_name="__main__")
else:
    from benchmarks.phase7.phase7_bench import *  # noqa: F401,F403
