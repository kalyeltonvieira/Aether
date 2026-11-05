"""Portable process-memory measurements used by optional benchmarks.

Missing operating-system metrics are represented by ``None`` rather than zero.
On Windows, peak RSS uses the documented process peak working-set counter.
"""
from __future__ import annotations

import ctypes
import os
import platform
import sys

try:  # Unix-only module; never let its absence block package imports on Windows.
    import resource as _resource
except ImportError:  # pragma: no cover - exercised on Windows
    _resource = None


def _windows_memory_counters() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    try:
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
    except (AttributeError, OSError):
        return None
    if not ok:
        return None
    return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)


def current_rss_bytes() -> int | None:
    """Return current resident/working-set bytes, or ``None`` if unavailable."""
    windows = _windows_memory_counters()
    if windows is not None:
        return windows[0]
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/self/status", encoding="ascii") as stream:
                for line in stream:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
    return None


def peak_rss_bytes() -> int | None:
    """Return process peak resident bytes (Windows peak working set), if known."""
    windows = _windows_memory_counters()
    if windows is not None:
        return windows[1]
    if sys.platform == "win32":
        return None
    if _resource is None:
        return None
    try:
        value = int(_resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, OSError, ValueError):
        return None
    # macOS reports bytes; Linux and the supported BSDs report KiB.
    return value if sys.platform == "darwin" else value * 1024


def peak_rss_kib() -> int | None:
    """Return peak RSS in KiB for historic CSV columns with ``_kib`` suffix."""
    value = peak_rss_bytes()
    return None if value is None else value // 1024


def total_memory_bytes() -> int | None:
    """Return physical memory bytes where the platform exposes a reliable value."""
    if sys.platform == "win32":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        state = MEMORYSTATUSEX()
        state.dwLength = ctypes.sizeof(state)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
                return int(state.ullTotalPhys)
        except (AttributeError, OSError):
            return None
        return None
    if platform.system() == "Linux":
        try:
            with open("/proc/meminfo", encoding="ascii") as stream:
                for line in stream:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages) * int(page_size)
    except (AttributeError, OSError, ValueError):
        return None


def available_memory_bytes() -> int | None:
    """Return currently available physical memory, or ``None`` if unavailable."""
    if sys.platform == "win32":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        state = MEMORYSTATUSEX()
        state.dwLength = ctypes.sizeof(state)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
                return int(state.ullAvailPhys)
        except (AttributeError, OSError):
            return None
        return None
    if platform.system() == "Linux":
        try:
            with open("/proc/meminfo", encoding="ascii") as stream:
                for line in stream:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
    return None


def memory_delta_bytes(after: int | None, before: int | None) -> int | None:
    """Subtract comparable RSS samples, preserving unavailability as ``None``."""
    if after is None or before is None:
        return None
    return after - before


def total_physical_memory_bytes() -> int | None:
    """Compatibility name used by Phase 8 benchmark metadata."""
    return total_memory_bytes()


def cpu_model() -> str | None:
    """Return a best-effort processor model without fabricating unknown values."""
    if sys.platform == "linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as stream:
                for line in stream:
                    if line.lower().startswith(("model name", "hardware")):
                        value = line.split(":", 1)[-1].strip()
                        if value:
                            return value
        except OSError:
            pass
    value = platform.processor().strip()
    return value or None
