"""Small, optional platform-specific process/system memory measurements.

All public functions return bytes or ``None`` when an OS metric is genuinely
unavailable. Callers must preserve nulls rather than substitute zero or relabel
peak RSS as current RSS.
"""
from __future__ import annotations

import os
import platform
import sys
from typing import Optional


def _windows_memory_counters() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class ProcessMemoryCountersEx(ctypes.Structure):
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
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCountersEx),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        if not psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return None
        return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)
    except (AttributeError, OSError, ImportError, ValueError):
        return None


def _macos_current_rss_bytes() -> Optional[int]:
    """Read resident_size from Mach task_info (TASK_BASIC_INFO_64)."""
    if sys.platform != "darwin":
        return None
    try:
        import ctypes

        class TimeValue(ctypes.Structure):
            _fields_ = [("seconds", ctypes.c_int), ("microseconds", ctypes.c_int)]

        class TaskBasicInfo64(ctypes.Structure):
            _fields_ = [
                ("virtual_size", ctypes.c_uint64),
                ("resident_size", ctypes.c_uint64),
                ("resident_size_max", ctypes.c_uint64),
                ("user_time", TimeValue),
                ("system_time", TimeValue),
                ("policy", ctypes.c_int),
                ("suspend_count", ctypes.c_int),
            ]

        libsystem = ctypes.CDLL(None)
        task_port = ctypes.c_uint32.in_dll(libsystem, "mach_task_self_").value
        task_info = libsystem.task_info
        task_info.argtypes = [
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.POINTER(TaskBasicInfo64),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        task_info.restype = ctypes.c_int
        info = TaskBasicInfo64()
        count = ctypes.c_uint32(ctypes.sizeof(info) // ctypes.sizeof(ctypes.c_uint32))
        result = task_info(task_port, 5, ctypes.byref(info), ctypes.byref(count))
        return int(info.resident_size) if result == 0 else None
    except (AttributeError, OSError, ValueError):
        return None


def current_rss_bytes() -> Optional[int]:
    """Return current resident set size in bytes, or ``None`` if unavailable."""
    if sys.platform == "linux":
        try:
            with open("/proc/self/status", encoding="ascii") as stream:
                for line in stream:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
        return None
    if sys.platform == "win32":
        values = _windows_memory_counters()
        return values[0] if values is not None else None
    if sys.platform == "darwin":
        return _macos_current_rss_bytes()
    return None


def peak_rss_bytes() -> Optional[int]:
    """Return process peak RSS in bytes, accounting for POSIX unit differences."""
    if sys.platform == "win32":
        values = _windows_memory_counters()
        return values[1] if values is not None else None
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes; Linux and the supported BSD-style resource APIs
        # report KiB. Do not import resource at module import time on Windows.
        return int(value) if sys.platform == "darwin" else int(value * 1024)
    except (ImportError, AttributeError, OSError, ValueError):
        return None


def total_physical_memory_bytes() -> Optional[int]:
    """Return installed physical memory in bytes, or ``None`` if unavailable."""
    if sys.platform == "linux":
        try:
            with open("/proc/meminfo", encoding="ascii") as stream:
                for line in stream:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
        return None
    if sys.platform == "win32":
        try:
            import ctypes

            class MemoryStatusEx(ctypes.Structure):
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

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(status)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatusEx)]
            kernel32.GlobalMemoryStatusEx.restype = ctypes.c_int
            if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except (AttributeError, OSError, ImportError, ValueError):
            return None
        return None
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return int(pages * page_size)
    except (AttributeError, OSError, ValueError):
        pass
    return None


def cpu_model() -> str | None:
    """Return a best-effort CPU model string; unknown is not fabricated."""
    if sys.platform == "linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as stream:
                for line in stream:
                    if line.lower().startswith(("model name", "hardware")):
                        value = line.split(":", 1)[-1].strip()
                        if value:
                            return value
        except OSError:
            return None
    value = platform.processor().strip()
    return value or None
