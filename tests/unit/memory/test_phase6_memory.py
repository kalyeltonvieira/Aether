import tempfile
import unittest
from pathlib import Path

from aether.memory.adaptive_storage import AdaptiveMemory, MemoryPolicyComparison
from aether.memory.patterns import IncrementalPatternLearner, PatternEvent


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

    def test_delete_remains_deleted_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cold.sqlite3"
            memory = AdaptiveMemory(16, cold_store=path)
            memory.put("gone", b"payload")
            self.assertTrue(memory.delete("gone"))
            memory.close()

            recovered = AdaptiveMemory(16, cold_store=path)
            self.assertIsNone(recovered.get("gone"))
            self.assertNotIn("gone", recovered.keys())
            recovered.close()

    def test_replacement_is_durable_before_process_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cold.sqlite3"
            memory = AdaptiveMemory(16, cold_store=path)
            memory.put("x", b"old")
            memory.put("x", b"new")
            memory.close()

            recovered = AdaptiveMemory(16, cold_store=path)
            self.assertEqual(recovered.get("x"), b"new")
            recovered.close()

    def test_corrupt_cold_payload_is_detected_by_digest(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cold.sqlite3"
            memory = AdaptiveMemory(16, cold_store=path)
            memory.put("x", b"payload")
            memory.close()

            with sqlite3.connect(path) as database:
                database.execute(
                    "UPDATE cold_entries SET payload = ? WHERE key = ?",
                    (b"tampered", "x"),
                )
            recovered = AdaptiveMemory(16, cold_store=path)
            with self.assertRaisesRegex(RuntimeError, "corrupt cold-store record"):
                recovered.get("x")
            recovered.close()

    def test_legacy_jsonl_migrates_and_ignores_torn_final_append(self):
        import base64
        import hashlib
        import json

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cold.jsonl"
            payload = b"legacy-payload"
            record = {
                "op": "put",
                "key": "legacy",
                "digest": hashlib.sha256(payload).hexdigest(),
                "payload": base64.b64encode(payload).decode("ascii"),
                "accesses": 2,
                "created_ns": 123,
            }
            path.write_text(json.dumps(record) + "\n{\"op\":\"put\"", encoding="utf-8")
            memory = AdaptiveMemory(32, cold_store=path)
            self.assertEqual(memory.get("legacy"), payload)
            self.assertTrue(path.read_bytes().startswith(b"SQLite format 3\x00"))
            memory.close()

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
