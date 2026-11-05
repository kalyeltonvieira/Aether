"""Weakly connected components over the existing directed AETHER adjacency."""
from __future__ import annotations

from array import array


def weak_component_labels(graph):
    """Return (root-label array, component count) treating each directed arc as undirected.

    The method scans the existing outgoing rows once and uses union-find with
    path compression and union by rank. It reports weak components, not strongly
    connected components. No graph copy or persistent cache is retained.
    """
    if not hasattr(graph, "n") or not callable(getattr(graph, "neighbors", None)):
        raise TypeError("graph must expose n and neighbors(node)")
    n = graph.n
    if isinstance(n, bool) or not isinstance(n, int) or n < 1 or n > 0xFFFFFFFF:
        raise ValueError("graph.n must be in [1, 2**32-1]")
    if array("I").itemsize != 4:
        raise RuntimeError("component labels require 32-bit unsigned integers")

    parent = array("I", range(n))
    rank = bytearray(n)

    def find(node):
        root = node
        while parent[root] != root:
            parent[root] = parent[parent[root]]
            root = parent[root]
        while node != root:
            next_node = parent[node]
            parent[node] = root
            node = next_node
        return root

    for source in range(n):
        for target in graph.neighbors(source):
            root_source = find(source)
            root_target = find(target)
            if root_source == root_target:
                continue
            if rank[root_source] < rank[root_target]:
                parent[root_source] = root_target
            elif rank[root_source] > rank[root_target]:
                parent[root_target] = root_source
            else:
                parent[root_target] = root_source
                rank[root_source] += 1

    labels = array("I", [0]) * n
    count = 0
    for node in range(n):
        root = find(node)
        labels[node] = root
        if root == node:
            count += 1
    return labels, count
