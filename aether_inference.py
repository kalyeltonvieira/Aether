"""Bounded, deterministic relational inference for AETHER phase 7."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from aether_knowledge import Fact, KnowledgeStore, Scalar


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


@dataclass(frozen=True)
class Rule:
    rule_id: str
    antecedents: tuple[Pattern, ...]
    consequent: Pattern

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not self.rule_id.strip():
            raise ValueError("rule_id must be a non-empty string")
        if not self.antecedents:
            raise ValueError("a rule needs at least one antecedent")
        variables = set().union(*(pattern.variables() for pattern in self.antecedents))
        if not self.consequent.variables() <= variables:
            raise ValueError("consequent variables must occur in antecedents")


@dataclass(frozen=True)
class InferenceLimits:
    max_depth: int = 8
    max_operations: int = 10000
    max_conclusions: int = 1000

    def __post_init__(self) -> None:
        for name, value in (("max_depth", self.max_depth), ("max_operations", self.max_operations), ("max_conclusions", self.max_conclusions)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class DerivedFact:
    subject: str
    predicate: str
    object: Scalar
    rule_id: str
    depth: int
    supports: tuple[int | tuple[str, str, Scalar], ...]

    @property
    def key(self) -> tuple[str, str, Scalar]:
        return self.subject, self.predicate, self.object


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
        return next((fact for fact in self.conclusions if fact.key == key), None)


class InferenceEngine:
    """Forward chaining over explicit facts with bounded joins and explanations."""

    def __init__(self, store: KnowledgeStore, rules: tuple[Rule, ...] | list[Rule] = ()) -> None:
        if not isinstance(store, KnowledgeStore):
            raise TypeError("store must be a KnowledgeStore")
        self.store = store
        self.rules: list[Rule] = []
        self._rule_ids: set[str] = set()
        for rule in rules:
            self.add_rule(rule)

    def add_rule(self, rule: Rule) -> None:
        if not isinstance(rule, Rule):
            raise TypeError("rule must be a Rule")
        if rule.rule_id in self._rule_ids:
            raise ValueError(f"duplicate rule id: {rule.rule_id}")
        self.rules.append(rule)
        self._rule_ids.add(rule.rule_id)

    @staticmethod
    def _match(value, expected, bindings: Mapping[str, Scalar]):
        if isinstance(expected, str) and expected.startswith("?"):
            bound = bindings.get(expected, ...)
            if bound is ...:
                updated = dict(bindings)
                updated[expected] = value
                return updated
            return dict(bindings) if bound == value else None
        return dict(bindings) if value == expected else None

    @classmethod
    def _match_pattern(cls, fact_key, pattern: Pattern, bindings):
        subject, predicate, object = fact_key
        if predicate != pattern.predicate:
            return None
        next_bindings = cls._match(subject, pattern.subject, bindings)
        if next_bindings is None:
            return None
        return cls._match(object, pattern.object, next_bindings)

    @staticmethod
    def _instantiate(pattern: Pattern, bindings: Mapping[str, Scalar]) -> tuple[str, str, Scalar]:
        def resolve(value):
            if isinstance(value, str) and value.startswith("?"):
                return bindings[value]
            return value
        return resolve(pattern.subject), pattern.predicate, resolve(pattern.object)

    def _known_by_predicate(self, derived: Mapping[tuple[str, str, Scalar], DerivedFact]):
        grouped: dict[str, list[tuple[tuple[str, str, Scalar], int | tuple[str, str, Scalar]]]] = {}
        for fact in self.store.query():
            key = (fact.subject, fact.predicate, fact.object)
            grouped.setdefault(fact.predicate, []).append((key, fact.fact_id))
        for key, fact in derived.items():
            grouped.setdefault(key[1], []).append((key, key))
        return grouped

    def _join_rule(self, rule: Rule, derived):
        grouped = self._known_by_predicate(derived)
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

    def infer(self, limits: InferenceLimits | None = None) -> InferenceResult:
        limits = limits or InferenceLimits()
        derived: dict[tuple[str, str, Scalar], DerivedFact] = {}
        conclusions: list[DerivedFact] = []
        operations = 0
        facts_examined = 0
        rules_applied = 0
        max_depth_reached = 0
        stop_reason = None
        for depth in range(1, limits.max_depth + 1):
            max_depth_reached = depth
            produced: list[DerivedFact] = []
            for rule in self.rules:
                partials, examined = self._join_rule(rule, derived)
                facts_examined += examined
                rules_applied += 1
                operations += max(1, examined)
                if operations > limits.max_operations:
                    stop_reason = "max_operations"
                    return InferenceResult(tuple(conclusions), operations, max_depth_reached, False, stop_reason, facts_examined, rules_applied)
                for bindings, supports in partials:
                    key = self._instantiate(rule.consequent, bindings)
                    if key in derived or any((fact.subject, fact.predicate, fact.object) == key for fact in self.store.query()):
                        continue
                    conclusion = DerivedFact(key[0], key[1], key[2], rule.rule_id, depth, supports)
                    produced.append(conclusion)
                    if len(conclusions) + len(produced) >= limits.max_conclusions:
                        stop_reason = "max_conclusions"
                        break
                if stop_reason:
                    break
            if stop_reason:
                break
            if not produced:
                return InferenceResult(tuple(conclusions), operations, max_depth_reached, True, None, facts_examined, rules_applied)
            for fact in produced:
                derived[fact.key] = fact
                conclusions.append(fact)
        if stop_reason is None and max_depth_reached >= limits.max_depth:
            stop_reason = "max_depth"
        return InferenceResult(tuple(conclusions), operations, max_depth_reached, stop_reason is None, stop_reason, facts_examined, rules_applied)

    @staticmethod
    def explain(result: InferenceResult, key: tuple[str, str, Scalar]) -> tuple[DerivedFact, ...]:
        target = result.by_key(key)
        if target is None:
            return ()
        explanation = [target]
        queue = list(target.supports)
        seen = {target.key}
        derived_by_key = {fact.key: fact for fact in result.conclusions}
        while queue:
            support = queue.pop(0)
            if not isinstance(support, tuple) or len(support) != 3 or not isinstance(support[0], str):
                continue
            fact = derived_by_key.get(support)
            if fact is not None and fact.key not in seen:
                seen.add(fact.key)
                explanation.append(fact)
                queue.extend(fact.supports)
        return tuple(explanation)
