"""Compatibility entry point for ``benchmarks.baseline.aether_bench``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.baseline.aether_bench", run_name="__main__")
else:
    from benchmarks.baseline.aether_bench import *  # noqa: F401,F403
