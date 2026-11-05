"""Experimental event log for time-varying directed AETHER graphs.

Events are retained in compact parallel arrays. The current graph is one mutable
compact adjacency structure. Historical states are reconstructed on demand; this
prototype does not retain one full graph snapshot per timestamp.
"""
from __future__ import annotations

import bisect
import sys
from array import array

from aether.graph.dynamic import DynamicGraph


class TemporalEdgeHistory:
    """Append-only, timestamp-ordered edge event log with a live current state.

    Operations are ``"add"`` and ``"remove"``. Event order at an equal timestamp
    is the input order (sequence index). Duplicate/no-op events are preserved in
    history even though they do not change current adjacency.
    """

    _ADD = 1
    _REMOVE = 0

    def __init__(self, n: int):
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 0xFFFFFFFF:
            raise ValueError("n must be an integer in [1, 2**32-1]")
        if array("Q").itemsize != 8 or array("I").itemsize != 4:
            raise RuntimeError("temporal log requires 64-bit timestamps and 32-bit node IDs")
        self.n = n
        self.current = DynamicGraph(n, "compact")
        self._timestamps = array("Q")
        self._sources = array("I")
        self._targets = array("I")
        self._operations = bytearray()
        self._edge_count = 0

    @property
    def event_count(self) -> int:
        return len(self._timestamps)

    @property
    def edge_count(self) -> int:
        return self._edge_count

    @property
    def cached_snapshots(self) -> int:
        return 0

    @property
    def log_memory_bytes(self) -> int:
        """Python estimates for the retained compact arrays, including capacity."""
        return (
            sys.getsizeof(self._timestamps)
            + sys.getsizeof(self._sources)
            + sys.getsizeof(self._targets)
            + sys.getsizeof(self._operations)
        )

    def memory_bytes(self) -> int:
        return self.log_memory_bytes + self.current.memory_bytes()

    def append(self, timestamp: int, operation: str, source: int, target: int) -> bool:
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or not 0 <= timestamp <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("timestamp must be an integer in [0, 2**64-1]")
        if operation not in ("add", "remove"):
            raise ValueError("operation must be 'add' or 'remove'")
        self.current._check(source, target)
        if self._timestamps and timestamp < self._timestamps[-1]:
            raise ValueError("events must be appended in non-decreasing timestamp order")
        opcode = self._ADD if operation == "add" else self._REMOVE

        # Extend the history first. Roll back partial array growth if allocation
        # fails; the live graph has not been mutated yet.
        previous_length = self.event_count
        try:
            self._timestamps.append(timestamp)
            self._sources.append(source)
            self._targets.append(target)
            self._operations.append(opcode)
        except Exception:
            del self._timestamps[previous_length:]
            del self._sources[previous_length:]
            del self._targets[previous_length:]
            del self._operations[previous_length:]
            raise

        try:
            if opcode == self._ADD:
                changed = self.current.add_edge(source, target)
                self._edge_count += int(changed)
            else:
                changed = self.current.remove_edge(source, target)
                self._edge_count -= int(changed)
        except Exception:
            del self._timestamps[previous_length:]
            del self._sources[previous_length:]
            del self._targets[previous_length:]
            del self._operations[previous_length:]
            raise
        return changed

    def _replay(self, event_count: int) -> DynamicGraph:
        if isinstance(event_count, bool) or not isinstance(event_count, int) or not 0 <= event_count <= self.event_count:
            raise IndexError("event_count must be between 0 and the current event count")
        graph = DynamicGraph(self.n, "compact")
        for index in range(event_count):
            source, target = self._sources[index], self._targets[index]
            if self._operations[index] == self._ADD:
                graph.add_edge(source, target)
            else:
                graph.remove_edge(source, target)
        return graph

    def state_at_event_count(self, event_count: int) -> DynamicGraph:
        """Reconstruct the state after exactly ``event_count`` ordered events."""
        return self._replay(event_count)

    def state_at_timestamp(self, timestamp: int) -> DynamicGraph:
        """Rebuild the historical state after all events with time <= timestamp."""
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise ValueError("timestamp must be a non-negative integer")
        event_count = bisect.bisect_right(self._timestamps, timestamp)
        return self._replay(event_count)

    def current_neighbors(self, node: int):
        return self.current.neighbors(node)

    def has_edge(self, source: int, target: int) -> bool:
        return self.current.has_edge(source, target)
