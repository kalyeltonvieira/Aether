"""Delta-driven incremental forward inference for phase 7."""
from __future__ import annotations

from dataclasses import dataclass

from aether.reasoning.inference import DerivedFact, InferenceEngine, InferenceLimits, InferenceResult, Rule
from aether.core.knowledge.store import Fact, KnowledgeStore, Provenance, Scalar


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

    The agenda never reruns existing conclusions. Join scans are still counted;
    therefore this is incremental derivation, not a claim of O(1) maintenance.
    """

    def __init__(self, store: KnowledgeStore, rules: tuple[Rule, ...] | list[Rule] = ()) -> None:
        self.store = store
        self.engine = InferenceEngine(store, rules)
        self.rules = tuple(rules)
        self.limits = InferenceLimits()
        self._derived: dict[tuple[str, str, Scalar], DerivedFact] = {}
        self._initialized = False
        self._operations = 0
        self._facts_examined = 0
        self._stop_reason: str | None = None

    def initialize(self, limits: InferenceLimits | None = None) -> InferenceResult:
        self.limits = limits or InferenceLimits()
        result = self.engine.infer(self.limits)
        self._derived = {fact.key: fact for fact in result.conclusions}
        self._initialized = True
        self._operations = result.operations
        self._facts_examined = result.facts_examined
        self._stop_reason = result.stop_reason
        return result

    def _explicit_keys(self) -> set[tuple[str, str, Scalar]]:
        return {(fact.subject, fact.predicate, fact.object) for fact in self.store.query()}

    def add_fact(
        self,
        subject: str,
        predicate: str,
        object: Scalar,
        *,
        provenance: Provenance | None = None,
        confidence: float | None = None,
    ) -> tuple[Fact, IncrementalUpdate]:
        explicit_fact, inserted = self.store.add_fact(subject, predicate, object, provenance=provenance, confidence=confidence)
        if not inserted:
            return explicit_fact, IncrementalUpdate(False, (), 0, 0, self._stop_reason is None, self._stop_reason)
        if not self._initialized:
            result = self.initialize(self.limits)
            return explicit_fact, IncrementalUpdate(True, result.conclusions, result.operations, result.facts_examined, result.complete, result.stop_reason)

        frontier: set[int | tuple[str, str, Scalar]] = {explicit_fact.fact_id}
        produced_all: list[DerivedFact] = []
        operations = 0
        examined = 0
        stop_reason = None
        for depth in range(1, self.limits.max_depth + 1):
            produced: list[DerivedFact] = []
            for rule in self.rules:
                partials, count = self.engine._join_rule(rule, self._derived)
                examined += count
                operations += max(1, count)
                if operations > self.limits.max_operations:
                    stop_reason = "max_operations"
                    break
                for bindings, supports in partials:
                    if not any(token in frontier for token in supports):
                        continue
                    key = self.engine._instantiate(rule.consequent, bindings)
                    if key in self._derived or key in self._explicit_keys():
                        continue
                    candidate = DerivedFact(key[0], key[1], key[2], rule.rule_id, depth, supports)
                    produced.append(candidate)
                    if len(self._derived) + len(produced) >= self.limits.max_conclusions:
                        stop_reason = "max_conclusions"
                        break
                if stop_reason:
                    break
            if stop_reason:
                break
            if not produced:
                break
            frontier = {fact.key for fact in produced}
            for derived_fact in produced:
                self._derived[derived_fact.key] = derived_fact
                produced_all.append(derived_fact)
        if stop_reason is None and produced_all and len(produced_all) >= self.limits.max_conclusions:
            stop_reason = "max_conclusions"
        self._operations += operations
        self._facts_examined += examined
        self._stop_reason = stop_reason
        return explicit_fact, IncrementalUpdate(True, tuple(produced_all), operations, examined, stop_reason is None, stop_reason)

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
            len(self.rules),
        )
