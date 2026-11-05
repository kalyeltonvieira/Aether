import unittest

from aether_inference import InferenceEngine, InferenceLimits, Pattern, Rule
from aether_incremental import IncrementalInference
from aether_knowledge import KnowledgeStore, Provenance


class IncrementalInferenceTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for entity in ("a", "b", "c", "d", "x", "y"):
            self.store.add_entity(entity)
        source = Provenance("fixture")
        self.store.add_fact("a", "link", "b", provenance=source)
        self.rule = Rule("transitive", (Pattern("?x", "link", "?y"), Pattern("?y", "link", "?z")), Pattern("?x", "link", "?z"))

    def test_inserted_fact_is_propagated_without_reemitting_old_conclusions(self):
        incremental = IncrementalInference(self.store, [self.rule])
        initial = incremental.initialize(InferenceLimits(max_depth=8, max_operations=10000, max_conclusions=1000))
        self.assertEqual(initial.conclusions, ())
        source = Provenance("fixture")
        fact, update = incremental.add_fact("b", "link", "c", provenance=source)
        self.assertTrue(update.inserted)
        self.assertEqual([item.key for item in update.new_conclusions], [("a", "link", "c")])
        self.assertTrue(update.complete)
        self.assertEqual(incremental.result().by_key(("a", "link", "c")).supports, (1, fact.fact_id))

    def test_multiple_insertions_match_full_oracle(self):
        incremental = IncrementalInference(self.store, [self.rule])
        incremental.initialize()
        source = Provenance("fixture")
        incremental.add_fact("b", "link", "c", provenance=source)
        incremental.add_fact("c", "link", "d", provenance=source)
        actual = {fact.key for fact in incremental.result().conclusions}
        oracle = InferenceEngine(self.store, [self.rule]).infer()
        expected = {fact.key for fact in oracle.conclusions}
        self.assertEqual(actual, expected)
        self.assertEqual(actual, {("a", "link", "c"), ("a", "link", "d"), ("b", "link", "d")})

    def test_duplicate_insertion_has_no_delta(self):
        incremental = IncrementalInference(self.store, [self.rule])
        incremental.initialize()
        _, update = incremental.add_fact("a", "link", "b", provenance=Provenance("duplicate"))
        self.assertFalse(update.inserted)
        self.assertEqual(update.new_conclusions, ())

    def test_limits_are_reported_and_no_false_completion(self):
        incremental = IncrementalInference(self.store, [self.rule])
        incremental.initialize(InferenceLimits(max_depth=1, max_operations=1, max_conclusions=10))
        _, update = incremental.add_fact("b", "link", "c", provenance=Provenance("fixture"))
        self.assertFalse(update.complete)
        self.assertIn(update.stop_reason, {"max_operations", "max_depth"})


if __name__ == "__main__":
    unittest.main()
