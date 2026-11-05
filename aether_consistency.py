"""Explicit consistency checks for the phase 7 knowledge layer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from aether_inference import InferenceResult, Rule
from aether_knowledge import KnowledgeStore


@dataclass(frozen=True)
class ConsistencyIssue:
    code: str
    message: str
    facts: tuple[int, ...] = ()
    rules: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConsistencyReport:
    issues: tuple[ConsistencyIssue, ...]

    @property
    def consistent(self) -> bool:
        return not self.issues


class ConsistencyValidator:
    """Detect contradictions without selecting a winner or inventing evidence."""

    def __init__(self, store: KnowledgeStore) -> None:
        if not isinstance(store, KnowledgeStore):
            raise TypeError("store must be a KnowledgeStore")
        self.store = store

    def validate(
        self,
        *,
        incompatible_predicates: Iterable[tuple[str, str]] = (),
        acyclic_predicates: Iterable[str] = (),
        inference: InferenceResult | None = None,
        rules: Iterable[Rule] = (),
    ) -> ConsistencyReport:
        issues: list[ConsistencyIssue] = []
        for fact in self.store.query():
            if fact.provenance is None:
                issues.append(ConsistencyIssue("missing_provenance", f"fact {fact.fact_id} has no provenance", (fact.fact_id,)))

        facts = list(self.store.query())
        by_pair: dict[tuple[str, str], list[int]] = {}
        for left, right in incompatible_predicates:
            if not isinstance(left, str) or not isinstance(right, str) or not left or not right:
                raise ValueError("incompatible predicate names must be non-empty strings")
        for first, second in incompatible_predicates:
            for fact in facts:
                if fact.predicate != first:
                    continue
                conflicts = [other.fact_id for other in facts if other.subject == fact.subject and other.object == fact.object and other.predicate == second]
                if conflicts:
                    issues.append(ConsistencyIssue("incompatible_facts", f"{first} conflicts with {second} for {fact.subject}/{fact.object}", (fact.fact_id, *conflicts)))

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
                # Each frame holds a node, its remaining edges, and the edge
                # used to enter it. This avoids Python recursion limits.
                stack: list[tuple[str, Iterator[tuple[str, int]], int | None]] = [
                    (start, iter(adjacency.get(start, ())), None)
                ]
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
                        cycle_facts = tuple(
                            frame[2] for frame in stack[cycle_start + 1:] if frame[2] is not None
                        ) + (fact_id,)
                        issues.append(
                            ConsistencyIssue(
                                "forbidden_cycle",
                                f"cycle detected for predicate {predicate}",
                                cycle_facts,
                            )
                        )
                    elif target not in visited:
                        active_index[target] = len(stack)
                        stack.append((target, iter(adjacency.get(target, ())), fact_id))

        rule_list = list(rules)
        for index, first in enumerate(rule_list):
            for second in rule_list[index + 1 :]:
                if first.antecedents == second.antecedents and first.consequent != second.consequent:
                    issues.append(ConsistencyIssue("contradictory_rules", f"rules {first.rule_id} and {second.rule_id} have identical premises", rules=(first.rule_id, second.rule_id)))

        if inference is not None:
            existing_ids = {fact.fact_id for fact in self.store.query()}
            derived_keys = {fact.key for fact in inference.conclusions}
            for conclusion in inference.conclusions:
                for support in conclusion.supports:
                    if isinstance(support, int) and support not in existing_ids:
                        issues.append(ConsistencyIssue("invalid_dependency", f"conclusion {conclusion.key} references missing fact {support}"))
                    elif isinstance(support, tuple) and support not in derived_keys:
                        issues.append(ConsistencyIssue("invalid_dependency", f"conclusion {conclusion.key} references missing derived fact {support}"))
        return ConsistencyReport(tuple(issues))
