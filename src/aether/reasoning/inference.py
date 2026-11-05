"""Bounded, deterministic relational inference and query enumeration."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from aether.core.knowledge.store import (
    Fact,
    FactIdentity,
    KnowledgeStore,
    Provenance,
    Scalar,
    fact_key_identity,
    scalar_equal,
    scalar_identity,
)


def _support_identity(support: int | tuple[str, str, Scalar]) -> tuple:
    if isinstance(support, int) and not isinstance(support, bool):
        return ("explicit", support)
    if isinstance(support, tuple) and len(support) == 3:
        return ("derived", fact_key_identity(support))
    raise TypeError("support must be an explicit fact ID or a derived fact key")


@dataclass(frozen=True)
class Pattern:
    subject: str
    predicate: str
    object: Scalar

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject:
            raise ValueError("pattern subject must be a non-empty string")
        if not isinstance(self.predicate, str) or not self.predicate:
            raise ValueError("pattern predicate must be a non-empty string")
        if not isinstance(self.object, (str, int, float, bool)) and self.object is not None:
            raise TypeError("pattern object must be scalar")

    def variables(self) -> set[str]:
        values = [self.subject, self.object]
        return {value for value in values if isinstance(value, str) and value.startswith("?")}

    @property
    def is_ground(self) -> bool:
        return not self.variables()


@dataclass(frozen=True)
class Rule:
    rule_id: str
    antecedents: tuple[Pattern, ...]
    consequent: Pattern
    revision: int = 1
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not self.rule_id.strip():
            raise ValueError("rule_id must be a non-empty string")
        try:
            antecedents = tuple(self.antecedents)
        except TypeError as exc:
            raise TypeError("antecedents must be an iterable of Pattern values") from exc
        if not antecedents:
            raise ValueError("a rule needs at least one antecedent")
        if any(not isinstance(pattern, Pattern) for pattern in antecedents):
            raise TypeError("all antecedents must be Pattern values")
        if not isinstance(self.consequent, Pattern):
            raise TypeError("consequent must be a Pattern")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("revision must be a positive integer")
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be bool")
        object.__setattr__(self, "antecedents", antecedents)
        variables = set().union(*(pattern.variables() for pattern in antecedents))
        if not self.consequent.variables() <= variables:
            raise ValueError("consequent variables must occur in antecedents")


@dataclass(frozen=True)
class InferenceLimits:
    max_depth: int = 8
    max_operations: int = 10000
    max_conclusions: int = 1000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_depth", self.max_depth),
            ("max_operations", self.max_operations),
            ("max_conclusions", self.max_conclusions),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class DerivationProof:
    """One derivation of a conclusion, distinct from the conclusion itself."""

    rule_id: str
    rule_revision: int
    depth: int
    supports: tuple[int | tuple[str, str, Scalar], ...]

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("proof rule_id must be non-empty")
        if self.rule_revision < 1 or self.depth < 1:
            raise ValueError("proof revision and depth must be positive")
        tuple(_support_identity(support) for support in self.supports)

    @property
    def identity(self) -> tuple:
        return (
            self.rule_id,
            self.rule_revision,
            tuple(_support_identity(support) for support in self.supports),
        )


@dataclass(frozen=True)
class DerivedFact:
    """Canonical conclusion with legacy primary-proof fields and all proofs."""

    subject: str
    predicate: str
    object: Scalar
    rule_id: str
    depth: int
    supports: tuple[int | tuple[str, str, Scalar], ...]
    proofs: tuple[DerivationProof, ...] = ()

    def __post_init__(self) -> None:
        if not self.proofs:
            object.__setattr__(
                self,
                "proofs",
                (DerivationProof(self.rule_id, 1, self.depth, self.supports),),
            )
        else:
            if any(not isinstance(proof, DerivationProof) for proof in self.proofs):
                raise TypeError("proofs must contain DerivationProof values")
            unique = []
            seen = set()
            for proof in self.proofs:
                if proof.identity not in seen:
                    unique.append(proof)
                    seen.add(proof.identity)
            object.__setattr__(self, "proofs", tuple(unique))
            primary = self.proofs[0]
            object.__setattr__(self, "rule_id", primary.rule_id)
            object.__setattr__(self, "depth", primary.depth)
            object.__setattr__(self, "supports", primary.supports)

    @property
    def key(self) -> tuple[str, str, Scalar]:
        return self.subject, self.predicate, self.object

    @property
    def identity(self) -> FactIdentity:
        return fact_key_identity(self.key)

    def with_proofs(self, proofs: tuple[DerivationProof, ...] | list[DerivationProof]) -> "DerivedFact":
        if not proofs:
            raise ValueError("a derived conclusion must retain at least one proof")
        primary = proofs[0]
        return replace(
            self,
            rule_id=primary.rule_id,
            depth=primary.depth,
            supports=primary.supports,
            proofs=tuple(proofs),
        )


@dataclass(frozen=True)
class InferenceResult:
    conclusions: tuple[DerivedFact, ...]
    operations: int
    max_depth_reached: int
    complete: bool
    stop_reason: str | None
    facts_examined: int
    rules_applied: int

    def by_key(self, key: tuple[str, str, Scalar]) -> DerivedFact | None:
        identity = fact_key_identity(key)
        return next((fact for fact in self.conclusions if fact.identity == identity), None)


@dataclass(frozen=True)
class ExplanationProof:
    proof: DerivationProof
    supports: tuple["ExplanationNode", ...]


@dataclass(frozen=True)
class ExplanationNode:
    key: tuple[str, str, Scalar]
    explicit_fact_id: int | None = None
    provenance: Provenance | None = None
    proofs: tuple[ExplanationProof, ...] = ()
    cycle_truncated: bool = False
    provenances: tuple[Provenance, ...] = ()


@dataclass(frozen=True)
class QuerySolution:
    bindings: tuple[tuple[str, Scalar], ...]
    fact_key: tuple[str, str, Scalar]
    explicit_fact_id: int | None
    proofs: tuple[DerivationProof, ...]
    explanation: ExplanationNode

    def binding_map(self) -> dict[str, Scalar]:
        return dict(self.bindings)


@dataclass(frozen=True)
class QueryResult:
    solutions: tuple[QuerySolution, ...]
    complete: bool
    operations: int
    facts_examined: int
    conclusions_produced: int
    stop_reason: str | None
    inference: InferenceResult
    offset: int = 0
    next_offset: int | None = None


@dataclass(frozen=True)
class JoinPlan:
    rule_id: str
    mode: str
    order: tuple[int, ...]
    candidate_estimates: tuple[int, ...]


class InferenceEngine:
    """Forward chaining with alternative proof records and bounded open queries."""

    def __init__(
        self,
        store: KnowledgeStore,
        rules: tuple[Rule, ...] | list[Rule] = (),
        *,
        join_planner: str = "input",
    ) -> None:
        if not isinstance(store, KnowledgeStore):
            raise TypeError("store must be a KnowledgeStore")
        if join_planner not in {"input", "selective"}:
            raise ValueError("join_planner must be 'input' or 'selective'")
        self.store = store
        self.join_planner = join_planner
        self.last_join_plan: JoinPlan | None = None
        self._rules: list[Rule] = []
        self._rule_ids: set[str] = set()
        self.rules_version = 0
        for rule in rules:
            self.add_rule(rule)

    @property
    def rules(self) -> tuple[Rule, ...]:
        return tuple(self._rules)

    @property
    def rules_fingerprint(self) -> tuple[tuple, ...]:
        return tuple(
            (
                rule.rule_id,
                rule.revision,
                rule.enabled,
                tuple((p.subject, p.predicate, scalar_identity(p.object)) for p in rule.antecedents),
                (rule.consequent.subject, rule.consequent.predicate, scalar_identity(rule.consequent.object)),
            )
            for rule in self._rules
        )

    def add_rule(self, rule: Rule) -> None:
        if not isinstance(rule, Rule):
            raise TypeError("rule must be a Rule")
        if rule.rule_id in self._rule_ids:
            raise ValueError(f"duplicate rule id: {rule.rule_id}")
        self._rules.append(rule)
        self._rule_ids.add(rule.rule_id)
        self.rules_version += 1

    def remove_rule(self, rule_id: str) -> Rule:
        if not isinstance(rule_id, str) or not rule_id:
            raise ValueError("rule_id must be a non-empty string")
        for index, rule in enumerate(self._rules):
            if rule.rule_id == rule_id:
                removed = self._rules.pop(index)
                self._rule_ids.remove(rule_id)
                self.rules_version += 1
                return removed
        raise KeyError(rule_id)

    def replace_rule(self, rule_id: str, rule: Rule) -> Rule:
        if not isinstance(rule, Rule):
            raise TypeError("rule must be a Rule")
        if rule.rule_id != rule_id:
            raise ValueError("replacement rule must keep the existing rule_id")
        for index, old in enumerate(self._rules):
            if old.rule_id == rule_id:
                revised = replace(rule, revision=old.revision + 1)
                self._rules[index] = revised
                self.rules_version += 1
                return revised
        raise KeyError(rule_id)

    def set_rule_enabled(self, rule_id: str, enabled: bool) -> Rule:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be bool")
        for old in self._rules:
            if old.rule_id == rule_id:
                if old.enabled == enabled:
                    return old
                return self.replace_rule(rule_id, replace(old, enabled=enabled))
        raise KeyError(rule_id)

    @staticmethod
    def _match(value: Scalar, expected: Scalar, bindings: Mapping[str, Scalar]):
        if isinstance(expected, str) and expected.startswith("?"):
            bound = bindings.get(expected, ...)
            if bound is ...:
                updated = dict(bindings)
                updated[expected] = value
                return updated
            return dict(bindings) if scalar_equal(bound, value) else None
        return dict(bindings) if scalar_equal(value, expected) else None

    @classmethod
    def _match_pattern(
        cls,
        fact_key: tuple[str, str, Scalar],
        pattern: Pattern,
        bindings: Mapping[str, Scalar],
    ):
        subject, predicate, object_value = fact_key
        if predicate != pattern.predicate:
            return None
        next_bindings = cls._match(subject, pattern.subject, bindings)
        if next_bindings is None:
            return None
        return cls._match(object_value, pattern.object, next_bindings)

    @staticmethod
    def _instantiate(pattern: Pattern, bindings: Mapping[str, Scalar]) -> tuple[str, str, Scalar]:
        def resolve(value: Scalar) -> Scalar:
            if isinstance(value, str) and value.startswith("?"):
                return bindings[value]
            return value
        return resolve(pattern.subject), pattern.predicate, resolve(pattern.object)

    def _known_by_predicate(
        self,
        derived: Mapping[FactIdentity, DerivedFact],
        *,
        count_predicates: set[str] | None = None,
    ):
        grouped: dict[str, list[tuple[tuple[str, str, Scalar], int | tuple[str, str, Scalar]]]] = {}
        by_subject: dict[tuple[str, str], int] = {}
        by_object: dict[tuple[str, object], int] = {}
        by_pair: dict[tuple[str, str, object], int] = {}
        for fact in self.store.query():
            key = fact.key
            grouped.setdefault(fact.predicate, []).append((key, fact.fact_id))
            if count_predicates is not None and fact.predicate in count_predicates:
                by_subject[(fact.predicate, fact.subject)] = by_subject.get((fact.predicate, fact.subject), 0) + 1
                object_id = scalar_identity(fact.object)
                by_object[(fact.predicate, object_id)] = by_object.get((fact.predicate, object_id), 0) + 1
                by_pair[(fact.predicate, fact.subject, object_id)] = by_pair.get(
                    (fact.predicate, fact.subject, object_id), 0
                ) + 1
        for fact in derived.values():
            key = fact.key
            grouped.setdefault(fact.predicate, []).append((key, key))
            if count_predicates is not None and fact.predicate in count_predicates:
                by_subject[(fact.predicate, fact.subject)] = by_subject.get((fact.predicate, fact.subject), 0) + 1
                object_id = scalar_identity(fact.object)
                by_object[(fact.predicate, object_id)] = by_object.get((fact.predicate, object_id), 0) + 1
                by_pair[(fact.predicate, fact.subject, object_id)] = by_pair.get(
                    (fact.predicate, fact.subject, object_id), 0
                ) + 1
        return grouped, by_subject, by_object, by_pair

    @staticmethod
    def _estimate_pattern(
        pattern: Pattern,
        by_predicate: Mapping[str, list],
        by_subject: Mapping[tuple[str, str], int],
        by_object: Mapping[tuple[str, object], int],
        by_pair: Mapping[tuple[str, str, object], int],
    ) -> int:
        subject_is_variable = isinstance(pattern.subject, str) and pattern.subject.startswith("?")
        object_is_variable = isinstance(pattern.object, str) and pattern.object.startswith("?")
        if not subject_is_variable and not object_is_variable:
            return by_pair.get(
                (pattern.predicate, pattern.subject, scalar_identity(pattern.object)), 0
            )
        if not subject_is_variable:
            return by_subject.get((pattern.predicate, pattern.subject), 0)
        if not object_is_variable:
            return by_object.get((pattern.predicate, scalar_identity(pattern.object)), 0)
        return len(by_predicate.get(pattern.predicate, ()))

    def _join_rule(self, rule: Rule, derived):
        selective = self.join_planner == "selective"
        count_predicates = None
        if selective:
            count_predicates = {
                pattern.predicate
                for pattern in rule.antecedents
                if not (isinstance(pattern.subject, str) and pattern.subject.startswith("?"))
                or not (isinstance(pattern.object, str) and pattern.object.startswith("?"))
            }
        grouped, by_subject, by_object, by_pair = self._known_by_predicate(
            derived, count_predicates=count_predicates
        )
        estimates = tuple(
            self._estimate_pattern(pattern, grouped, by_subject, by_object, by_pair)
            for pattern in rule.antecedents
        ) if selective else ()
        order = tuple(range(len(rule.antecedents)))
        if selective:
            order = tuple(sorted(order, key=lambda index: (estimates[index], index)))
        self.last_join_plan = JoinPlan(rule.rule_id, self.join_planner, order, estimates)

        if order == tuple(range(len(rule.antecedents))):
            partials: list[tuple[dict[str, Scalar], tuple[int | tuple[str, str, Scalar], ...]]] = [({}, ())]
            examined = 0
            for pattern in rule.antecedents:
                next_partials = []
                candidates = grouped.get(pattern.predicate, [])
                for bindings, supports in partials:
                    for fact_key, support in candidates:
                        examined += 1
                        next_bindings = self._match_pattern(fact_key, pattern, bindings)
                        if next_bindings is not None:
                            next_partials.append((next_bindings, supports + (support,)))
                partials = next_partials
                if not partials:
                    break
            return partials, examined

        partials: list[tuple[dict[str, Scalar], dict[int, int | tuple[str, str, Scalar]]]] = [({}, {})]
        examined = 0
        for pattern_index in order:
            pattern = rule.antecedents[pattern_index]
            next_partials = []
            candidates = grouped.get(pattern.predicate, [])
            for bindings, supports in partials:
                for fact_key, support in candidates:
                    examined += 1
                    next_bindings = self._match_pattern(fact_key, pattern, bindings)
                    if next_bindings is not None:
                        next_supports = dict(supports)
                        next_supports[pattern_index] = support
                        next_partials.append((next_bindings, next_supports))
            partials = next_partials
            if not partials:
                break
        ordered_partials = [
            (bindings, tuple(supports[index] for index in range(len(rule.antecedents))))
            for bindings, supports in partials
        ]
        ordered_partials.sort(key=lambda item: (
            tuple((name, scalar_identity(value)) for name, value in sorted(item[0].items())),
            tuple(_support_identity(support) for support in item[1]),
        ))
        return ordered_partials, examined

    @staticmethod
    def _dedupe_proofs(proofs: list[DerivationProof]) -> tuple[DerivationProof, ...]:
        unique = []
        seen = set()
        for proof in proofs:
            if proof.identity not in seen:
                unique.append(proof)
                seen.add(proof.identity)
        return tuple(unique)

    def infer(self, limits: InferenceLimits | None = None) -> InferenceResult:
        limits = limits or InferenceLimits()
        derived: dict[FactIdentity, DerivedFact] = {}
        explicit_ids = {fact_key_identity(fact.key) for fact in self.store.query()}
        operations = facts_examined = rules_applied = max_depth_reached = 0
        stop_reason = None
        for depth in range(1, limits.max_depth + 1):
            max_depth_reached = depth
            produced: dict[FactIdentity, tuple[tuple[str, str, Scalar], list[DerivationProof]]] = {}
            for rule in self._rules:
                if not rule.enabled:
                    continue
                partials, examined = self._join_rule(rule, derived)
                facts_examined += examined
                rules_applied += 1
                operations += max(1, examined)
                if operations > limits.max_operations:
                    stop_reason = "max_operations"
                    return InferenceResult(tuple(derived.values()), operations, max_depth_reached, False, stop_reason, facts_examined, rules_applied)
                for bindings, supports in partials:
                    key = self._instantiate(rule.consequent, bindings)
                    identity = fact_key_identity(key)
                    if identity in explicit_ids:
                        continue
                    proof = DerivationProof(rule.rule_id, rule.revision, depth, supports)
                    if identity in derived:
                        old = derived[identity]
                        proofs = self._dedupe_proofs([*old.proofs, proof])
                        if len(proofs) != len(old.proofs):
                            derived[identity] = old.with_proofs(proofs)
                        continue
                    if identity in produced:
                        produced[identity][1].append(proof)
                        continue
                    if len(derived) + len(produced) >= limits.max_conclusions:
                        stop_reason = "max_conclusions"
                        break
                    produced[identity] = (key, [proof])
                if stop_reason:
                    break
            if stop_reason:
                break
            if not produced:
                return InferenceResult(tuple(derived.values()), operations, max_depth_reached, True, None, facts_examined, rules_applied)
            for identity, (key, proofs) in produced.items():
                unique_proofs = self._dedupe_proofs(proofs)
                primary = unique_proofs[0]
                derived[identity] = DerivedFact(
                    key[0], key[1], key[2], primary.rule_id, primary.depth,
                    primary.supports, unique_proofs,
                )
        if stop_reason is None and max_depth_reached >= limits.max_depth:
            stop_reason = "max_depth"
        return InferenceResult(tuple(derived.values()), operations, max_depth_reached, stop_reason is None, stop_reason, facts_examined, rules_applied)

    def explain_all(self, result: InferenceResult, key: tuple[str, str, Scalar]) -> tuple[ExplanationNode, ...]:
        target = result.by_key(key)
        if target is None:
            direct = self.store.query(subject=key[0], predicate=key[1], object=key[2])
            return tuple(
                ExplanationNode(
                    fact.key,
                    explicit_fact_id=fact.fact_id,
                    provenance=fact.provenance,
                    provenances=fact.provenances,
                )
                for fact in direct
            )
        derived = {fact.identity: fact for fact in result.conclusions}
        explicit = {fact.fact_id: fact for fact in self.store.query()}

        def build(current_key: tuple[str, str, Scalar], active: frozenset[FactIdentity]) -> ExplanationNode:
            identity = fact_key_identity(current_key)
            if identity in active:
                return ExplanationNode(current_key, cycle_truncated=True)
            fact = derived.get(identity)
            if fact is None:
                direct = self.store.query(subject=current_key[0], predicate=current_key[1], object=current_key[2])
                if direct:
                    source = direct[0]
                    return ExplanationNode(
                        source.key,
                        explicit_fact_id=source.fact_id,
                        provenance=source.provenance,
                        provenances=source.provenances,
                    )
                return ExplanationNode(current_key)
            branches = []
            for proof in fact.proofs:
                support_nodes = []
                for support in proof.supports:
                    if isinstance(support, int) and not isinstance(support, bool):
                        source = explicit.get(support)
                        if source is None:
                            support_nodes.append(ExplanationNode(("?missing", "support", support)))
                        else:
                            support_nodes.append(ExplanationNode(
                                source.key,
                                explicit_fact_id=source.fact_id,
                                provenance=source.provenance,
                                provenances=source.provenances,
                            ))
                    else:
                        support_nodes.append(build(support, active | {identity}))
                branches.append(ExplanationProof(proof, tuple(support_nodes)))
            return ExplanationNode(current_key, proofs=tuple(branches))

        return (build(target.key, frozenset()),)

    @staticmethod
    def explain(result: InferenceResult, key: tuple[str, str, Scalar]) -> tuple[DerivedFact, ...]:
        target = result.by_key(key)
        if target is None:
            return ()
        explanation = [target]
        queue = list(target.proofs[0].supports)
        seen = {target.identity}
        derived_by_key = {fact.identity: fact for fact in result.conclusions}
        while queue:
            support = queue.pop(0)
            if not isinstance(support, tuple) or len(support) != 3 or not isinstance(support[0], str):
                continue
            fact = derived_by_key.get(fact_key_identity(support))
            if fact is not None and fact.identity not in seen:
                seen.add(fact.identity)
                explanation.append(fact)
                queue.extend(fact.proofs[0].supports)
        return tuple(explanation)

    def query(
        self,
        pattern: Pattern,
        limits: InferenceLimits | None = None,
        *,
        max_results: int = 1000,
        offset: int = 0,
    ) -> QueryResult:
        if not isinstance(pattern, Pattern):
            raise TypeError("pattern must be a Pattern")
        if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
            raise ValueError("max_results must be a positive integer")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        limits = limits or InferenceLimits()
        inference = self.infer(limits)
        explicit = self.store.query(predicate=pattern.predicate)
        candidates: list[tuple[tuple[str, str, Scalar], int | None, DerivedFact | None]] = [
            (fact.key, fact.fact_id, None) for fact in explicit
        ]
        candidates.extend(
            (fact.key, None, fact)
            for fact in inference.conclusions
            if fact.predicate == pattern.predicate
        )
        solutions = []
        seen_bindings: set[tuple[tuple[str, tuple[str, object]], ...]] = set()
        operations = inference.operations
        facts_examined = inference.facts_examined
        stop_reason = inference.stop_reason
        complete = inference.complete
        next_offset = None
        for key, fact_id, derived_fact in candidates:
            operations += 1
            facts_examined += 1
            if operations > limits.max_operations:
                complete = False
                stop_reason = "max_operations"
                break
            bindings = self._match_pattern(key, pattern, {})
            if bindings is None:
                continue
            binding_identity = tuple(
                (name, scalar_identity(value)) for name, value in sorted(bindings.items())
            )
            if binding_identity in seen_bindings:
                continue
            binding_offset = len(seen_bindings)
            seen_bindings.add(binding_identity)
            if binding_offset < offset:
                continue
            if len(solutions) >= max_results:
                complete = False
                stop_reason = "max_results"
                next_offset = offset + len(solutions)
                break
            explanation = self.explain_all(inference, key)
            solutions.append(QuerySolution(
                tuple(sorted(bindings.items())),
                key,
                fact_id,
                derived_fact.proofs if derived_fact is not None else (),
                explanation[0] if explanation else ExplanationNode(key),
            ))
        return QueryResult(
            tuple(solutions), complete, operations, facts_examined,
            len(inference.conclusions), stop_reason, inference, offset, next_offset,
        )
