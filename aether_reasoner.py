"""Safe orchestration of explicit facts, inference and localized invalidation."""
from __future__ import annotations

from dataclasses import dataclass

from aether_dependencies import DependencyTracker, InvalidationStats
from aether_inference import InferenceEngine, InferenceLimits, InferenceResult, Rule
from aether_incremental import IncrementalInference
from aether_knowledge import Fact, KnowledgeStore, Provenance, Scalar


@dataclass(frozen=True)
class ReasonerState:
    result: InferenceResult
    store_version: int
    complete_for_current_store: bool
    stale_reason: str | None = None


class KnowledgeReasoner:
    """Keep inference state safe across mutations without hiding fallbacks.

    Removal can invalidate a proven dependency region immediately. Additions and
    updates are marked stale until a full recomputation, because a local proof
    of all newly enabled joins is not assumed without an incremental agenda.
    """

    def __init__(self, store: KnowledgeStore, rules: tuple[Rule, ...] | list[Rule] = ()) -> None:
        self.store = store
        self.engine = InferenceEngine(store, rules)
        self._incremental = IncrementalInference(store, rules)
        self._state: ReasonerState | None = None
        self._tracker: DependencyTracker | None = None

    @property
    def state(self) -> ReasonerState | None:
        return self._state

    def recompute(self, limits: InferenceLimits | None = None) -> ReasonerState:
        result = self._incremental.initialize(limits)
        self._tracker = DependencyTracker(result)
        self._state = ReasonerState(result, self.store.version, result.complete, None if result.complete else result.stop_reason)
        return self._state

    def add_fact(
        self,
        subject: str,
        predicate: str,
        object: Scalar,
        *,
        provenance: Provenance | None = None,
        confidence: float | None = None,
    ) -> tuple[Fact, bool]:
        if self._state is not None and self._state.complete_for_current_store:
            fact, update = self._incremental.add_fact(subject, predicate, object, provenance=provenance, confidence=confidence)
            inserted = update.inserted
            result = self._incremental.result()
            if not inserted:
                return fact, False
            if update.complete:
                self._tracker = DependencyTracker(result)
                self._state = ReasonerState(result, self.store.version, True, None)
            else:
                self._state = ReasonerState(result, self.store.version, False, update.stop_reason or "incremental_update_incomplete")
            return fact, True
        fact, inserted = self.store.add_fact(subject, predicate, object, provenance=provenance, confidence=confidence)
        if inserted and self._state is not None:
            self._state = ReasonerState(self._state.result, self.store.version, False, "new_fact_requires_recompute")
        return fact, inserted

    def remove_fact(self, fact_id: int) -> InvalidationStats | None:
        if self._state is None or self._tracker is None:
            self.store.remove_fact(fact_id)
            return None
        stats = self._tracker.invalidate({fact_id})
        self.store.remove_fact(fact_id)
        self._incremental = IncrementalInference(self.store, self.engine.rules)
        remaining = tuple(self._tracker.active)
        result = InferenceResult(
            remaining,
            self._state.result.operations,
            self._state.result.max_depth_reached,
            False,
            "removed_fact_requires_recompute_for_alternative_proofs",
            self._state.result.facts_examined,
            self._state.result.rules_applied,
        )
        self._state = ReasonerState(result, self.store.version, False, result.stop_reason)
        return stats

    def conclusions(self) -> tuple:
        if self._state is None:
            raise RuntimeError("call recompute() before reading conclusions")
        return self._state.result.conclusions
