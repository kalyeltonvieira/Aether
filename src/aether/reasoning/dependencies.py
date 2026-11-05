"""Dependency tracking and localized invalidation for phase 7 conclusions."""
from __future__ import annotations

from dataclasses import dataclass

from aether.reasoning.inference import DerivedFact, InferenceResult


DerivedKey = tuple[str, str, object]


@dataclass(frozen=True)
class InvalidationStats:
    requested_supports: int
    conclusions_visited: int
    conclusions_invalidated: int
    remaining_conclusions: int


class DependencyTracker:
    """Maintain reverse dependencies so removals do not scan unrelated proofs."""

    def __init__(self, result: InferenceResult):
        if not isinstance(result, InferenceResult):
            raise TypeError("result must be an InferenceResult")
        self._facts: dict[DerivedKey, DerivedFact] = {fact.key: fact for fact in result.conclusions}
        self._dependents: dict[int | DerivedKey, set[DerivedKey]] = {}
        for fact in result.conclusions:
            for support in fact.supports:
                self._dependents.setdefault(support, set()).add(fact.key)
        self.invalidated_total = 0
        self.visited_total = 0

    @property
    def active(self) -> tuple[DerivedFact, ...]:
        return tuple(self._facts.values())

    def invalidate(self, support_ids: set[int] | frozenset[int], support_keys: set[DerivedKey] | frozenset[DerivedKey] = frozenset()) -> InvalidationStats:
        if not isinstance(support_ids, (set, frozenset)) or not isinstance(support_keys, (set, frozenset)):
            raise TypeError("support_ids and support_keys must be sets")
        queue: list[int | DerivedKey] = [*support_ids, *support_keys]
        seen_supports: set[int | DerivedKey] = set(queue)
        impacted: set[DerivedKey] = set()
        impacted.update(key for key in support_keys if key in self._facts)
        while queue:
            support = queue.pop(0)
            for dependent in self._dependents.get(support, ()):
                if dependent in impacted:
                    continue
                impacted.add(dependent)
                if dependent not in seen_supports:
                    seen_supports.add(dependent)
                    queue.append(dependent)
        for key in impacted:
            self._facts.pop(key, None)
        self.invalidated_total += len(impacted)
        self.visited_total += len(seen_supports)
        return InvalidationStats(
            requested_supports=len(support_ids) + len(support_keys),
            conclusions_visited=len(seen_supports),
            conclusions_invalidated=len(impacted),
            remaining_conclusions=len(self._facts),
        )

    def add(self, conclusions: tuple[DerivedFact, ...] | list[DerivedFact]) -> None:
        for fact in conclusions:
            self._facts[fact.key] = fact
            for support in fact.supports:
                self._dependents.setdefault(support, set()).add(fact.key)

    def stats(self) -> dict[str, int]:
        return {
            "active_conclusions": len(self._facts),
            "dependency_keys": len(self._dependents),
            "invalidated_total": self.invalidated_total,
            "visited_total": self.visited_total,
        }
