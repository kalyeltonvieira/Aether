"""Bounded query-driven backward chaining for phase 7."""
from __future__ import annotations

from dataclasses import dataclass

from aether.reasoning.inference import Pattern, Rule
from aether.core.knowledge.store import KnowledgeStore, Scalar


@dataclass(frozen=True)
class BackwardLimits:
    max_depth: int = 8
    max_operations: int = 10000


@dataclass(frozen=True)
class Proof:
    goal: tuple[str, str, Scalar]
    proven: bool
    complete: bool
    depth: int
    operations: int
    supports: tuple[int, ...] = ()
    rule_id: str | None = None
    stop_reason: str | None = None


class BackwardInference:
    """Query-driven proof search with complete candidate enumeration under limits."""

    def __init__(self, store: KnowledgeStore, rules: tuple[Rule, ...] | list[Rule] = ()) -> None:
        if not isinstance(store, KnowledgeStore):
            raise TypeError("store must be a KnowledgeStore")
        self.store = store
        self.rules = tuple(rules)

    @staticmethod
    def _unify(value, pattern_value, bindings):
        if isinstance(pattern_value, str) and pattern_value.startswith("?"):
            current = bindings.get(pattern_value, ...)
            if current is ...:
                updated = dict(bindings)
                updated[pattern_value] = value
                return updated
            return dict(bindings) if current == value else None
        return dict(bindings) if value == pattern_value else None

    @classmethod
    def _match(cls, fact, pattern: Pattern, bindings):
        if fact.predicate != pattern.predicate:
            return None
        updated = cls._unify(fact.subject, pattern.subject, bindings)
        if updated is None:
            return None
        return cls._unify(fact.object, pattern.object, updated)

    @staticmethod
    def _resolve(value, bindings):
        if isinstance(value, str) and value.startswith("?"):
            return bindings.get(value, value)
        return value

    def prove(self, goal: tuple[str, str, Scalar], limits: BackwardLimits | None = None) -> Proof:
        limits = limits or BackwardLimits()
        if not isinstance(goal, tuple) or len(goal) != 3:
            raise TypeError("goal must be (subject, predicate, object)")
        operations = 0
        visiting: set[tuple[str, str, Scalar]] = set()
        incomplete_reason: str | None = None

        def search(current: tuple[str, str, Scalar], depth: int) -> Proof:
            nonlocal operations, incomplete_reason
            operations += 1
            if operations > limits.max_operations:
                incomplete_reason = "max_operations"
                return Proof(current, False, False, depth, operations, stop_reason="max_operations")
            if current in visiting:
                return Proof(current, False, True, depth, operations, stop_reason="cycle")
            direct = self.store.query(subject=current[0], predicate=current[1], object=current[2])
            if direct:
                return Proof(current, True, True, depth, operations, tuple(f.fact_id for f in direct))
            if depth >= limits.max_depth:
                incomplete_reason = "max_depth"
                return Proof(current, False, False, depth, operations, stop_reason="max_depth")

            visiting.add(current)
            any_incomplete = False
            for rule in self.rules:
                if rule.consequent.predicate != current[1]:
                    continue
                bindings = self._unify(current[0], rule.consequent.subject, {})
                if bindings is None:
                    continue
                bindings = self._unify(current[2], rule.consequent.object, bindings)
                if bindings is None:
                    continue

                def solve(index: int, current_bindings, supports: tuple[int, ...]):
                    nonlocal any_incomplete, operations, incomplete_reason
                    if index == len(rule.antecedents):
                        return Proof(current, True, True, depth, operations, supports, rule.rule_id)
                    antecedent = rule.antecedents[index]
                    subject = self._resolve(antecedent.subject, current_bindings)
                    object_value = self._resolve(antecedent.object, current_bindings)
                    pattern = Pattern(subject, antecedent.predicate, object_value)
                    candidates = self.store.query(predicate=pattern.predicate)
                    matched_any = False
                    for fact in candidates:
                        operations += 1
                        if operations > limits.max_operations:
                            incomplete_reason = "max_operations"
                            any_incomplete = True
                            return Proof(current, False, False, depth, operations, stop_reason="max_operations")
                        next_bindings = self._match(fact, pattern, current_bindings)
                        if next_bindings is None:
                            continue
                        matched_any = True
                        branch = solve(index + 1, next_bindings, supports + (fact.fact_id,))
                        if branch is None:
                            continue
                        if branch.proven:
                            return branch
                        if not branch.complete:
                            any_incomplete = True
                    if matched_any:
                        return None
                    if isinstance(subject, str) and subject.startswith("?") or isinstance(object_value, str) and object_value.startswith("?"):
                        any_incomplete = True
                        return None
                    branch = search((subject, antecedent.predicate, object_value), depth + 1)
                    if branch.proven:
                        return solve(index + 1, current_bindings, supports + branch.supports)
                    if not branch.complete:
                        any_incomplete = True
                    return None

                result = solve(0, bindings, ())
                if result is not None and result.proven:
                    visiting.remove(current)
                    return result
            visiting.remove(current)
            if any_incomplete:
                return Proof(current, False, False, depth, operations, stop_reason=incomplete_reason or "limit")
            return Proof(current, False, True, depth, operations, stop_reason="not_proven")

        return search(goal, 0)
