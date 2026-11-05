import unittest

from aether.reasoning.dependencies import DependencyTracker
from aether.reasoning.inference import InferenceEngine, Pattern, Rule
from aether.core.knowledge.store import KnowledgeStore, Provenance


class DependencyTrackerTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for entity in ("a", "b", "c", "x", "y"):
            self.store.add_entity(entity)
        source = Provenance("fixture")
        self.first, _ = self.store.add_fact("a", "p", "b", provenance=source)
        self.second, _ = self.store.add_fact("b", "p", "c", provenance=source)
        self.independent, _ = self.store.add_fact("x", "p", "y", provenance=source)
        rule = Rule("transitive", (Pattern("?x", "p", "?y"), Pattern("?y", "p", "?z")), Pattern("?x", "p", "?z"))
        self.result = InferenceEngine(self.store, (rule,)).infer()

    def test_invalidation_propagates_through_derived_supports(self):
        tracker = DependencyTracker(self.result)
        stats = tracker.invalidate({self.first.fact_id})
        self.assertGreaterEqual(stats.conclusions_invalidated, 1)
        self.assertNotIn(("a", "p", "c"), {fact.key for fact in tracker.active})
        self.assertEqual(stats.conclusions_visited, stats.conclusions_invalidated + 1)

    def test_unrelated_support_does_not_invalidate_other_branch(self):
        tracker = DependencyTracker(self.result)
        stats = tracker.invalidate({self.independent.fact_id})
        self.assertEqual(stats.conclusions_invalidated, 0)
        self.assertEqual(len(tracker.active), len(self.result.conclusions))

    def test_derived_support_invalidation_is_supported(self):
        tracker = DependencyTracker(self.result)
        derived = self.result.by_key(("a", "p", "c"))
        self.assertIsNotNone(derived)
        stats = tracker.invalidate(set(), {derived.key})
        self.assertEqual(stats.conclusions_invalidated, 1)
        self.assertNotIn(derived.key, {fact.key for fact in tracker.active})

    def test_new_conclusions_can_be_added_after_local_recomputation(self):
        tracker = DependencyTracker(self.result)
        tracker.invalidate({self.first.fact_id})
        derived = self.result.by_key(("a", "p", "c"))
        self.assertIsNotNone(derived)
        tracker.add((derived,))
        self.assertIn(derived.key, {fact.key for fact in tracker.active})

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(TypeError):
            DependencyTracker(object())
        with self.assertRaises(TypeError):
            DependencyTracker(self.result).invalidate({1}, ())


if __name__ == "__main__":
    unittest.main()
