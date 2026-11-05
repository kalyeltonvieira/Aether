"""Incremental operational access-pattern learner for AETHER phase 6.

It learns only observable operation frequencies and short transitions. It does
not infer meaning, truth or semantic relevance.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class PatternEvent:
    kind: str
    key: str


class IncrementalPatternLearner:
    """O(1) update counters for keys, operation kinds and adjacent transitions."""

    def __init__(self, *, max_transition_targets: int = 64):
        if isinstance(max_transition_targets, bool) or not isinstance(max_transition_targets, int):
            raise TypeError("max_transition_targets must be an integer")
        if max_transition_targets < 1:
            raise ValueError("max_transition_targets must be positive")
        self.max_transition_targets = max_transition_targets
        self.events_seen = 0
        self._key_counts: Counter[str] = Counter()
        self._kind_counts: Counter[str] = Counter()
        self._transitions: dict[PatternEvent, Counter[PatternEvent]] = defaultdict(Counter)
        self._last: PatternEvent | None = None

    def observe(self, kind: str, key: str) -> None:
        if not isinstance(kind, str) or not kind:
            raise ValueError("kind must be a non-empty string")
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        event = PatternEvent(kind, key)
        self.events_seen += 1
        self._key_counts[key] += 1
        self._kind_counts[kind] += 1
        if self._last is not None:
            targets = self._transitions[self._last]
            targets[event] += 1
            if len(targets) > self.max_transition_targets:
                least_common = min(targets.items(), key=lambda pair: (pair[1], pair[0].kind, pair[0].key))[0]
                del targets[least_common]
        self._last = event

    def key_frequency(self, key: str) -> int:
        return self._key_counts[key]

    def kind_frequency(self, kind: str) -> int:
        return self._kind_counts[kind]

    def hot_keys(self, limit: int = 10) -> list[tuple[str, int]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        return self._key_counts.most_common(limit)

    def predict_next(self, kind: str, key: str, limit: int = 5) -> list[tuple[PatternEvent, int]]:
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        current = PatternEvent(kind, key)
        return self._transitions.get(current, Counter()).most_common(limit)

    def transition_frequency(self, previous: PatternEvent, current: PatternEvent) -> int:
        return self._transitions.get(previous, Counter())[current]

    def stats(self) -> dict:
        transition_count = sum(len(targets) for targets in self._transitions.values())
        return {
            "events_seen": self.events_seen,
            "distinct_keys": len(self._key_counts),
            "distinct_kinds": len(self._kind_counts),
            "transition_sources": len(self._transitions),
            "transition_edges": transition_count,
            "max_transition_targets": self.max_transition_targets,
        }
