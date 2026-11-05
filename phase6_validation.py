"""Compatibility entry point for ``benchmarks.phase6.phase6_validation``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.phase6.phase6_validation", run_name="__main__")
else:
    from benchmarks.phase6.phase6_validation import *  # noqa: F401,F403
