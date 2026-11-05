"""Incremental operational access-pattern learner for AETHER phase 6.

It learns only observable operation frequencies and short transitions. It does
not infer meaning, truth or semantic relevance. The counters are deliberately
bounded: when a configured resident set is full, the least frequent entry is
evicted, with lexical tie-breaking for deterministic results. An evicted entry's
frequency is no longer retained; ``events_seen`` remains the complete observed
event count.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass


DEFAULT_MAX_KEYS = 4096
DEFAULT_MAX_KINDS = 64
DEFAULT_MAX_TRANSITION_SOURCES = 4096
DEFAULT_MAX_TRANSITION_TARGETS = 64


@dataclass(frozen=True)
class PatternEvent:
    kind: str
    key: str


class IncrementalPatternLearner:
    """Incremental updates with bounded key, kind, source and target storage.

    Frequency values describe only entries currently resident in the bounded
    operational counters. They are not semantic labels, truth values, or a
    general learning model. ``events_seen`` is intentionally separate and is
    never reduced by eviction.
    """

    def __init__(
        self,
        *,
        max_transition_targets: int = DEFAULT_MAX_TRANSITION_TARGETS,
        max_keys: int = DEFAULT_MAX_KEYS,
        max_kinds: int = DEFAULT_MAX_KINDS,
        max_transition_sources: int = DEFAULT_MAX_TRANSITION_SOURCES,
    ):
        self.max_transition_targets = self._validate_limit(
            max_transition_targets, "max_transition_targets"
        )
        self.max_keys = self._validate_limit(max_keys, "max_keys")
        self.max_kinds = self._validate_limit(max_kinds, "max_kinds")
        self.max_transition_sources = self._validate_limit(
            max_transition_sources, "max_transition_sources"
        )
        self.events_seen = 0
        self._key_counts: Counter[str] = Counter()
        self._kind_counts: Counter[str] = Counter()
        self._transitions: dict[PatternEvent, Counter[PatternEvent]] = defaultdict(Counter)
        self._last: PatternEvent | None = None
        self.key_evictions = 0
        self.kind_evictions = 0
        self.transition_source_evictions = 0
        self.transition_target_evictions = 0

    @staticmethod
    def _validate_limit(value: int, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field} must be an integer")
        if value < 1:
            raise ValueError(f"{field} must be positive")
        return value

    @staticmethod
    def _counter_victim(counter: Counter[str]) -> str:
        """Return the deterministic least frequent string key."""
        return min(counter.items(), key=lambda pair: (pair[1], pair[0]))[0]

    @staticmethod
    def _transition_source_victim(
        transitions: dict[PatternEvent, Counter[PatternEvent]],
    ) -> PatternEvent:
        return min(
            transitions,
            key=lambda source: (
                sum(transitions[source].values()),
                source.kind,
                source.key,
            ),
        )

    @staticmethod
    def _transition_target_victim(targets: Counter[PatternEvent]) -> PatternEvent:
        return min(
            targets.items(),
            key=lambda pair: (pair[1], pair[0].kind, pair[0].key),
        )[0]

    def _observe_counter(
        self,
        counter: Counter[str],
        value: str,
        limit: int,
        eviction_field: str,
    ) -> None:
        counter[value] += 1
        if len(counter) <= limit:
            return
        victim = self._counter_victim(counter)
        del counter[victim]
        setattr(self, eviction_field, getattr(self, eviction_field) + 1)

    def _ensure_transition_source(self, source: PatternEvent) -> Counter[PatternEvent] | None:
        targets = self._transitions.get(source)
        if targets is None:
            targets = Counter()
            self._transitions[source] = targets
        if len(self._transitions) > self.max_transition_sources:
            victim = self._transition_source_victim(self._transitions)
            del self._transitions[victim]
            self.transition_source_evictions += 1
            if victim == source:
                return None
        return targets

    def observe(self, kind: str, key: str) -> None:
        if not isinstance(kind, str) or not kind:
            raise ValueError("kind must be a non-empty string")
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        event = PatternEvent(kind, key)
        self.events_seen += 1
        self._observe_counter(self._key_counts, key, self.max_keys, "key_evictions")
        self._observe_counter(self._kind_counts, kind, self.max_kinds, "kind_evictions")
        if self._last is not None:
            targets = self._ensure_transition_source(self._last)
            if targets is not None:
                targets[event] += 1
                if len(targets) > self.max_transition_targets:
                    least_common = self._transition_target_victim(targets)
                    del targets[least_common]
                    self.transition_target_evictions += 1
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
            "max_keys": self.max_keys,
            "max_kinds": self.max_kinds,
            "max_transition_sources": self.max_transition_sources,
            "max_transition_targets": self.max_transition_targets,
            "key_evictions": self.key_evictions,
            "kind_evictions": self.kind_evictions,
            "transition_source_evictions": self.transition_source_evictions,
            "transition_target_evictions": self.transition_target_evictions,
            "evictions": (
                self.key_evictions
                + self.kind_evictions
                + self.transition_source_evictions
                + self.transition_target_evictions
            ),
        }
