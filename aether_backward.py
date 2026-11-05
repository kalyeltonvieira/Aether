"""Bounded query-driven backward chaining for phase 7."""
from __future__ import annotations

from dataclasses import dataclass

from aether_inference import Pattern, Rule
from aether_knowledge import KnowledgeStore, Scalar


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
    def __init__(self, store: KnowledgeStore, rules: tuple[Rule, ...] | list[Rule] = ()) -> None:
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

        def search(current: tuple[str, str, Scalar], depth: int) -> Proof:
            nonlocal operations
            operations += 1
            if operations > limits.max_operations:
                return Proof(current, False, False, depth, operations, stop_reason="max_operations")
            if current in visiting:
                return Proof(current, False, True, depth, operations, stop_reason="cycle")
            direct = self.store.query(subject=current[0], predicate=current[1], object=current[2])
            if direct:
                return Proof(current, True, True, depth, operations, tuple(f.fact_id for f in direct))
            if depth >= limits.max_depth:
                return Proof(current, False, False, depth, operations, stop_reason="max_depth")
            visiting.add(current)
            incomplete = False
            incomplete_reason = None
            for rule in self.rules:
                consequent = rule.consequent
                bindings = self._unify(current[0], consequent.subject, {})
                if bindings is None or consequent.predicate != current[1]:
                    continue
                bindings = self._unify(current[2], consequent.object, bindings)
                if bindings is None:
                    continue
                support_ids: list[int] = []
                valid = True
                for antecedent in rule.antecedents:
                    subject = self._resolve(antecedent.subject, bindings)
                    object = self._resolve(antecedent.object, bindings)
                    if isinstance(subject, str) and subject.startswith("?"):
                        valid = False
                        break
                    if isinstance(object, str) and object.startswith("?"):
                        candidates = self.store.query(subject=subject, predicate=antecedent.predicate)
                        if not candidates:
                            valid = False
                            break
                        candidate = candidates[0]
                        bindings = self._unify(candidate.object, antecedent.object, bindings)
                        if bindings is None:
                            valid = False
                            break
                        support_ids.append(candidate.fact_id)
                        continue
                    proof = search((subject, antecedent.predicate, object), depth + 1)
                    if not proof.proven:
                        valid = False
                        incomplete = incomplete or not proof.complete
                        if not proof.complete:
                            incomplete_reason = proof.stop_reason
                        break
                    support_ids.extend(proof.supports)
                if valid:
                    visiting.remove(current)
                    return Proof(current, True, not incomplete, depth, operations, tuple(support_ids), rule.rule_id)
            visiting.remove(current)
            return Proof(current, False, not incomplete, depth, operations, stop_reason=incomplete_reason or "not_proven")

        return search(goal, 0)
