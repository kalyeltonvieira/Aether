"""Versioned Rust-backed relation index with Python provenance preservation."""
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
    store_version: int = 0


class RustKnowledgeIndex:
    """A versioned snapshot of one directed predicate relation.

    ``has_fact`` checks a direct explicit edge. ``reachable`` and
    ``reachable_transitively`` check paths in this directed relation. The Python
    KnowledgeStore remains authoritative for IDs, attributes and provenance.
    A changed store is never queried silently: call ``refresh()`` first.
    """

    def __init__(self, store: KnowledgeStore, predicate: str, *, library=None):
        if not isinstance(store, KnowledgeStore):
            raise TypeError("store must be a KnowledgeStore")
        if not isinstance(predicate, str) or not predicate.strip():
            raise ValueError("predicate must be non-empty")
        self.store = store
        self.predicate = predicate
        self.library = library
        self._closed = False
        self._install_snapshot(self._build_snapshot())

    def _build_snapshot(self):
        version = self.store.version
        conversion_start = time.perf_counter_ns()
        entity_to_node = {
            entity.entity_id: index
            for index, entity in enumerate(sorted(self.store.entities(), key=lambda item: item.entity_id))
        }
        facts = self.store.query(predicate=self.predicate)
        edges = []
        for fact in facts:
            if not isinstance(fact.object, str):
                raise ValueError("relation object must be a known entity identifier")
            try:
                edges.append((entity_to_node[fact.subject], entity_to_node[fact.object]))
            except KeyError as exc:
                raise ValueError("relation subject and object must be known entities") from exc
        conversion_ns = time.perf_counter_ns() - conversion_start
        if self.store.version != version:
            raise RuntimeError("KnowledgeStore changed while building the Rust index; retry refresh()")
        rust_start = time.perf_counter_ns()
        graph = RustDynamicGraph(len(entity_to_node), edges, library=self.library)
        rust_build_ns = time.perf_counter_ns() - rust_start
        if self.store.version != version:
            graph.close()
            raise RuntimeError("KnowledgeStore changed while building the Rust index; retry refresh()")
        build = RustKnowledgeBuild(
            self.predicate,
            len(entity_to_node),
            len(facts),
            conversion_ns,
            rust_build_ns,
            version,
        )
        return version, entity_to_node, graph, conversion_ns, rust_build_ns, build

    def _install_snapshot(self, snapshot) -> None:
        (
            self._store_version,
            self.entity_to_node,
            self.graph,
            self.conversion_ns,
            self.rust_build_ns,
            self.build,
        ) = snapshot

    @property
    def store_version(self) -> int:
        return self._store_version

    def _ensure_current(self) -> None:
        if self._closed:
            raise RuntimeError("RustKnowledgeIndex is closed")
        if self.store.version != self._store_version:
            raise RuntimeError(
                f"RustKnowledgeIndex is stale (snapshot version {self._store_version}, "
                f"store version {self.store.version}); call refresh() before querying"
            )

    def refresh(self) -> RustKnowledgeBuild:
        """Atomically replace the native snapshot with the current store state."""
        self._ensure_current_or_open()
        snapshot = self._build_snapshot()
        old_graph = self.graph
        self._install_snapshot(snapshot)
        old_graph.close()
        return self.build

    def _ensure_current_or_open(self) -> None:
        if self._closed:
            raise RuntimeError("RustKnowledgeIndex is closed")

    def has_fact(self, subject: str, object: Scalar) -> bool:
        self._ensure_current()
        if not isinstance(subject, str) or not isinstance(object, str):
            return False
        try:
            source = self.entity_to_node[subject]
            target = self.entity_to_node[object]
        except KeyError:
            return False
        result = self.graph.has_edge(source, target)
        self._ensure_current()
        return result

    def reachable(self, subject: str, object: Scalar) -> bool:
        """Return transitive directed reachability, including reflexive identity."""
        self._ensure_current()
        if not isinstance(subject, str) or not isinstance(object, str):
            return False
        try:
            source = self.entity_to_node[subject]
            target = self.entity_to_node[object]
        except KeyError:
            return False
        result = self.graph.reachable(source, target)
        self._ensure_current()
        return result

    def reachable_transitively(self, subject: str, object: Scalar) -> bool:
        return self.reachable(subject, object)

    def close(self) -> None:
        if not self._closed:
            self.graph.close()
            self._closed = True

    def __enter__(self):
        self._ensure_current()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
