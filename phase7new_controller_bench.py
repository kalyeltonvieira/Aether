"""Compatibility entry point for ``benchmarks.phase7new.phase7new_controller_bench``."""
import runpy

if __name__ == "__main__":
    runpy.run_module("benchmarks.phase7new.phase7new_controller_bench", run_name="__main__")
else:
    from benchmarks.phase7new.phase7new_controller_bench import *  # noqa: F401,F403
