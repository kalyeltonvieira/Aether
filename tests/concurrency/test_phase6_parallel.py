import unittest

from aether.graph.dynamic import DynamicGraph, reachable_set
from aether.graph.parallel import parallel_reachability


class ParallelReachabilityTests(unittest.TestCase):
    def factory(self, n, edges):
        graph = DynamicGraph(n, "compact")
        for source, target in edges:
            graph.add_edge(source, target)
        return graph

    def test_parallel_results_match_sequential_oracle_in_original_order(self):
        edges = [(0, 1), (1, 2), (2, 3), (4, 5)]
        pairs = [(0, 3), (3, 0), (4, 5), (5, 4), (6, 6), (0, 5)]
        expected = [reachable_set(self.factory(7, edges), *pair) for pair in pairs]
        actual, stats = parallel_reachability(self.factory, 7, edges, pairs, workers=3)
        self.assertEqual(actual, expected)
        self.assertEqual(stats["queries"], len(pairs))
        self.assertEqual(stats["isolated_handles"], 3)
        self.assertGreaterEqual(stats["total_ms"], stats["query_ms"])

    def test_empty_workload_does_not_create_handles(self):
        result, stats = parallel_reachability(self.factory, 4, [], [], workers=2)
        self.assertEqual(result, [])
        self.assertEqual(stats["isolated_handles"], 0)

    def test_invalid_worker_count_is_rejected(self):
        with self.assertRaises(ValueError):
            parallel_reachability(self.factory, 2, [], [(0, 0)], workers=0)


if __name__ == "__main__":
    unittest.main()
