"""Setuptools hook that packages the optional Rust source beside its wrapper."""
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
    def run(self) -> None:
        super().run()
        source = Path(__file__).resolve().parent / "aether_native.rs"
        destination = Path(self.build_lib) / "aether_native.rs"
        self.copy_file(str(source), str(destination))


setup(cmdclass={"build_py": build_py})
