"""Path helpers shared by historical benchmark modules."""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def repository_root() -> Path:
    """Locate a source checkout, or use the caller's working directory after install."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "aether").is_dir():
            return candidate
    return Path.cwd().resolve()


def phase5_manifest_path() -> Path:
    """Return the sole packaged SNAP manifest, not a cwd-relative guess."""
    checkout = repository_root() / "datasets" / "manifests" / "phase5_datasets.json"
    if checkout.is_file():
        return checkout
    resource = files("aether.resources.datasets").joinpath(
        "manifests", "phase5_datasets.json"
    )
    return Path(str(resource))
