"""Experimental bounded reachability-result cache with conservative invalidation.

This prototype invalidates the whole cache after every successful graph mutation.
It is deliberately not wired into the default AETHER engine; mutation must flow
through this wrapper or cached values may become stale.
"""
from __future__ import annotations

import sys
import threading
from collections import OrderedDict


class VersionedReachabilityCache:
    """Bounded LRU cache for a caller-supplied exact reachability function."""

    def __init__(self, graph, query_function, max_entries: int = 4096):
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self.graph = graph
        self._query = query_function
        self.max_entries = max_entries
        self._cache = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.invalidations = 0
        self.generation = 0

    def reachable(self, source: int, target: int) -> bool:
        key = (source, target)
        with self._lock:
            if key in self._cache:
                self.hits += 1
                self._cache.move_to_end(key)
                return self._cache[key]
            self.misses += 1
            value = bool(self._query(source, target))
            self._cache[key] = value
            if len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
            return value

    def _after_mutation(self, changed: int) -> None:
        if changed:
            self._cache.clear()
            self.generation += 1
            self.invalidations += 1

    def add_edge(self, source: int, target: int) -> bool:
        with self._lock:
            changed = bool(self.graph.add_edge(source, target))
            self._after_mutation(int(changed))
            return changed

    def remove_edge(self, source: int, target: int) -> bool:
        with self._lock:
            changed = bool(self.graph.remove_edge(source, target))
            self._after_mutation(int(changed))
            return changed

    def add_edges(self, pairs) -> int:
        with self._lock:
            if not hasattr(self.graph, "add_edges"):
                changed = sum(bool(self.graph.add_edge(u, v)) for u, v in pairs)
            else:
                changed = int(self.graph.add_edges(pairs))
            self._after_mutation(changed)
            return changed

    def remove_edges(self, pairs) -> int:
        with self._lock:
            if not hasattr(self.graph, "remove_edges"):
                changed = sum(bool(self.graph.remove_edge(u, v)) for u, v in pairs)
            else:
                changed = int(self.graph.remove_edges(pairs))
            self._after_mutation(changed)
            return changed

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self.generation += 1
            self.invalidations += 1

    @property
    def entries(self) -> int:
        return len(self._cache)

    def memory_bytes(self) -> int:
        """Approximate Python heap retained by the cache and its key/value pairs."""
        with self._lock:
            return sys.getsizeof(self._cache) + sum(
                sys.getsizeof(key) + sys.getsizeof(value)
                for key, value in self._cache.items()
            )

    def stats(self) -> dict:
        with self._lock:
            return {
                "hits": self.hits,
                "misses": self.misses,
                "entries": len(self._cache),
                "capacity": self.max_entries,
                "invalidations": self.invalidations,
                "generation": self.generation,
                "estimated_bytes": self.memory_bytes(),
            }
