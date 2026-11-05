import unittest

from aether.temporal.checkpoints import SelectiveCheckpointHistory
from aether.graph.dynamic import DynamicGraph


def edge_set(graph):
    return {(u, v) for u in range(graph.n) for v in graph.neighbors(u)}


class SelectiveCheckpointTests(unittest.TestCase):
    def build(self, strategy):
        history = SelectiveCheckpointHistory(8, strategy=strategy, interval=3, target_recovery_ms=0.0001)
        events = [
            (1, "add", 0, 1),
            (2, "add", 1, 2),
            (3, "add", 2, 3),
            (4, "add", 3, 4),
            (5, "remove", 1, 2),
            (6, "add", 4, 5),
            (7, "add", 5, 6),
            (8, "remove", 0, 1),
        ]
        for event in events:
            history.append(*event)
        return history

    def test_all_strategies_match_independent_replay_at_every_prefix(self):
        for strategy in SelectiveCheckpointHistory.STRATEGIES:
            history = self.build(strategy)
            for count in range(history.event_count + 1):
                actual = edge_set(history.state_at_event_count(count))
                oracle = DynamicGraph(8, "compact")
                events = [
                    (1, "add", 0, 1), (2, "add", 1, 2), (3, "add", 2, 3),
                    (4, "add", 3, 4), (5, "remove", 1, 2), (6, "add", 4, 5),
                    (7, "add", 5, 6), (8, "remove", 0, 1),
                ]
                for _, operation, source, target in events[:count]:
                    (oracle.add_edge if operation == "add" else oracle.remove_edge)(source, target)
                self.assertEqual(actual, edge_set(oracle), strategy)

    def test_periodic_and_adaptive_create_checkpoints(self):
        periodic = self.build("periodic")
        adaptive = self.build("adaptive")
        self.assertGreaterEqual(periodic.checkpoint_count, 2)
        self.assertGreaterEqual(adaptive.checkpoint_count, 2)
        self.assertGreater(adaptive.stats()["checkpoint_bytes"], 0)

    def test_recovery_uses_checkpoint_suffix(self):
        history = self.build("periodic")
        history.state_at_event_count(8)
        stats = history.stats()
        self.assertLess(stats["replayed_events"], history.event_count)
        self.assertGreaterEqual(stats["recovery_count"], 1)

    def test_replay_strategy_never_materializes_checkpoints(self):
        history = self.build("replay")
        self.assertEqual(history.checkpoint_count, 0)
        history.state_at_event_count(history.event_count)
        self.assertEqual(history.stats()["replayed_events"], history.event_count)

    def test_invalid_arguments_are_rejected(self):
        with self.assertRaises(ValueError): SelectiveCheckpointHistory(4, strategy="bad")
        with self.assertRaises(ValueError): SelectiveCheckpointHistory(4, interval=0)
        history = SelectiveCheckpointHistory(4)
        with self.assertRaises(ValueError): history.append(0, "bad", 0, 1)
        with self.assertRaises(IndexError): history.state_at_event_count(1)


if __name__ == "__main__":
    unittest.main()
