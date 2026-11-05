import random
import unittest
from collections import deque

from aether_components import weak_component_labels
from aether_dynamic import DynamicGraph


def weak_oracle(graph):
    adjacency = [set() for _ in range(graph.n)]
    for source in range(graph.n):
        for target in graph.neighbors(source):
            adjacency[source].add(target)
            adjacency[target].add(source)
    labels = [-1] * graph.n
    count = 0
    for start in range(graph.n):
        if labels[start] >= 0:
            continue
        queue = deque([start])
        labels[start] = count
        while queue:
            node = queue.popleft()
            for neighbor in adjacency[node]:
                if labels[neighbor] < 0:
                    labels[neighbor] = count
                    queue.append(neighbor)
        count += 1
    return labels, count


def same_partition(left, right):
    forward, reverse = {}, {}
    for a, b in zip(left, right):
        if a in forward and forward[a] != b:
            return False
        if b in reverse and reverse[b] != a:
            return False
        forward[a] = b
        reverse[b] = a
    return True


class WeakComponentsTests(unittest.TestCase):
    def test_disconnected_directed_graph_self_loops_and_isolates(self):
        graph = DynamicGraph(9, "compact")
        for edge in [(0, 1), (2, 1), (2, 3), (4, 5), (6, 6)]:
            graph.add_edge(*edge)
        labels, count = weak_component_labels(graph)
        oracle_labels, oracle_count = weak_oracle(graph)
        self.assertEqual(count, 5)
        self.assertEqual(count, oracle_count)
        self.assertTrue(same_partition(labels, oracle_labels))
        self.assertNotEqual(labels[6], labels[7])
        self.assertNotEqual(labels[7], labels[8])
        self.assertNotEqual(labels[0], labels[4])

    def test_recomputes_after_merge_and_split_updates(self):
        graph = DynamicGraph(8, "sets")
        for edge in [(0, 1), (2, 3), (4, 5)]:
            graph.add_edge(*edge)
        first, first_count = weak_component_labels(graph)
        self.assertEqual(first_count, 5)
        graph.add_edge(3, 4)
        merged, merged_count = weak_component_labels(graph)
        self.assertEqual(merged_count, 4)
        self.assertEqual(merged[2], merged[5])
        graph.remove_edge(3, 4)
        split, split_count = weak_component_labels(graph)
        self.assertEqual(split_count, 5)
        self.assertNotEqual(split[2], split[4])
        self.assertEqual(first_count, split_count)

    def test_random_graphs_match_independent_weak_bfs(self):
        for seed in range(30):
            rng = random.Random(seed)
            n = 25
            graph = DynamicGraph(n, "compact")
            for _ in range(60):
                source, target = rng.randrange(n), rng.randrange(n)
                graph.add_edge(source, target)
            labels, count = weak_component_labels(graph)
            oracle_labels, oracle_count = weak_oracle(graph)
            self.assertEqual(count, oracle_count, seed)
            self.assertTrue(same_partition(labels, oracle_labels), seed)

    def test_rejects_incompatible_graph(self):
        with self.assertRaises(TypeError):
            weak_component_labels(object())


if __name__ == "__main__":
    unittest.main()
