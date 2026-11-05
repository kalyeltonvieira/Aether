"""Incremental weakly-connected components for mutable directed graphs.

Directed arcs are treated as undirected connections. Insertions merge component
sets in-place. A removal checks only the affected component; if the removed arc
splits it, a bounded BFS over that component relabels the two resulting parts.
The implementation is exact and exposes work counters for comparison with full
recomputation.
"""
from __future__ import annotations

from collections import deque

from aether_dynamic import DynamicGraph


class IncrementalWeakComponents:
    def __init__(self, n: int, backend: str = "compact"):
        self.graph = DynamicGraph(n, backend)
        self.n = n
        self._incident = [set() for _ in range(n)]
        self._connection_counts: dict[tuple[int, int], int] = {}
        self._component_of = list(range(n))
        self._members = {node: {node} for node in range(n)}
        self.insertions = 0
        self.removals = 0
        self.merges = 0
        self.splits = 0
        self.affected_nodes_scanned = 0
        self.full_recomputations = 0

    def _check(self, u: int, v: int) -> None:
        self.graph._check(u, v)

    def _merge(self, left: int, right: int) -> None:
        if left == right:
            return
        if len(self._members[left]) < len(self._members[right]):
            left, right = right, left
        moved = self._members.pop(right)
        for node in moved:
            self._component_of[node] = left
        self._members[left].update(moved)
        self.merges += 1

    def add_edge(self, u: int, v: int) -> bool:
        self._check(u, v)
        changed = self.graph.add_edge(u, v)
        if not changed:
            return False
        self.insertions += 1
        key = (u, v) if u <= v else (v, u)
        self._connection_counts[key] = self._connection_counts.get(key, 0) + 1
        self._incident[u].add(v)
        self._incident[v].add(u)
        self._merge(self._component_of[u], self._component_of[v])
        return True

    def _reachable_without_removed_edge(self, source: int, target: int, skip_direct: bool) -> set[int]:
        seen = {source}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            for neighbor in self._incident[node]:
                if skip_direct and node == source and neighbor == target:
                    continue
                if skip_direct and node == target and neighbor == source:
                    continue
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        self.affected_nodes_scanned += len(seen)
        return seen

    def remove_edge(self, u: int, v: int) -> bool:
        self._check(u, v)
        if not self.graph.has_edge(u, v):
            return False
        changed = self.graph.remove_edge(u, v)
        if not changed:
            return False
        self.removals += 1
        key = (u, v) if u <= v else (v, u)
        remaining = self._connection_counts[key] - 1
        if remaining:
            self._connection_counts[key] = remaining
        else:
            del self._connection_counts[key]
            self._incident[u].discard(v)
            self._incident[v].discard(u)
        if u == v:
            return True
        component = self._component_of[u]
        if component != self._component_of[v]:
            raise RuntimeError("component index inconsistent before removal")
        reached = self._reachable_without_removed_edge(u, v, key not in self._connection_counts)
        if v in reached:
            return True
        members = self._members[component]
        other = members - reached
        if not other:
            raise RuntimeError("component split produced an empty side")
        new_component = max(self._members, default=-1) + 1
        self._members[component] = set(reached)
        self._members[new_component] = set(other)
        for node in reached:
            self._component_of[node] = component
        for node in other:
            self._component_of[node] = new_component
        self.splits += 1
        return True

    def component_count(self) -> int:
        return len(self._members)

    def labels(self) -> tuple[int, ...]:
        return tuple(self._component_of)

    def component_nodes(self, node: int) -> frozenset[int]:
        if not isinstance(node, int) or isinstance(node, bool) or not 0 <= node < self.n:
            raise IndexError("node id out of range")
        return frozenset(self._members[self._component_of[node]])

    def stats(self) -> dict:
        return {
            "nodes": self.n,
            "edges": sum(len(row) for row in self.graph.rows),
            "components": self.component_count(),
            "insertions": self.insertions,
            "removals": self.removals,
            "merges": self.merges,
            "splits": self.splits,
            "affected_nodes_scanned": self.affected_nodes_scanned,
            "full_recomputations": self.full_recomputations,
        }

    @classmethod
    def from_edges(cls, n: int, edges, backend: str = "compact"):
        result = cls(n, backend)
        for u, v in edges:
            result.add_edge(u, v)
        return result
