"""ctypes wrapper for the optional Rust mutable reachability engine.

Rust owns the live graph after one bulk import. There is no Python-side mirror.
The ABI is deliberately tiny: create/import once, then call for each update/query.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
from array import array
from pathlib import Path

_U32 = ctypes.c_uint32
_SIZE = ctypes.c_size_t
_PTR = ctypes.c_void_p


def compile_native(output: str | os.PathLike | None = None) -> Path:
    """Build optimized shared library and return its path; compiler time is external."""
    root = Path(__file__).resolve().parent
    output = Path(output) if output else root / "build" / "libaether_native.so"
    output.parent.mkdir(parents=True, exist_ok=True)
    source = root / "aether_native.rs"
    subprocess.run(
        ["rustc", "-O", "--edition=2021", "--crate-type=cdylib", str(source), "-o", str(output)],
        check=True,
    )
    return output


def _load_library(path: str | os.PathLike | None = None) -> ctypes.CDLL:
    if path is None:
        path = os.environ.get("AETHER_NATIVE_LIB")
    library_path = Path(path) if path else Path(__file__).resolve().parent / "build" / "libaether_native.so"
    if not library_path.exists():
        library_path = compile_native(library_path)
    lib = ctypes.CDLL(str(library_path))
    lib.aether_graph_new.argtypes = [_SIZE]
    lib.aether_graph_new.restype = _PTR
    lib.aether_graph_free.argtypes = [_PTR]
    lib.aether_graph_free.restype = None
    lib.aether_graph_add_edges.argtypes = [_PTR, ctypes.POINTER(_U32), _SIZE]
    lib.aether_graph_add_edges.restype = ctypes.c_int64
    lib.aether_graph_add_edge.argtypes = [_PTR, _U32, _U32]
    lib.aether_graph_add_edge.restype = ctypes.c_int
    lib.aether_graph_remove_edge.argtypes = [_PTR, _U32, _U32]
    lib.aether_graph_remove_edge.restype = ctypes.c_int
    lib.aether_graph_has_edge.argtypes = [_PTR, _U32, _U32]
    lib.aether_graph_has_edge.restype = ctypes.c_int
    lib.aether_graph_reachable.argtypes = [_PTR, _U32, _U32]
    lib.aether_graph_reachable.restype = ctypes.c_int
    lib.aether_graph_edge_count.argtypes = [_PTR]
    lib.aether_graph_edge_count.restype = _SIZE
    lib.aether_graph_memory_bytes.argtypes = [_PTR]
    lib.aether_graph_memory_bytes.restype = _SIZE
    return lib


class RustDynamicGraph:
    """Exact dynamic graph whose sole live adjacency storage is Rust-owned."""

    backend = "rust_vec_rows"

    def __init__(self, n: int, initial_edges=(), library=None):
        if not isinstance(n, int) or n < 1 or n > 0xFFFFFFFF:
            raise ValueError("n must be an integer in [1, 2**32-1]")
        self.n = n
        self._lib = _load_library(library)
        self._handle = self._lib.aether_graph_new(n)
        if not self._handle:
            raise MemoryError("Rust graph allocation failed")
        self.closed = False
        flat = array("I")
        if flat.itemsize != 4:
            self.close()
            raise RuntimeError("array('I') must contain 32-bit unsigned integers")
        for u, v in initial_edges:
            self._check(u, v)
            flat.extend((u, v))
        if flat:
            changed = self._lib.aether_graph_add_edges(
                self._handle, flat.buffer_info()[0] and ctypes.cast(flat.buffer_info()[0], ctypes.POINTER(_U32)), len(flat)
            )
            expected = len(flat) // 2
            if changed < 0 or changed != expected:
                self.close()
                raise ValueError("initial edge stream contains duplicate edges or import failed")

    def _check(self, u, v):
        if not isinstance(u, int) or not isinstance(v, int) or not (0 <= u < self.n and 0 <= v < self.n):
            raise IndexError("node ids out of range")

    def add_edge(self, u, v):
        self._check(u, v)
        result = self._lib.aether_graph_add_edge(self._handle, u, v)
        if result < 0:
            raise RuntimeError("Rust add_edge failed")
        return bool(result)

    def remove_edge(self, u, v):
        self._check(u, v)
        result = self._lib.aether_graph_remove_edge(self._handle, u, v)
        if result < 0:
            raise RuntimeError("Rust remove_edge failed")
        return bool(result)

    def has_edge(self, u, v):
        self._check(u, v)
        result = self._lib.aether_graph_has_edge(self._handle, u, v)
        if result < 0:
            raise RuntimeError("Rust has_edge failed")
        return bool(result)

    def reachable(self, source, target):
        self._check(source, target)
        result = self._lib.aether_graph_reachable(self._handle, source, target)
        if result < 0:
            raise RuntimeError("Rust reachability query failed")
        return bool(result)

    def edge_count(self):
        return int(self._lib.aether_graph_edge_count(self._handle))

    def memory_bytes(self):
        """Rust-retained allocation estimate (capacities, not allocator metadata)."""
        return int(self._lib.aether_graph_memory_bytes(self._handle))

    def close(self):
        if getattr(self, "_handle", None):
            self._lib.aether_graph_free(self._handle)
            self._handle = None
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
