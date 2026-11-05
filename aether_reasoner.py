"""Safe orchestration of explicit facts, inference and localized invalidation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from aether_dependencies import DependencyTracker, InvalidationStats
from aether_inference import InferenceEngine, InferenceLimits, InferenceResult, Rule
from aether_incremental import IncrementalInference
from aether_knowledge import Entity, Fact, KnowledgeStore, Provenance, Scalar


_EXTERNAL_MUTATION = "external_store_mutation_requires_recompute"


@dataclass(frozen=True)
class ReasonerState:
    result: InferenceResult
    store_version: int
    complete_for_current_store: bool
    stale_reason: str | None = None


class KnowledgeReasoner:
    """Keep inference state safe across mutations without hiding fallbacks.

    Mutations performed through this object are tracked. Direct mutations of the
    exposed store are detected on the next state/conclusion access and require a
    recomputation before conclusions can be read.
    """

    def __init__(self, store: KnowledgeStore, rules: tuple[Rule, ...] | list[Rule] = ()) -> None:
        self.store = store
        self.engine = InferenceEngine(store, rules)
        self._incremental = IncrementalInference(store, rules)
        self._state: ReasonerState | None = None
        self._tracker: DependencyTracker | None = None

    def _synchronize_external_mutation(self) -> ReasonerState | None:
        state = self._state
        if state is not None and state.store_version != self.store.version:
            self._state = ReasonerState(
                state.result,
                state.store_version,
                False,
                _EXTERNAL_MUTATION,
            )
        return self._state

    def _record_entity_change(self) -> None:
        """Advance the version for entity metadata changes, which do not affect rules."""
        if self._state is not None:
            self._state = ReasonerState(
                self._state.result,
                self.store.version,
                self._state.complete_for_current_store,
                self._state.stale_reason,
            )

    @property
    def state(self) -> ReasonerState | None:
        return self._synchronize_external_mutation()

    def add_entity(self, entity_id: str, properties: Mapping[str, Scalar] | None = None) -> Entity:
        entity = self.store.add_entity(entity_id, properties)
        self._record_entity_change()
        return entity

    def update_entity(self, entity_id: str, properties: Mapping[str, Scalar]) -> Entity:
        entity = self.store.update_entity(entity_id, properties)
        self._record_entity_change()
        return entity

    def recompute(self, limits: InferenceLimits | None = None) -> ReasonerState:
        result = self._incremental.initialize(limits)
        self._tracker = DependencyTracker(result)
        self._state = ReasonerState(
            result,
            self.store.version,
            result.complete,
            None if result.complete else result.stop_reason,
        )
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
        self._synchronize_external_mutation()
        if self._state is not None and self._state.complete_for_current_store:
            fact, update = self._incremental.add_fact(
                subject, predicate, object, provenance=provenance, confidence=confidence
            )
            if not update.inserted:
                return fact, False
            result = self._incremental.result()
            if update.complete:
                self._tracker = DependencyTracker(result)
                self._state = ReasonerState(result, self.store.version, True, None)
            else:
                self._state = ReasonerState(
                    result,
                    self.store.version,
                    False,
                    update.stop_reason or "incremental_update_incomplete",
                )
            return fact, True

        fact, inserted = self.store.add_fact(
            subject, predicate, object, provenance=provenance, confidence=confidence
        )
        if inserted and self._state is not None:
            stale_reason = (
                self._state.stale_reason
                if self._state.stale_reason == _EXTERNAL_MUTATION
                else "new_fact_requires_recompute"
            )
            self._state = ReasonerState(self._state.result, self.store.version, False, stale_reason)
        return fact, inserted

    def remove_fact(self, fact_id: int) -> InvalidationStats | None:
        self._synchronize_external_mutation()
        if (
            self._state is None
            or self._tracker is None
            or not self._state.complete_for_current_store
        ):
            self.store.remove_fact(fact_id)
            if self._state is not None:
                stale_reason = self._state.stale_reason or "fact_removal_requires_recompute"
                self._state = ReasonerState(self._state.result, self.store.version, False, stale_reason)
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
        state = self._synchronize_external_mutation()
        if state is None:
            raise RuntimeError("call recompute() before reading conclusions")
        if state.stale_reason == _EXTERNAL_MUTATION:
            raise RuntimeError("the KnowledgeStore changed outside this reasoner; call recompute() before reading conclusions")
        return state.result.conclusions
