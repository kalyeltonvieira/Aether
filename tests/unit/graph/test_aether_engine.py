import random
import unittest
from aether.graph.engine import AdaptiveReachability


def bfs(n, edges, source, target):
    if source == target:
        return True
    adj = [[] for _ in range(n)]
    for u, v in edges:
        adj[u].append(v)
    seen, stack = {source}, [source]
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if v == target:
                return True
            if v not in seen:
                seen.add(v); stack.append(v)
    return False


class AdaptiveReachabilityTests(unittest.TestCase):
    def test_both_routes_match_bfs_during_updates(self):
        n = 9
        for forecast in (0, 100_000):
            for seed in range(30):
                rng = random.Random(seed)
                pairs = [(u, v) for u in range(n) for v in range(n) if u != v]
                rng.shuffle(pairs)
                initial, updates = pairs[:12], pairs[12:30]
                engine = AdaptiveReachability(n, initial, expected_updates=len(updates), expected_queries=forecast)
                edges = set(initial)
                for u, v in updates:
                    engine.add_edge(u, v); edges.add((u, v))
                    for _ in range(8):
                        s, t = rng.randrange(n), rng.randrange(n)
                        self.assertEqual(engine.reachable(s, t), bfs(n, edges, s, t))

    def test_expected_query_volume_changes_strategy(self):
        self.assertEqual(AdaptiveReachability(120, [(i, (i+1)%120) for i in range(20)], expected_queries=0).strategy, 'bitset_bfs')
        self.assertEqual(AdaptiveReachability(120, [(i, (i+1)%120) for i in range(20)], expected_queries=20_000).strategy, 'aether_rows_only')

    def test_invalid_node_rejected(self):
        engine = AdaptiveReachability(3)
        with self.assertRaises(IndexError): engine.reachable(-1, 0)
        with self.assertRaises(IndexError): engine.add_edge(0, 3)


if __name__ == '__main__':
    unittest.main()
