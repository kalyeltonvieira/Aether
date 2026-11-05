import random
import unittest
from collections import deque

from aether_incremental_components import IncrementalWeakComponents


def oracle_components(n, edges):
    incident = [set() for _ in range(n)]
    for u, v in edges:
        incident[u].add(v)
        incident[v].add(u)
    labels = [-1] * n
    groups = []
    for start in range(n):
        if labels[start] != -1:
            continue
        group = set([start])
        queue = deque([start])
        labels[start] = len(groups)
        while queue:
            node = queue.popleft()
            for neighbor in incident[node]:
                if labels[neighbor] == -1:
                    labels[neighbor] = len(groups)
                    group.add(neighbor)
                    queue.append(neighbor)
        groups.append(group)
    return {frozenset(group) for group in groups}


def actual_components(index):
    return {index.component_nodes(node) for node in range(index.n)}


class IncrementalWeakComponentsTests(unittest.TestCase):
    def test_insertions_merge_and_removals_split_only_affected_component(self):
        index = IncrementalWeakComponents(8)
        index.add_edge(0, 1)
        index.add_edge(1, 2)
        index.add_edge(3, 4)
        index.add_edge(2, 3)
        self.assertEqual(index.component_count(), 4)
        index.remove_edge(1, 2)
        self.assertEqual(index.component_count(), 5)
        self.assertEqual(index.component_nodes(0), frozenset({0, 1}))
        self.assertEqual(index.component_nodes(2), frozenset({2, 3, 4}))
        self.assertGreater(index.stats()["splits"], 0)

    def test_reverse_arcs_do_not_split_until_both_are_removed(self):
        index = IncrementalWeakComponents(3)
        index.add_edge(0, 1)
        index.add_edge(1, 0)
        index.remove_edge(0, 1)
        self.assertEqual(index.component_count(), 2)
        self.assertEqual(index.component_nodes(0), frozenset({0, 1}))
        index.remove_edge(1, 0)
        self.assertEqual(index.component_count(), 3)

    def test_random_stream_matches_independent_oracle(self):
        rng = random.Random(20261105)
        n = 32
        index = IncrementalWeakComponents(n)
        active = set()
        for _ in range(500):
            edge = (rng.randrange(n), rng.randrange(n))
            if rng.random() < 0.58:
                changed = index.add_edge(*edge)
                expected = edge not in active
                active.add(edge)
            else:
                changed = index.remove_edge(*edge)
                expected = edge in active
                active.discard(edge)
            self.assertEqual(changed, expected)
            self.assertEqual(actual_components(index), oracle_components(n, active))

    def test_invalid_node_and_duplicate_operations(self):
        index = IncrementalWeakComponents(2)
        with self.assertRaises(IndexError): index.add_edge(2, 0)
        self.assertTrue(index.add_edge(0, 1))
        self.assertFalse(index.add_edge(0, 1))
        self.assertFalse(index.remove_edge(1, 0))


if __name__ == "__main__":
    unittest.main()
