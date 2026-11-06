"""Delta-driven incremental forward inference with proof-aware deduplication."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from aether.reasoning.inference import (
    DerivationProof,
    DerivedFact,
    InferenceEngine,
    InferenceLimits,
    InferenceResult,
    Rule,
    _support_identity,
)
from aether.core.knowledge.store import Fact, FactIdentity, KnowledgeStore, Provenance, Scalar, fact_key_identity


@dataclass(frozen=True)
class IncrementalUpdate:
    inserted: bool
    new_conclusions: tuple[DerivedFact, ...]
    operations: int
    facts_examined: int
    complete: bool
    stop_reason: str | None


class IncrementalInference:
    """Maintain a derived set and propagate only new support tokens.

    Alternative derivations are retained on an existing conclusion. Join scans
    are counted; the agenda is incremental but does not claim O(1) maintenance.
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
        self.rules = self.engine.rules
        self.limits = InferenceLimits()
        self._derived: dict[FactIdentity, DerivedFact] = {}
        self._initialized = False
        self._operations = 0
        self._facts_examined = 0
        self._stop_reason: str | None = None

    def initialize(self, limits: InferenceLimits | None = None) -> InferenceResult:
        self.limits = limits or InferenceLimits()
        result = self.engine.infer(self.limits)
        self._derived = {fact.identity: fact for fact in result.conclusions}
        self._initialized = True
        self._operations = result.operations
        self._facts_examined = result.facts_examined
        self._stop_reason = result.stop_reason
        return result

    def _explicit_keys(self) -> set[FactIdentity]:
        return {fact_key_identity(fact.key) for fact in self.store.query()}

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
    ) -> tuple[Fact, IncrementalUpdate]:
        explicit_fact, inserted = self.store.add_fact(
            subject, predicate, object, provenance=provenance, confidence=confidence,
            properties=properties, context=context,
        )
        if not inserted:
            return explicit_fact, IncrementalUpdate(False, (), 0, 0, self._stop_reason is None, self._stop_reason)
        if not self._initialized:
            result = self.initialize(self.limits)
            return explicit_fact, IncrementalUpdate(
                True, result.conclusions, result.operations, result.facts_examined,
                result.complete, result.stop_reason,
            )

        frontier = {_support_identity(explicit_fact.fact_id)}
        produced_all: list[DerivedFact] = []
        operations = examined = 0
        stop_reason = None
        explicit_keys = self._explicit_keys()
        for depth in range(1, self.limits.max_depth + 1):
            produced: dict[FactIdentity, tuple[tuple[str, str, Scalar], list[DerivationProof]]] = {}
            for rule in self.rules:
                if not rule.enabled:
                    continue
                partials, count = self.engine._join_rule(rule, self._derived)
                examined += count
                operations += max(1, count)
                if self._operations + operations > self.limits.max_operations:
                    stop_reason = "max_operations"
                    break
                for bindings, supports in partials:
                    if not any(_support_identity(token) in frontier for token in supports):
                        continue
                    key = self.engine._instantiate(rule.consequent, bindings)
                    identity = fact_key_identity(key)
                    if identity in explicit_keys:
                        continue
                    proof = DerivationProof(rule.rule_id, rule.revision, depth, supports)
                    existing = self._derived.get(identity)
                    if existing is not None:
                        proofs = list(existing.proofs)
                        if proof.identity not in {item.identity for item in proofs}:
                            proofs.append(proof)
                            self._derived[identity] = existing.with_proofs(proofs)
                        continue
                    if identity in produced:
                        produced[identity][1].append(proof)
                        continue
                    if len(self._derived) + len(produced) >= self.limits.max_conclusions:
                        stop_reason = "max_conclusions"
                        break
                    produced[identity] = (key, [proof])
                if stop_reason:
                    break
            if stop_reason or not produced:
                break
            frontier = set()
            for identity, (key, proofs) in produced.items():
                unique_proofs = []
                seen = set()
                for proof in proofs:
                    if proof.identity not in seen:
                        unique_proofs.append(proof)
                        seen.add(proof.identity)
                primary = unique_proofs[0]
                derived_fact = DerivedFact(
                    key[0], key[1], key[2], primary.rule_id, primary.depth,
                    primary.supports, tuple(unique_proofs),
                )
                self._derived[identity] = derived_fact
                produced_all.append(derived_fact)
                frontier.add(_support_identity(derived_fact.key))

        self._operations += operations
        self._facts_examined += examined
        self._stop_reason = stop_reason
        return explicit_fact, IncrementalUpdate(
            True, tuple(produced_all), operations, examined,
            stop_reason is None, stop_reason,
        )

    def result(self) -> InferenceResult:
        if not self._initialized:
            raise RuntimeError("call initialize() before result()")
        return InferenceResult(
            tuple(self._derived.values()),
            self._operations,
            max((fact.depth for fact in self._derived.values()), default=0),
            self._stop_reason is None,
            self._stop_reason,
            self._facts_examined,
            sum(rule.enabled for rule in self.rules),
        )
