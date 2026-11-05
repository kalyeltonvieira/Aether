"""Explicit evidence assessments and consistency checks for AETHER."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Iterator

from aether.reasoning.inference import InferenceResult, Rule
from aether.core.knowledge.store import Fact, KnowledgeStore, Provenance, Scalar, fact_key_identity, scalar_equal


class KnowledgeStatus(str, Enum):
    EXPLICIT = "explicit"
    DERIVED = "derived"
    UNKNOWN = "unknown"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class IncompatibilityRule:
    """A declared conflict between predicates for facts about the same subject.

    If ``object_pairs`` is None, any pair of values on the two declared
    predicates conflicts. Otherwise only the listed ordered value pairs do.
    The rule is symmetric with respect to predicate order.
    """

    predicate_a: str
    predicate_b: str
    object_pairs: tuple[tuple[Scalar, Scalar], ...] | None = None

    def __post_init__(self) -> None:
        if not self.predicate_a or not self.predicate_b or self.predicate_a == self.predicate_b:
            raise ValueError("incompatibility predicates must be distinct non-empty names")
        if self.object_pairs is not None:
            object.__setattr__(self, "object_pairs", tuple(tuple(pair) for pair in self.object_pairs))
            if any(len(pair) != 2 for pair in self.object_pairs):
                raise ValueError("each object pair must contain exactly two values")

    def conflicts(self, predicate: str, value: Scalar, other_predicate: str, other_value: Scalar) -> bool:
        if predicate == self.predicate_a and other_predicate == self.predicate_b:
            oriented = (value, other_value)
        elif predicate == self.predicate_b and other_predicate == self.predicate_a:
            oriented = (other_value, value)
        else:
            return False
        if self.object_pairs is None:
            return True
        return any(scalar_equal(oriented[0], left) and scalar_equal(oriented[1], right) for left, right in self.object_pairs)


@dataclass(frozen=True)
class ConsistencyIssue:
    code: str
    message: str
    facts: tuple[int, ...] = ()
    rules: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConflictResolution:
    fact_ids: tuple[int, ...]
    selected_fact_ids: tuple[int, ...]
    reason: str
    resolved_by: str


@dataclass(frozen=True)
class ConsistencyReport:
    issues: tuple[ConsistencyIssue, ...]
    resolutions: tuple[ConflictResolution, ...] = ()

    @property
    def consistent(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class KnowledgeAssessment:
    claim: tuple[str, str, Scalar]
    status: KnowledgeStatus
    explicit_fact_ids: tuple[int, ...] = ()
    derived_proofs: tuple = ()
    conflicting_fact_ids: tuple[int, ...] = ()
    evidence_sufficient: bool = False
    complete: bool | None = None
    resolution: ConflictResolution | None = None
    note: str = ""

    @property
    def is_explicit(self) -> bool:
        return bool(self.explicit_fact_ids)

    @property
    def is_derived(self) -> bool:
        return bool(self.derived_proofs)


class ConsistencyValidator:
    """Detect contradictions without selecting a winner or inventing evidence."""

    def __init__(self, store: KnowledgeStore) -> None:
        if not isinstance(store, KnowledgeStore):
            raise TypeError("store must be a KnowledgeStore")
        self.store = store
        self._resolutions: list[ConflictResolution] = []

    @property
    def resolutions(self) -> tuple[ConflictResolution, ...]:
        return tuple(self._resolutions)

    def record_resolution(
        self,
        fact_ids: Iterable[int],
        selected_fact_ids: Iterable[int],
        *,
        reason: str,
        resolved_by: str,
    ) -> ConflictResolution:
        ids = tuple(sorted(set(fact_ids)))
        selected = tuple(sorted(set(selected_fact_ids)))
        if not ids or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in ids):
            raise ValueError("fact_ids must contain positive integers")
        if not selected or not set(selected) <= set(ids):
            raise ValueError("selected_fact_ids must be a non-empty subset of fact_ids")
        for fact_id in ids:
            self.store.get_fact(fact_id)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")
        if not isinstance(resolved_by, str) or not resolved_by.strip():
            raise ValueError("resolved_by must be a non-empty string")
        resolution = ConflictResolution(ids, selected, reason, resolved_by)
        self._resolutions.append(resolution)
        return resolution

    def _declared_conflicts(
        self,
        claim: tuple[str, str, Scalar],
        rules: Iterable[IncompatibilityRule],
    ) -> tuple[Fact, ...]:
        subject, predicate, value = claim
        conflicts = []
        for other in self.store.query(subject=subject):
            if any(rule.conflicts(predicate, value, other.predicate, other.object) for rule in rules):
                conflicts.append(other)
        return tuple(conflicts)

    def _evidence_for_derived(self, inference: InferenceResult, key, active=frozenset()) -> bool:
        identity = fact_key_identity(key)
        if identity in active:
            return False
        derived = inference.by_key(key)
        if derived is None:
            explicit = self.store.query(subject=key[0], predicate=key[1], object=key[2])
            return bool(explicit) and all(fact.provenances for fact in explicit)
        for proof in derived.proofs:
            supports_ok = True
            for support in proof.supports:
                if isinstance(support, int) and not isinstance(support, bool):
                    try:
                        fact = self.store.get_fact(support)
                    except KeyError:
                        supports_ok = False
                        break
                    if not fact.provenances:
                        supports_ok = False
                        break
                elif not self._evidence_for_derived(inference, support, active | {identity}):
                    supports_ok = False
                    break
            if supports_ok:
                return True
        return False

    def assess(
        self,
        claim: tuple[str, str, Scalar],
        *,
        inference: InferenceResult | None = None,
        incompatibilities: Iterable[IncompatibilityRule] = (),
    ) -> KnowledgeAssessment:
        if not isinstance(claim, tuple) or len(claim) != 3:
            raise TypeError("claim must be a (subject, predicate, object) tuple")
        subject, predicate, value = claim
        subject = self.store._entity_id(subject)
        predicate = self.store._predicate(predicate)
        value = self.store._scalar(value)
        rules = tuple(incompatibilities)
        if any(not isinstance(rule, IncompatibilityRule) for rule in rules):
            raise TypeError("incompatibilities must contain IncompatibilityRule values")
        explicit = self.store.query(subject=subject, predicate=predicate, object=value)
        conflicts = self._declared_conflicts((subject, predicate, value), rules)
        conflict_ids = tuple(sorted({fact.fact_id for fact in conflicts}))
        matching_ids = tuple(fact.fact_id for fact in explicit)
        all_fact_ids = tuple(sorted(set(matching_ids) | set(conflict_ids)))
        resolution = next(
            (item for item in reversed(self._resolutions) if item.fact_ids == all_fact_ids and all_fact_ids),
            None,
        )
        if conflicts:
            evidence_sufficient = bool(explicit or conflicts) and all(
                self.store.get_fact(fact_id).provenances for fact_id in all_fact_ids
            )
            return KnowledgeAssessment(
                (subject, predicate, value), KnowledgeStatus.CONTRADICTED,
                matching_ids, (), conflict_ids, evidence_sufficient,
                True if inference is None else inference.complete, resolution,
                "Conflicting records are preserved; no source or confidence is selected automatically.",
            )
        if explicit:
            sufficient = all(fact.provenances for fact in explicit)
            return KnowledgeAssessment(
                (subject, predicate, value),
                KnowledgeStatus.EXPLICIT if sufficient else KnowledgeStatus.INSUFFICIENT_EVIDENCE,
                matching_ids, (), (), sufficient, True,
                note="Explicit record; confidence is not treated as a calibrated probability."
                if sufficient else "Explicit record exists, but provenance is missing.",
            )
        derived = inference.by_key((subject, predicate, value)) if inference is not None else None
        if derived is not None:
            sufficient = self._evidence_for_derived(inference, derived.key)
            return KnowledgeAssessment(
                (subject, predicate, value),
                KnowledgeStatus.DERIVED if sufficient else KnowledgeStatus.INSUFFICIENT_EVIDENCE,
                (), derived.proofs, (), sufficient, inference.complete,
                note="Derived from the recorded proof graph."
                if sufficient else "A derivation exists, but at least one available proof lacks provenance.",
            )
        complete = inference.complete if inference is not None else None
        if inference is not None and not inference.complete:
            return KnowledgeAssessment(
                (subject, predicate, value), KnowledgeStatus.INSUFFICIENT_EVIDENCE,
                complete=False,
                note="The inference result is incomplete; absence is not a negative fact.",
            )
        return KnowledgeAssessment(
            (subject, predicate, value), KnowledgeStatus.UNKNOWN,
            complete=complete,
            note="No explicit or derived record was found; absence is not falsity.",
        )

    def validate(
        self,
        *,
        incompatible_predicates: Iterable[tuple[str, str]] = (),
        incompatibilities: Iterable[IncompatibilityRule] = (),
        acyclic_predicates: Iterable[str] = (),
        inference: InferenceResult | None = None,
        rules: Iterable[Rule] = (),
    ) -> ConsistencyReport:
        issues: list[ConsistencyIssue] = []
        facts = list(self.store.query())
        for fact in facts:
            if not fact.provenances:
                issues.append(ConsistencyIssue("missing_provenance", f"fact {fact.fact_id} has no provenance", (fact.fact_id,)))

        legacy_pairs = tuple(incompatible_predicates)
        for left, right in legacy_pairs:
            if not isinstance(left, str) or not isinstance(right, str) or not left or not right:
                raise ValueError("incompatible predicate names must be non-empty strings")
            for fact in facts:
                if fact.predicate != left:
                    continue
                conflicts = [
                    other.fact_id for other in facts
                    if other.subject == fact.subject and other.predicate == right
                    and scalar_equal(other.object, fact.object)
                ]
                if conflicts:
                    issues.append(ConsistencyIssue(
                        "incompatible_facts",
                        f"{left} conflicts with {right} for {fact.subject}/{fact.object!r}",
                        (fact.fact_id, *conflicts),
                    ))

        declared = tuple(incompatibilities)
        if any(not isinstance(rule, IncompatibilityRule) for rule in declared):
            raise TypeError("incompatibilities must contain IncompatibilityRule values")
        for rule in declared:
            for first in facts:
                conflicts = [
                    second.fact_id for second in facts
                    if second.fact_id != first.fact_id and second.subject == first.subject
                    and rule.conflicts(first.predicate, first.object, second.predicate, second.object)
                ]
                for other_id in conflicts:
                    if first.fact_id < other_id:
                        issues.append(ConsistencyIssue(
                            "incompatible_facts",
                            f"declared incompatibility {rule.predicate_a}/{rule.predicate_b} for {first.subject}",
                            (first.fact_id, other_id),
                        ))

        for predicate in acyclic_predicates:
            edges = [(fact.subject, fact.object, fact.fact_id) for fact in facts if fact.predicate == predicate and isinstance(fact.object, str)]
            adjacency: dict[str, list[tuple[str, int]]] = {}
            for source, target, fact_id in edges:
                adjacency.setdefault(source, []).append((target, fact_id))
            visited: set[str] = set()
            active_index: dict[str, int] = {}
            for start in adjacency:
                if start in visited:
                    continue
                stack: list[tuple[str, Iterator[tuple[str, int]], int | None]] = [(start, iter(adjacency.get(start, ())), None)]
                active_index[start] = 0
                while stack:
                    node, neighbors, _incoming_fact = stack[-1]
                    try:
                        target, fact_id = next(neighbors)
                    except StopIteration:
                        visited.add(node)
                        active_index.pop(node, None)
                        stack.pop()
                        continue
                    if target in active_index:
                        cycle_start = active_index[target]
                        cycle_facts = tuple(frame[2] for frame in stack[cycle_start + 1:] if frame[2] is not None) + (fact_id,)
                        issues.append(ConsistencyIssue("forbidden_cycle", f"cycle detected for predicate {predicate}", cycle_facts))
                    elif target not in visited:
                        active_index[target] = len(stack)
                        stack.append((target, iter(adjacency.get(target, ())), fact_id))

        declared_pairs = set(legacy_pairs)
        declared_pairs.update((rule.predicate_a, rule.predicate_b) for rule in declared)
        declared_pairs.update((rule.predicate_b, rule.predicate_a) for rule in declared)
        rule_list = list(rules)
        for index, first in enumerate(rule_list):
            for second in rule_list[index + 1:]:
                if first.antecedents != second.antecedents:
                    continue
                if (
                    first.consequent.subject == second.consequent.subject
                    and first.consequent.predicate != second.consequent.predicate
                    and (first.consequent.predicate, second.consequent.predicate) in declared_pairs
                    and (first.consequent.object == second.consequent.object)
                ):
                    issues.append(ConsistencyIssue(
                        "contradictory_rules",
                        f"rules {first.rule_id} and {second.rule_id} have declared incompatible consequents",
                        rules=(first.rule_id, second.rule_id),
                    ))

        if inference is not None:
            existing_ids = {fact.fact_id for fact in self.store.query()}
            derived_by_identity = {fact.identity: fact for fact in inference.conclusions}
            for conclusion in inference.conclusions:
                for proof in conclusion.proofs:
                    for support in proof.supports:
                        if isinstance(support, int) and not isinstance(support, bool):
                            if support not in existing_ids:
                                issues.append(ConsistencyIssue("invalid_dependency", f"conclusion {conclusion.key} references missing fact {support}"))
                        elif isinstance(support, tuple) and len(support) == 3:
                            if fact_key_identity(support) not in derived_by_identity:
                                issues.append(ConsistencyIssue("invalid_dependency", f"conclusion {conclusion.key} references missing derived fact {support}"))
        return ConsistencyReport(tuple(issues), tuple(self._resolutions))
