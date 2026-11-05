"""Safe orchestration of explicit facts, inference and localized invalidation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from aether.reasoning.dependencies import DependencyTracker, InvalidationStats
from aether.reasoning.inference import InferenceEngine, InferenceLimits, InferenceResult, Rule
from aether.reasoning.incremental import IncrementalInference
from aether.core.knowledge.store import Entity, Fact, KnowledgeStore, Provenance, Scalar

_EXTERNAL_MUTATION = "external_store_mutation_requires_recompute"
_RULE_MUTATION = "rule_set_changed_requires_recompute"


@dataclass(frozen=True)
class ReasonerState:
    result: InferenceResult
    store_version: int
    complete_for_current_store: bool
    stale_reason: str | None = None
    rules_version: int = 0
    rules_fingerprint: tuple = ()


class KnowledgeReasoner:
    """Keep inference state safe across store and rule-set mutations.

    Mutations through the reasoner are tracked. Direct store mutations and all
    rule lifecycle changes invalidate a previously complete result; conclusions
    from an obsolete snapshot cannot be read as current until ``recompute``.
    Fact removal uses proof-level dependency invalidation first, retains surviving
    alternative proofs, then conservatively marks completeness unknown pending a
    fresh full inference.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        rules: tuple[Rule, ...] | list[Rule] = (),
        *,
        join_planner: str = "input",
    ) -> None:
        self.store = store
        self.engine = InferenceEngine(store, rules, join_planner=join_planner)
        self.join_planner = self.engine.join_planner
        self._incremental = IncrementalInference(
            store, self.engine.rules, join_planner=self.join_planner
        )
        self._state: ReasonerState | None = None
        self._tracker: DependencyTracker | None = None

    def _synchronize_versions(self) -> ReasonerState | None:
        state = self._state
        if state is None:
            return None
        external_store_change = state.store_version != self.store.version
        external_rule_change = state.rules_version != self.engine.rules_version
        if external_store_change or external_rule_change:
            reason = _EXTERNAL_MUTATION if external_store_change else _RULE_MUTATION
            self._state = ReasonerState(
                state.result,
                state.store_version,
                False,
                reason,
                self.engine.rules_version,
                self.engine.rules_fingerprint,
            )
        return self._state

    def _record_entity_change(self) -> None:
        if self._state is not None:
            state = self._state
            self._state = ReasonerState(
                state.result,
                self.store.version,
                state.complete_for_current_store,
                state.stale_reason,
                self.engine.rules_version,
                self.engine.rules_fingerprint,
            )

    @property
    def state(self) -> ReasonerState | None:
        return self._synchronize_versions()

    @property
    def rules_version(self) -> int:
        return self.engine.rules_version

    def add_entity(self, entity_id: str, properties: Mapping[str, Scalar] | None = None) -> Entity:
        self._synchronize_versions()
        entity = self.store.add_entity(entity_id, properties)
        self._record_entity_change()
        return entity

    def update_entity(self, entity_id: str, properties: Mapping[str, Scalar]) -> Entity:
        self._synchronize_versions()
        entity = self.store.update_entity(entity_id, properties)
        self._record_entity_change()
        return entity

    def add_rule(self, rule: Rule) -> None:
        self.engine.add_rule(rule)
        self._synchronize_versions()

    def remove_rule(self, rule_id: str) -> Rule:
        removed = self.engine.remove_rule(rule_id)
        self._synchronize_versions()
        return removed

    def replace_rule(self, rule_id: str, rule: Rule) -> Rule:
        revised = self.engine.replace_rule(rule_id, rule)
        self._synchronize_versions()
        return revised

    def set_rule_enabled(self, rule_id: str, enabled: bool) -> Rule:
        revised = self.engine.set_rule_enabled(rule_id, enabled)
        self._synchronize_versions()
        return revised

    def recompute(self, limits: InferenceLimits | None = None) -> ReasonerState:
        self._incremental = IncrementalInference(
            self.store, self.engine.rules, join_planner=self.join_planner
        )
        result = self._incremental.initialize(limits)
        self._tracker = DependencyTracker(result)
        self._state = ReasonerState(
            result,
            self.store.version,
            result.complete,
            None if result.complete else result.stop_reason,
            self.engine.rules_version,
            self.engine.rules_fingerprint,
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
        properties: Mapping[str, Scalar] | None = None,
        context: Mapping[str, str] | None = None,
    ) -> tuple[Fact, bool]:
        self._synchronize_versions()
        if self._state is not None and self._state.complete_for_current_store:
            fact, update = self._incremental.add_fact(
                subject, predicate, object, provenance=provenance, confidence=confidence,
                properties=properties, context=context,
            )
            if not update.inserted:
                return fact, False
            result = self._incremental.result()
            if update.complete:
                self._tracker = DependencyTracker(result)
                self._state = ReasonerState(
                    result, self.store.version, True, None,
                    self.engine.rules_version, self.engine.rules_fingerprint,
                )
            else:
                self._state = ReasonerState(
                    result, self.store.version, False,
                    update.stop_reason or "incremental_update_incomplete",
                    self.engine.rules_version, self.engine.rules_fingerprint,
                )
            return fact, True

        fact, inserted = self.store.add_fact(
            subject, predicate, object, provenance=provenance, confidence=confidence,
            properties=properties, context=context,
        )
        if inserted and self._state is not None:
            stale_reason = self._state.stale_reason or "new_fact_requires_recompute"
            self._state = ReasonerState(
                self._state.result, self.store.version, False, stale_reason,
                self.engine.rules_version, self.engine.rules_fingerprint,
            )
        return fact, inserted

    def remove_fact(self, fact_id: int) -> InvalidationStats | None:
        self._synchronize_versions()
        if (
            self._state is None
            or self._tracker is None
            or not self._state.complete_for_current_store
        ):
            self.store.remove_fact(fact_id)
            if self._state is not None:
                stale_reason = self._state.stale_reason or "fact_removal_requires_recompute"
                self._state = ReasonerState(
                    self._state.result, self.store.version, False, stale_reason,
                    self.engine.rules_version, self.engine.rules_fingerprint,
                )
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
        self._state = ReasonerState(
            result, self.store.version, False, result.stop_reason,
            self.engine.rules_version, self.engine.rules_fingerprint,
        )
        return stats

    def conclusions(self) -> tuple:
        state = self._synchronize_versions()
        if state is None:
            raise RuntimeError("call recompute() before reading conclusions")
        if state.stale_reason in {_EXTERNAL_MUTATION, _RULE_MUTATION}:
            raise RuntimeError("the store or rule set changed; call recompute() before reading conclusions")
        return state.result.conclusions
