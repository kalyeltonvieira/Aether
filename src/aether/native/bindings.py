"""Portable ctypes wrapper for the optional Rust dynamic-graph library.

Rust owns the only live graph copy. Batch methods pass contiguous caller-owned
buffers and never copy the graph across the ABI. The wrapper serializes access
to one handle because the Rust traversal reuses mutable work buffers.
"""
from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
import threading
from array import array
from pathlib import Path

_U32 = ctypes.c_uint32
_U8 = ctypes.c_uint8
_SIZE = ctypes.c_size_t
_PTR = ctypes.c_void_p
_ABI_VERSION = 2

_PLATFORM_IDS = {"Windows": 1, "Linux": 2, "Darwin": 3}
_ARCH_IDS = {
    "x86_64": 1,
    "amd64": 1,
    "aarch64": 2,
    "arm64": 2,
    "x86": 3,
    "i386": 3,
    "i686": 3,
    "arm": 4,
    "armv7l": 4,
    "riscv64": 5,
}


def _native_build_dir() -> Path:
    """Return a per-user writable directory, independent of site-packages."""
    configured = os.environ.get("AETHER_NATIVE_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Aether" / "native"
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_home / "aether" / "native"


_ERROR_MESSAGES = {
    -1: "Rust FFI recebeu um ponteiro nulo inesperado",
    -2: "Rust FFI rejeitou IDs, comprimentos ou argumentos inválidos",
    -3: "Rust não conseguiu reservar memória para a operação",
    -4: "um panic Rust foi contido na fronteira FFI",
    -5: "overflow de tamanho ou contador na fronteira FFI",
    -6: "buffer de saída menor que o necessário",
}


def _native_filename(system: str | None = None) -> str:
    system = system or platform.system()
    if system == "Windows":
        return "aether_native.dll"
    if system == "Linux":
        return "libaether_native.so"
    if system == "Darwin":
        return "libaether_native.dylib"
    raise RuntimeError(f"Plataforma não suportada pelo backend nativo: {system!r}")


def _platform_id() -> int:
    try:
        return _PLATFORM_IDS[platform.system()]
    except KeyError as exc:
        raise RuntimeError(f"Plataforma não suportada: {platform.system()!r}") from exc


def _arch_id() -> int:
    machine = platform.machine().lower()
    try:
        return _ARCH_IDS[machine]
    except KeyError as exc:
        raise RuntimeError(f"Arquitetura não suportada pelo backend nativo: {machine!r}") from exc


def compile_native(output: str | os.PathLike | None = None) -> Path:
    """Compile the Rust cdylib for the current OS/architecture and return it."""
    root = Path(__file__).resolve().parent
    output_path = Path(output) if output is not None else _native_build_dir() / _native_filename()
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source = root / "rust" / "aether_native.rs"
    project_root = next(
        (candidate for candidate in Path(__file__).resolve().parents
         if (candidate / "rust-toolchain.toml").is_file()),
        None,
    )
    rustc = shutil.which("rustc")
    if rustc is None:
        raise FileNotFoundError(
            "rustc não foi encontrado no PATH. Instale o toolchain Rust e tente novamente."
        )
    command = [
        rustc,
        "-O",
        "--edition=2021",
        "--crate-type=cdylib",
        "-C",
        "panic=unwind",
        str(source),
        "-o",
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            cwd=project_root,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"Falha ao compilar a biblioteca AETHER com rustc: {detail}") from exc
    if completed.stderr.strip():
        # Keep compiler warnings visible; they can indicate target/toolchain issues.
        print(completed.stderr.rstrip())
    return output_path


def _configure_library(lib: ctypes.CDLL) -> None:
    signatures = {
        "aether_graph_abi_version": ([], ctypes.c_uint32),
        "aether_graph_pointer_width": ([], ctypes.c_uint32),
        "aether_graph_platform_id": ([], ctypes.c_uint32),
        "aether_graph_arch_id": ([], ctypes.c_uint32),
        "aether_graph_new": ([_SIZE], _PTR),
        "aether_graph_free": ([_PTR], None),
        "aether_graph_add_edges": ([_PTR, ctypes.POINTER(_U32), _SIZE], ctypes.c_int64),
        "aether_graph_remove_edges": ([_PTR, ctypes.POINTER(_U32), _SIZE], ctypes.c_int64),
        "aether_graph_reachable_many": (
            [_PTR, ctypes.POINTER(_U32), ctypes.POINTER(_U8), _SIZE], ctypes.c_int64
        ),
        "aether_graph_add_edge": ([_PTR, _U32, _U32], ctypes.c_int64),
        "aether_graph_remove_edge": ([_PTR, _U32, _U32], ctypes.c_int64),
        "aether_graph_has_edge": ([_PTR, _U32, _U32], ctypes.c_int64),
        "aether_graph_reachable": ([_PTR, _U32, _U32], ctypes.c_int64),
        "aether_graph_edge_count": ([_PTR], ctypes.c_int64),
        "aether_graph_memory_bytes": ([_PTR], ctypes.c_int64),
        "aether_graph_neighbor_count": ([_PTR, _U32], ctypes.c_int64),
        "aether_graph_copy_neighbors": (
            [_PTR, _U32, ctypes.POINTER(_U32), _SIZE], ctypes.c_int64
        ),
    }
    try:
        for name, (argtypes, restype) in signatures.items():
            function = getattr(lib, name)
            function.argtypes = argtypes
            function.restype = restype
    except AttributeError as exc:
        raise RuntimeError(
            "A biblioteca nativa não expõe a ABI exigida pela Fase 5; recompile-a."
        ) from exc

    version = int(lib.aether_graph_abi_version())
    if version != _ABI_VERSION:
        raise RuntimeError(
            f"Versão ABI incompatível: biblioteca={version}, wrapper={_ABI_VERSION}. "
            "Recompile a biblioteca nativa."
        )
    pointer_width = int(lib.aether_graph_pointer_width())
    python_pointer_width = ctypes.sizeof(_PTR) * 8
    if pointer_width != python_pointer_width:
        raise RuntimeError(
            f"Largura de ponteiro incompatível: biblioteca={pointer_width}, "
            f"Python={python_pointer_width}."
        )
    native_platform = int(lib.aether_graph_platform_id())
    expected_platform = _platform_id()
    if native_platform != expected_platform:
        raise RuntimeError(
            f"Plataforma da biblioteca incompatível: biblioteca={native_platform}, "
            f"Python={expected_platform}."
        )
    native_arch = int(lib.aether_graph_arch_id())
    expected_arch = _arch_id()
    if native_arch != expected_arch:
        raise RuntimeError(
            f"Arquitetura da biblioteca incompatível: biblioteca={native_arch}, "
            f"Python={expected_arch}."
        )


def _load_library(path: str | os.PathLike | None = None) -> ctypes.CDLL:
    if path is None:
        path = os.environ.get("AETHER_NATIVE_LIB")
    library_path = (
        Path(path).expanduser()
        if path
        else _native_build_dir() / _native_filename()
    )
    if not library_path.exists():
        library_path = compile_native(library_path)
    library_path = library_path.resolve()
    try:
        lib = ctypes.CDLL(str(library_path))
    except OSError as exc:
        raise OSError(
            f"Não foi possível carregar {library_path} em "
            f"{platform.system()}/{platform.machine()}: {exc}"
        ) from exc
    _configure_library(lib)
    return lib


def _check_node(node: int, n: int) -> None:
    if isinstance(node, bool) or not isinstance(node, int) or not 0 <= node < n:
        raise IndexError(f"node id must be an integer in [0, {n})")


def _pack_pairs(pairs, n: int) -> array:
    packed = array("I")
    if packed.itemsize != 4:
        raise RuntimeError("array('I') deve conter inteiros de 32 bits")
    try:
        iterator = iter(pairs)
    except TypeError as exc:
        raise TypeError("pares deve ser uma sequência ou iterável de (u, v)") from exc
    for index, pair in enumerate(iterator):
        try:
            u, v = pair
        except (TypeError, ValueError) as exc:
            raise ValueError(f"par de arestas inválido na posição {index}") from exc
        _check_node(u, n)
        _check_node(v, n)
        packed.extend((u, v))
    return packed


def _u32_pointer(values: array):
    if not values:
        return ctypes.POINTER(_U32)()
    return ctypes.cast(ctypes.c_void_p(values.buffer_info()[0]), ctypes.POINTER(_U32))


def _raise_status(status: int, operation: str) -> None:
    if status >= 0:
        return
    message = _ERROR_MESSAGES.get(status, f"código de erro nativo desconhecido {status}")
    if status == -3:
        raise MemoryError(f"{operation}: {message}")
    if status == -2:
        raise ValueError(f"{operation}: {message}")
    if status == -5:
        raise OverflowError(f"{operation}: {message}")
    if status == -6:
        raise BufferError(f"{operation}: {message}")
    raise RuntimeError(f"{operation}: {message}")


class RustDynamicGraph:
    """Exact mutable directed graph whose only live adjacency is Rust-owned."""

    backend = "rust_vec_rows"

    def __init__(self, n: int, initial_edges=(), library=None):
        if isinstance(n, bool) or not isinstance(n, int) or n < 1 or n > 0xFFFFFFFF:
            raise ValueError("n must be an integer in [1, 2**32-1]")
        self.n = n
        self._lib = _load_library(library)
        self._lock = threading.RLock()
        self._handle = self._lib.aether_graph_new(n)
        self._closed = False
        if not self._handle:
            raise MemoryError(f"Rust não conseguiu criar um grafo com {n} nós")
        try:
            packed = _pack_pairs(initial_edges, self.n)
            changed = self._add_edges_packed(packed)
            expected = len(packed) // 2
            if changed != expected:
                raise ValueError(
                    "initial edge stream contains duplicate edges; "
                    "bulk updates otherwise ignore duplicates"
                )
        except Exception:
            self.close()
            raise

    @property
    def closed(self) -> bool:
        return self._closed

    def _ensure_open(self) -> None:
        if self._closed or not self._handle:
            raise RuntimeError("RustDynamicGraph já foi fechado")

    def _add_edges_packed(self, packed: array) -> int:
        self._ensure_open()
        status = int(
            self._lib.aether_graph_add_edges(
                self._handle, _u32_pointer(packed), len(packed)
            )
        )
        _raise_status(status, "add_edges")
        return status

    def add_edge(self, u: int, v: int) -> bool:
        _check_node(u, self.n)
        _check_node(v, self.n)
        with self._lock:
            self._ensure_open()
            status = int(self._lib.aether_graph_add_edge(self._handle, u, v))
            _raise_status(status, "add_edge")
            return bool(status)

    def remove_edge(self, u: int, v: int) -> bool:
        _check_node(u, self.n)
        _check_node(v, self.n)
        with self._lock:
            self._ensure_open()
            status = int(self._lib.aether_graph_remove_edge(self._handle, u, v))
            _raise_status(status, "remove_edge")
            return bool(status)

    def has_edge(self, u: int, v: int) -> bool:
        _check_node(u, self.n)
        _check_node(v, self.n)
        with self._lock:
            self._ensure_open()
            status = int(self._lib.aether_graph_has_edge(self._handle, u, v))
            _raise_status(status, "has_edge")
            return bool(status)

    def reachable(self, source: int, target: int) -> bool:
        _check_node(source, self.n)
        _check_node(target, self.n)
        with self._lock:
            self._ensure_open()
            status = int(
                self._lib.aether_graph_reachable(self._handle, source, target)
            )
            _raise_status(status, "reachable")
            return bool(status)

    def add_edges(self, edges) -> int:
        """Insert many edges with one ABI call; return the number newly added."""
        packed = _pack_pairs(edges, self.n)
        with self._lock:
            return self._add_edges_packed(packed)

    def remove_edges(self, edges) -> int:
        """Remove many edges with one ABI call; missing edges are ignored."""
        packed = _pack_pairs(edges, self.n)
        with self._lock:
            self._ensure_open()
            status = int(
                self._lib.aether_graph_remove_edges(
                    self._handle, _u32_pointer(packed), len(packed)
                )
            )
            _raise_status(status, "remove_edges")
            return status

    def reachable_many(self, pairs, out_buffer=None) -> memoryview:
        """Query a batch and return a zero-copy memoryview of 0/1 result bytes.

        Pass a writable, contiguous byte buffer as ``out_buffer`` to reuse it.
        The returned view aliases that buffer; callers own its lifetime.
        """
        packed = _pack_pairs(pairs, self.n)
        query_count = len(packed) // 2
        if out_buffer is None:
            out_buffer = bytearray(query_count)
        try:
            raw_view = memoryview(out_buffer)
            if raw_view.readonly:
                raise ValueError("out_buffer deve ser gravável")
            if not raw_view.contiguous:
                raise ValueError("out_buffer deve ser contíguo")
            result_view = raw_view.cast("B")
        except TypeError as exc:
            raise TypeError("out_buffer deve expor um buffer contíguo de bytes") from exc
        if result_view.nbytes < query_count:
            raise ValueError(
                f"out_buffer tem {result_view.nbytes} bytes; são necessários {query_count}"
            )
        output_storage = None
        output_pointer = ctypes.POINTER(_U8)()
        if query_count:
            output_storage = (_U8 * result_view.nbytes).from_buffer(result_view)
            output_pointer = ctypes.cast(
                ctypes.addressof(output_storage), ctypes.POINTER(_U8)
            )
        with self._lock:
            self._ensure_open()
            status = int(
                self._lib.aether_graph_reachable_many(
                    self._handle,
                    _u32_pointer(packed),
                    output_pointer,
                    query_count,
                )
            )
            _raise_status(status, "reachable_many")
        # Keep ctypes' export alive through the FFI call; the memoryview owns its
        # Python exporter after return and does not copy the query results.
        _ = output_storage
        return result_view[:query_count]

    def edge_count(self) -> int:
        with self._lock:
            self._ensure_open()
            status = int(self._lib.aether_graph_edge_count(self._handle))
            _raise_status(status, "edge_count")
            return status

    def memory_bytes(self) -> int:
        """Estimate Rust-owned capacities; allocator metadata is not included."""
        with self._lock:
            self._ensure_open()
            status = int(self._lib.aether_graph_memory_bytes(self._handle))
            _raise_status(status, "memory_bytes")
            return status

    def neighbors(self, node: int) -> array:
        """Copy a node's outgoing IDs into a Python array for graph algorithms."""
        _check_node(node, self.n)
        with self._lock:
            self._ensure_open()
            count = int(self._lib.aether_graph_neighbor_count(self._handle, node))
            _raise_status(count, "neighbor_count")
            values = array("I", [0]) * count
            if values.itemsize != 4:
                raise RuntimeError("array('I') deve conter inteiros de 32 bits")
            output_pointer = _u32_pointer(values)
            copied = int(
                self._lib.aether_graph_copy_neighbors(
                    self._handle, node, output_pointer, count
                )
            )
            _raise_status(copied, "copy_neighbors")
            if copied != count:
                raise RuntimeError("Rust retornou uma contagem de vizinhos inconsistente")
            return values

    def close(self) -> None:
        lock = getattr(self, "_lock", None)
        if lock is None:
            return
        with lock:
            handle = getattr(self, "_handle", None)
            if handle:
                library = self._lib
                library.aether_graph_free(handle)
            self._handle = None
            self._closed = True
            # A ctypes library handle pins the DLL on Windows. Once the native
            # graph is freed, dropping this reference allows temporary build
            # directories to be removed and the library to be replaced.
            self._lib = None

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
