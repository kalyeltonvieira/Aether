import unittest

from aether.memory.patterns import (
    DEFAULT_MAX_KINDS,
    DEFAULT_MAX_KEYS,
    DEFAULT_MAX_TRANSITION_SOURCES,
    IncrementalPatternLearner,
    PatternEvent,
)


class Phase9PatternLearnerTests(unittest.TestCase):
    def test_historical_counts_and_prediction_api_remain_compatible(self):
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
        self.assertEqual(
            learner.predict_next("query", "a")[0],
            (PatternEvent("query", "c"), 2),
        )
        self.assertEqual(
            learner.transition_frequency(
                PatternEvent("query", "a"), PatternEvent("query", "b")
            ),
            1,
        )

    def test_default_limits_are_bounded_and_reported(self):
        learner = IncrementalPatternLearner()
        stats = learner.stats()
        self.assertEqual(stats["max_keys"], DEFAULT_MAX_KEYS)
        self.assertEqual(stats["max_kinds"], DEFAULT_MAX_KINDS)
        self.assertEqual(stats["max_transition_sources"], DEFAULT_MAX_TRANSITION_SOURCES)
        self.assertGreaterEqual(stats["max_transition_targets"], 1)

    def test_all_global_resident_sets_stay_within_configured_limits(self):
        learner = IncrementalPatternLearner(
            max_keys=7,
            max_kinds=3,
            max_transition_sources=5,
            max_transition_targets=4,
        )
        for index in range(5000):
            learner.observe(f"kind-{index}", f"key-{index}")

        stats = learner.stats()
        self.assertEqual(stats["events_seen"], 5000)
        self.assertLessEqual(stats["distinct_keys"], 7)
        self.assertLessEqual(stats["distinct_kinds"], 3)
        self.assertLessEqual(stats["transition_sources"], 5)
        self.assertLessEqual(stats["transition_edges"], 5 * 4)
        self.assertGreater(stats["key_evictions"], 0)
        self.assertGreater(stats["kind_evictions"], 0)
        self.assertGreater(stats["transition_source_evictions"], 0)
        self.assertGreaterEqual(stats["evictions"], stats["key_evictions"])

    def test_eviction_victims_and_counts_are_deterministic(self):
        sequence = (
            ("kind", "b"),
            ("kind", "b"),
            ("kind", "a"),
            ("kind", "c"),
            ("other", "d"),
            ("third", "e"),
        )
        first = IncrementalPatternLearner(
            max_keys=2,
            max_kinds=2,
            max_transition_sources=2,
            max_transition_targets=1,
        )
        second = IncrementalPatternLearner(
            max_keys=2,
            max_kinds=2,
            max_transition_sources=2,
            max_transition_targets=1,
        )
        for event in sequence:
            first.observe(*event)
            second.observe(*event)

        self.assertEqual(first.stats(), second.stats())
        self.assertEqual(first.hot_keys(), second.hot_keys())
        self.assertEqual(first.predict_next("kind", "b"), second.predict_next("kind", "b"))
        self.assertEqual(first.key_frequency("b"), 2)
        self.assertEqual(first.key_frequency("a"), 0)
        self.assertEqual(first.stats()["key_evictions"], 3)
        self.assertEqual(first.stats()["kind_evictions"], 1)

    def test_evicted_frequency_is_not_presented_as_retained_history(self):
        learner = IncrementalPatternLearner(
            max_keys=1,
            max_kinds=1,
            max_transition_sources=1,
            max_transition_targets=1,
        )
        learner.observe("query", "first")
        learner.observe("query", "second")

        self.assertEqual(learner.key_frequency("first"), 0)
        self.assertEqual(learner.key_frequency("second"), 1)
        self.assertEqual(learner.events_seen, 2)
        self.assertNotIn("meaning", learner.stats())
        self.assertNotIn("truth", learner.stats())
        self.assertEqual(
            learner.predict_next("query", "first"),
            [(PatternEvent("query", "second"), 1)],
            "prediction reports only an observed operational transition; it is not a semantic claim",
        )

    def test_invalid_bounds_are_rejected(self):
        for field in (
            "max_keys",
            "max_kinds",
            "max_transition_sources",
            "max_transition_targets",
        ):
            with self.subTest(field=field):
                with self.assertRaises(TypeError):
                    IncrementalPatternLearner(**{field: True})
                with self.assertRaises(ValueError):
                    IncrementalPatternLearner(**{field: 0})

    def test_invalid_events_remain_rejected(self):
        learner = IncrementalPatternLearner()
        with self.assertRaises(ValueError):
            learner.observe("", "x")
        with self.assertRaises(ValueError):
            learner.observe("query", "")
        with self.assertRaises(ValueError):
            learner.hot_keys(0)


if __name__ == "__main__":
    unittest.main()
