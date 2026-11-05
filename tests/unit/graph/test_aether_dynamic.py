import random
import unittest
from array import array
from aether.graph.dynamic import (
    DynamicGraph,
    neighbors_within_hops,
    reachable_epoch,
    reachable_set,
    shortest_path,
)


def oracle(n, edges, s, t):
    if s == t: return True
    adj = [[] for _ in range(n)]
    for u, v in edges: adj[u].append(v)
    seen = {s}; stack = [s]
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if v == t: return True
            if v not in seen: seen.add(v); stack.append(v)
    return False


def shortest_path_oracle(n, edges, s, t, max_depth=None):
    if s == t: return [s]
    adj = [[] for _ in range(n)]
    for u, v in edges: adj[u].append(v)
    queue = [(s, [s])]
    cursor = 0
    while cursor < len(queue):
        u, path = queue[cursor]; cursor += 1
        if max_depth is not None and len(path) - 1 >= max_depth: continue
        for v in adj[u]:
            if v in path: continue
            candidate = path + [v]
            if v == t: return candidate
            queue.append((v, candidate))
    return None


class DynamicGraphTests(unittest.TestCase):
    def test_random_add_remove_stream_both_backends(self):
        n = 25
        for backend in ('sets', 'compact'):
            rng = random.Random(90210)
            graph = DynamicGraph(n, backend); edges = set(); marks = array('I', [0]) * n; epoch = 1
            for _ in range(500):
                u, v = rng.randrange(n), rng.randrange(n)
                if rng.random() < .55:
                    changed = graph.add_edge(u, v)
                    self.assertEqual(changed, (u, v) not in edges); edges.add((u, v))
                else:
                    changed = graph.remove_edge(u, v)
                    self.assertEqual(changed, (u, v) in edges); edges.discard((u, v))
                s, t = rng.randrange(n), rng.randrange(n)
                expected = oracle(n, edges, s, t)
                self.assertEqual(reachable_set(graph, s, t), expected)
                self.assertEqual(reachable_epoch(graph, s, t, marks, epoch), expected)
                epoch += 1

    def test_missing_edge_removal_and_invalid_id(self):
        for backend in ('sets', 'compact'):
            g = DynamicGraph(8, backend)
            self.assertFalse(g.remove_edge(1, 2))
            self.assertTrue(g.add_edge(1, 2)); self.assertFalse(g.add_edge(1, 2))
            self.assertTrue(g.remove_edge(1, 2)); self.assertFalse(g.has_edge(1, 2))
            with self.assertRaises(IndexError): g.add_edge(8, 0)

    def test_shortest_path_and_bounded_depth_after_removal(self):
        for backend in ('sets', 'compact'):
            g = DynamicGraph(7, backend)
            edges = {(0, 1), (1, 4), (0, 2), (2, 3), (3, 4), (4, 5), (6, 6)}
            for edge in edges: g.add_edge(*edge)
            path = shortest_path(g, 0, 5)
            self.assertEqual(len(path) - 1, 3)
            self.assertEqual(path[0], 0); self.assertEqual(path[-1], 5)
            self.assertEqual(shortest_path(g, 0, 5, max_depth=2), None)
            self.assertEqual(shortest_path(g, 0, 0), [0])
            self.assertEqual(neighbors_within_hops(g, 0, 1), {1, 2})
            self.assertEqual(neighbors_within_hops(g, 0, 2), {1, 2, 3, 4})
            g.remove_edge(1, 4); g.remove_edge(3, 4)
            self.assertIsNone(shortest_path(g, 0, 5))
            self.assertNotIn(5, neighbors_within_hops(g, 0, 5))

    def test_random_shortest_paths_match_independent_bfs(self):
        for backend in ('sets', 'compact'):
            for seed in range(12):
                rng = random.Random(7000 + seed)
                graph = DynamicGraph(18, backend); edges = set()
                for _ in range(50):
                    u, v = rng.randrange(18), rng.randrange(18)
                    if rng.random() < .7:
                        graph.add_edge(u, v); edges.add((u, v))
                    else:
                        graph.remove_edge(u, v); edges.discard((u, v))
                for _ in range(20):
                    s, t = rng.randrange(18), rng.randrange(18)
                    depth = rng.choice((None, 0, 1, 3, 6))
                    actual = shortest_path(graph, s, t, depth)
                    expected = shortest_path_oracle(18, edges, s, t, depth)
                    if actual is not None:
                        self.assertEqual(actual[0], s); self.assertEqual(actual[-1], t)
                        self.assertTrue(all((u, v) in edges for u, v in zip(actual, actual[1:])))
                        self.assertEqual(len(actual), len(expected))
                    else:
                        self.assertIsNone(expected)

    def test_invalid_bounds_and_buffers(self):
        g = DynamicGraph(3)
        with self.assertRaises(ValueError): shortest_path(g, 0, 1, -1)
        with self.assertRaises(ValueError): neighbors_within_hops(g, 0, 0)
        with self.assertRaises(ValueError): reachable_epoch(g, 0, 1, array('I', [0]), 1)
        with self.assertRaises(ValueError): reachable_epoch(g, 0, 1, array('I', [0, 0, 0]), 0)


class OnlineControllerTests(unittest.TestCase):
    def test_learns_real_query_cost_and_recalibrates_after_update(self):
        from benchmarks.phase3.phase3_bench import OnlineCostController
        g = DynamicGraph(20, 'compact'); marks = array('I', [0]) * 20
        for i in range(19): g.add_edge(i, i + 1)
        c = OnlineCostController()
        expected = reachable_set(g, 0, 19)
        self.assertEqual(c.query(g, 0, 19, marks, 1, 'wide'), expected)
        self.assertEqual(c.query(g, 19, 0, marks, 2, 'wide'), reachable_set(g, 19, 0))
        self.assertIsNotNone(c.route); self.assertEqual(c.probes, 2)
        c.notify_graph_change(); g.remove_edge(5, 6)
        for q in range(4): c.query(g, 2, 18, marks, 3 + q, 'after_remove')
        self.assertIsNotNone(c.ema['set']); self.assertIsNotNone(c.ema['epoch'])
        self.assertEqual(c.recalibrate_remaining, 0)


if __name__ == '__main__':
    unittest.main()
