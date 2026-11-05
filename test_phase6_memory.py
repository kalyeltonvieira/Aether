import tempfile
import unittest
from pathlib import Path

from aether_adaptive_memory import AdaptiveMemory, MemoryPolicyComparison
from aether_pattern import IncrementalPatternLearner, PatternEvent


class AdaptiveMemoryTests(unittest.TestCase):
    def test_budget_eviction_and_cold_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            memory = AdaptiveMemory(8, cold_store=Path(folder) / "cold.jsonl")
            memory.put("a", b"1234")
            memory.put("b", b"5678")
            memory.put("c", b"zzzz")
            self.assertLessEqual(memory.stats()["resident_bytes"], 8)
            self.assertGreaterEqual(memory.stats()["evictions"], 1)
            self.assertEqual(memory.get("a"), b"1234")
            self.assertGreaterEqual(memory.stats()["hits"], 1)

    def test_frequency_tiers_and_deduplication(self):
        memory = AdaptiveMemory(100, warm_accesses=2, hot_accesses=3)
        memory.put("x", b"payload")
        memory.put("x", b"payload")
        self.assertEqual(memory.stats()["deduplicated_puts"], 1)
        memory.get("x")
        self.assertEqual(memory.metadata("x")["tier"], "hot")
        self.assertEqual(memory.metadata("x")["accesses"], 3)

    def test_replacement_invalidates_old_payload_and_delete(self):
        memory = AdaptiveMemory(100)
        memory.put("x", b"old")
        memory.put("x", b"new")
        self.assertEqual(memory.get("x"), b"new")
        self.assertTrue(memory.delete("x"))
        self.assertIsNone(memory.get("x"))
        self.assertFalse(memory.delete("x"))

    def test_persistence_survives_new_instance_and_compaction(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cold.jsonl"
            first = AdaptiveMemory(4, cold_store=path)
            first.put("a", b"abcd")
            first.put("b", b"efgh")
            second = AdaptiveMemory(4, cold_store=path)
            self.assertEqual(second.get("a"), b"abcd")
            second.compact()
            self.assertTrue(path.exists())

    def test_single_payload_over_budget_is_rejected(self):
        memory = AdaptiveMemory(3)
        with self.assertRaises(MemoryError):
            memory.put("large", b"1234")

    def test_policy_comparison_exposes_three_distinct_strategies(self):
        self.assertEqual(
            MemoryPolicyComparison.names(),
            ("unbounded_lru", "bounded_lru", "frequency_aware"),
        )
        for name in MemoryPolicyComparison.names():
            self.assertIsInstance(MemoryPolicyComparison.build(name, 64), AdaptiveMemory)


class IncrementalPatternLearnerTests(unittest.TestCase):
    def test_counts_and_next_prediction_update_incrementally(self):
        learner = IncrementalPatternLearner()
        learner.observe("query", "a")
        learner.observe("query", "b")
        learner.observe("query", "a")
        learner.observe("query", "c")
        learner.observe("query", "a")
        learner.observe("query", "c")
        learner.observe("update", "c")
        self.assertEqual(learner.events_seen, 7)
        self.assertEqual(learner.key_frequency("a"), 3)
        self.assertEqual(learner.kind_frequency("query"), 6)
        self.assertEqual(learner.predict_next("query", "a")[0], (PatternEvent("query", "c"), 2))
        self.assertEqual(learner.transition_frequency(PatternEvent("query", "a"), PatternEvent("query", "b")), 1)

    def test_transition_cardinality_is_bounded(self):
        learner = IncrementalPatternLearner(max_transition_targets=2)
        for key in ("a", "b", "c", "d", "e"):
            learner.observe("query", key)
        self.assertLessEqual(learner.stats()["transition_edges"], 2 * learner.stats()["transition_sources"])

    def test_invalid_events_are_rejected(self):
        learner = IncrementalPatternLearner()
        with self.assertRaises(ValueError): learner.observe("", "x")
        with self.assertRaises(ValueError): learner.observe("query", "")
        with self.assertRaises(ValueError): learner.hot_keys(0)


if __name__ == "__main__":
    unittest.main()
