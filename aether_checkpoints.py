"""Selective temporal checkpoints for AETHER phase 6.

Snapshots are immutable edge tuples. The current graph remains a mutable compact
adjacency; historical recovery chooses the nearest checkpoint and replays only
the suffix after it. The policy is explicit and records maintenance/recovery
costs rather than hiding them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from aether_dynamic import DynamicGraph


@dataclass(frozen=True)
class Checkpoint:
    event_count: int
    edges: tuple[tuple[int, int], ...]
    created_bytes: int


class SelectiveCheckpointHistory:
    """Exact append-only temporal history with optional selective checkpoints."""

    STRATEGIES = ("replay", "periodic", "adaptive")

    def __init__(
        self,
        n: int,
        *,
        strategy: str = "adaptive",
        interval: int = 128,
        target_recovery_ms: float = 2.0,
        max_checkpoints: int = 64,
    ):
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ValueError("n must be a positive integer")
        if strategy not in self.STRATEGIES:
            raise ValueError(f"strategy must be one of {self.STRATEGIES}")
        if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
            raise ValueError("interval must be a positive integer")
        if not isinstance(target_recovery_ms, (int, float)) or target_recovery_ms <= 0:
            raise ValueError("target_recovery_ms must be positive")
        if isinstance(max_checkpoints, bool) or not isinstance(max_checkpoints, int) or max_checkpoints < 1:
            raise ValueError("max_checkpoints must be positive")
        self.n = n
        self.strategy = strategy
        self.interval = interval
        self.target_recovery_ms = float(target_recovery_ms)
        self.max_checkpoints = max_checkpoints
        self.current = DynamicGraph(n, "compact")
        self._events: list[tuple[int, str, int, int]] = []
        self._checkpoints: dict[int, Checkpoint] = {}
        self._next_checkpoint = interval
        self._last_checkpoint_event = 0
        self._replay_ema_ms: float | None = None
        self._last_recovery_ms = 0.0
        self.recovery_count = 0
        self.replayed_events = 0
        self.checkpoint_creations = 0
        self.checkpoint_bytes = 0

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def checkpoint_count(self) -> int:
        return len(self._checkpoints)

    @staticmethod
    def _snapshot(graph: DynamicGraph) -> tuple[tuple[int, int], ...]:
        return tuple((source, target) for source in range(graph.n) for target in graph.neighbors(source))

    @staticmethod
    def _snapshot_bytes(edges: tuple[tuple[int, int], ...]) -> int:
        return len(edges) * 8

    def _make_checkpoint(self) -> None:
        count = self.event_count
        if count == 0 or count == self._last_checkpoint_event:
            return
        edges = self._snapshot(self.current)
        checkpoint = Checkpoint(count, edges, self._snapshot_bytes(edges))
        self._checkpoints[count] = checkpoint
        self._last_checkpoint_event = count
        self.checkpoint_creations += 1
        self.checkpoint_bytes += checkpoint.created_bytes
        if len(self._checkpoints) > self.max_checkpoints:
            oldest = min(self._checkpoints)
            removed = self._checkpoints.pop(oldest)
            self.checkpoint_bytes -= removed.created_bytes

    def _maybe_checkpoint(self) -> None:
        if self.strategy == "replay":
            return
        if self.event_count < self._next_checkpoint:
            return
        self._make_checkpoint()
        if self.strategy == "periodic":
            self._next_checkpoint = self.event_count + self.interval
        else:
            interval = max(1, self.interval)
            if self._replay_ema_ms is not None and self._replay_ema_ms > self.target_recovery_ms:
                interval = max(1, interval // 2)
            elif self._replay_ema_ms is not None and self._replay_ema_ms < self.target_recovery_ms / 2:
                interval = min(interval * 2, self.interval * 16)
            self._next_checkpoint = self.event_count + interval

    def append(self, timestamp: int, operation: str, source: int, target: int) -> bool:
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise ValueError("timestamp must be a non-negative integer")
        if operation not in ("add", "remove"):
            raise ValueError("operation must be 'add' or 'remove'")
        if self._events and timestamp < self._events[-1][0]:
            raise ValueError("events must be appended in non-decreasing timestamp order")
        changed = (
            self.current.add_edge(source, target)
            if operation == "add"
            else self.current.remove_edge(source, target)
        )
        self._events.append((timestamp, operation, source, target))
        self._maybe_checkpoint()
        return changed

    def _restore(self, checkpoint: Checkpoint | None) -> tuple[DynamicGraph, int]:
        graph = DynamicGraph(self.n, "compact")
        start = 0
        if checkpoint is not None:
            for source, target in checkpoint.edges:
                graph.add_edge(source, target)
            start = checkpoint.event_count
        for _, operation, source, target in self._events[start:]:
            if operation == "add":
                graph.add_edge(source, target)
            else:
                graph.remove_edge(source, target)
        return graph, len(self._events) - start

    def state_at_event_count(self, event_count: int) -> DynamicGraph:
        if isinstance(event_count, bool) or not isinstance(event_count, int) or not 0 <= event_count <= self.event_count:
            raise IndexError("event_count must be between 0 and the current event count")
        started = time.perf_counter_ns()
        checkpoint = None
        if self.strategy != "replay":
            eligible = [count for count in self._checkpoints if count <= event_count]
            if eligible:
                checkpoint = self._checkpoints[max(eligible)]
        graph = DynamicGraph(self.n, "compact")
        start = 0
        if checkpoint is not None:
            for source, target in checkpoint.edges:
                graph.add_edge(source, target)
            start = checkpoint.event_count
        replayed = 0
        for _, operation, source, target in self._events[start:event_count]:
            replayed += 1
            if operation == "add":
                graph.add_edge(source, target)
            else:
                graph.remove_edge(source, target)
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        self.recovery_count += 1
        self.replayed_events += replayed
        self._last_recovery_ms = elapsed_ms
        self._replay_ema_ms = elapsed_ms if self._replay_ema_ms is None else 0.5 * self._replay_ema_ms + 0.5 * elapsed_ms
        return graph

    def state_at_timestamp(self, timestamp: int) -> DynamicGraph:
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise ValueError("timestamp must be a non-negative integer")
        event_count = sum(1 for event in self._events if event[0] <= timestamp)
        return self.state_at_event_count(event_count)

    def stats(self) -> dict:
        return {
            "strategy": self.strategy,
            "event_count": self.event_count,
            "checkpoint_count": self.checkpoint_count,
            "checkpoint_bytes": self.checkpoint_bytes,
            "checkpoint_creations": self.checkpoint_creations,
            "recovery_count": self.recovery_count,
            "replayed_events": self.replayed_events,
            "last_recovery_ms": self._last_recovery_ms,
            "replay_ema_ms": self._replay_ema_ms,
            "next_checkpoint": self._next_checkpoint,
        }
