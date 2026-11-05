import unittest

from aether.reasoning.inference import InferenceEngine, InferenceLimits, Pattern, Rule
from aether.core.knowledge.store import KnowledgeStore, Provenance


class InferenceEngineTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for entity in ("a", "b", "c", "d"):
            self.store.add_entity(entity)
        self.store.add_fact("a", "connected", "b", provenance=Provenance("fixture"))
        self.store.add_fact("b", "connected", "c", provenance=Provenance("fixture"))
        self.store.add_fact("c", "connected", "d", provenance=Provenance("fixture"))
        self.rule = Rule(
            "transitive-connected",
            (
                Pattern("?x", "connected", "?y"),
                Pattern("?y", "connected", "?z"),
            ),
            Pattern("?x", "connected", "?z"),
        )

    def test_one_and_multiple_step_transitive_inference(self):
        result = InferenceEngine(self.store, [self.rule]).infer()
        keys = {fact.key for fact in result.conclusions}
        self.assertIn(("a", "connected", "c"), keys)
        self.assertIn(("a", "connected", "d"), keys)
        self.assertIn(("b", "connected", "d"), keys)
        self.assertTrue(result.complete)
        self.assertEqual(result.max_depth_reached, 3)

    def test_conclusion_has_rule_depth_and_supports(self):
        result = InferenceEngine(self.store, [self.rule]).infer()
        fact = result.by_key(("a", "connected", "c"))
        self.assertIsNotNone(fact)
        self.assertEqual(fact.rule_id, "transitive-connected")
        self.assertEqual(fact.depth, 1)
        self.assertEqual(len(fact.supports), 2)
        self.assertEqual(len(InferenceEngine.explain(result, fact.key)), 1)

    def test_derived_fact_can_support_next_depth_and_explanation_is_compact(self):
        bridge = Rule(
            "reachable-to-related",
            (Pattern("?x", "connected", "?y"),),
            Pattern("?x", "related", "?y"),
        )
        result = InferenceEngine(self.store, [self.rule, bridge]).infer()
        target = result.by_key(("a", "related", "c"))
        self.assertIsNotNone(target)
        self.assertEqual(target.depth, 2)
        explanation = InferenceEngine.explain(result, target.key)
        self.assertEqual([item.key for item in explanation], [("a", "related", "c"), ("a", "connected", "c")])

    def test_cycles_terminate_and_do_not_duplicate_conclusions(self):
        cyclic = Rule("symmetric", (Pattern("?x", "connected", "?y"),), Pattern("?y", "connected", "?x"))
        result = InferenceEngine(self.store, [cyclic]).infer(InferenceLimits(max_depth=100, max_operations=1000, max_conclusions=100))
        self.assertLessEqual(len(result.conclusions), 6)
        self.assertEqual(len({fact.key for fact in result.conclusions}), len(result.conclusions))

    def test_limits_return_incomplete_state_without_claiming_completion(self):
        result = InferenceEngine(self.store, [self.rule]).infer(InferenceLimits(max_depth=1, max_operations=1, max_conclusions=100))
        self.assertFalse(result.complete)
        self.assertIn(result.stop_reason, {"max_operations", "max_depth"})

    def test_missing_variables_and_invalid_rules_are_rejected(self):
        with self.assertRaises(ValueError):
            Rule("bad", (Pattern("?x", "connected", "?y"),), Pattern("?x", "reachable", "?z"))
        with self.assertRaises(ValueError):
            Rule("empty", (), Pattern("a", "x", "b"))

    def test_empty_or_negative_query_remains_undetermined(self):
        result = InferenceEngine(self.store, [self.rule]).infer()
        self.assertIsNone(result.by_key(("d", "connected", "a")))
        self.assertEqual(InferenceEngine.explain(result, ("d", "connected", "a")), ())


if __name__ == "__main__":
    unittest.main()
