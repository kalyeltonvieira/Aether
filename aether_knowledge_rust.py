"""Rust-backed relational index with Python provenance preservation."""
from __future__ import annotations

import time
from dataclasses import dataclass

from aether_knowledge import KnowledgeStore, Scalar
from aether_native import RustDynamicGraph


@dataclass(frozen=True)
class RustKnowledgeBuild:
    predicate: str
    entities: int
    facts: int
    conversion_ns: int
    rust_build_ns: int


class RustKnowledgeIndex:
    """Use the existing ABI v2 graph kernel for one predicate relation.

    KnowledgeStore remains authoritative for fact identity, properties and
    provenance. Rust receives only dense node IDs and relation edges, so the
    conversion cost is measured rather than hidden.
    """

    def __init__(self, store: KnowledgeStore, predicate: str, *, library=None):
        if not isinstance(store, KnowledgeStore):
            raise TypeError("store must be a KnowledgeStore")
        if not isinstance(predicate, str) or not predicate.strip():
            raise ValueError("predicate must be non-empty")
        self.store = store
        self.predicate = predicate
        conversion_start = time.perf_counter_ns()
        self.entity_to_node = {entity.entity_id: index for index, entity in enumerate(sorted(store.entities(), key=lambda item: item.entity_id))}
        facts = store.query(predicate=predicate)
        edges = []
        for fact in facts:
            try:
                edges.append((self.entity_to_node[fact.subject], self.entity_to_node[fact.object]))
            except KeyError as exc:
                raise ValueError("relation object is not a known entity") from exc
        self.conversion_ns = time.perf_counter_ns() - conversion_start
        rust_start = time.perf_counter_ns()
        self.graph = RustDynamicGraph(len(self.entity_to_node), edges, library=library)
        self.rust_build_ns = time.perf_counter_ns() - rust_start
        self.build = RustKnowledgeBuild(predicate, len(self.entity_to_node), len(facts), self.conversion_ns, self.rust_build_ns)

    def has_fact(self, subject: str, object: Scalar) -> bool:
        if not isinstance(object, str):
            return False
        try:
            source = self.entity_to_node[subject]
            target = self.entity_to_node[object]
        except KeyError:
            return False
        return self.graph.has_edge(source, target)

    def reachable(self, subject: str, object: Scalar) -> bool:
        if not isinstance(object, str):
            return False
        try:
            source = self.entity_to_node[subject]
            target = self.entity_to_node[object]
        except KeyError:
            return False
        return self.graph.reachable(source, target)

    def close(self) -> None:
        self.graph.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
