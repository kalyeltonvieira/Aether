import unittest

from aether_inference import Pattern, Rule
from aether_knowledge import KnowledgeStore, Provenance
from aether_reasoning_controller import AdaptiveReasoningController
from aether_backward import BackwardInference
from aether_hybrid import HybridInference


class AdaptiveControllerTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for entity in ("a", "b", "c"):
            self.store.add_entity(entity)
        source = Provenance("fixture")
        self.store.add_fact("a", "link", "b", provenance=source)
        self.store.add_fact("b", "link", "c", provenance=source)
        self.rule = Rule("transitive", (Pattern("?x", "link", "?y"), Pattern("?y", "link", "?z")), Pattern("?x", "link", "?z"))

    def test_ground_query_with_unbound_rule_variables_avoids_incomplete_backward(self):
        controller = AdaptiveReasoningController(self.store, [self.rule])
        result = controller.prove(("a", "link", "c"))
        self.assertIn(result.strategy, {"hybrid", "forward"})
        self.assertTrue(result.proven)
        self.assertTrue(result.complete)
        self.assertGreaterEqual(result.decision_ns, 0)
        self.assertGreater(result.execution_ns, 0)

    def test_open_query_uses_forward_closure(self):
        controller = AdaptiveReasoningController(self.store, [self.rule])
        result = controller.prove(("a", "link", "?z"))
        self.assertEqual(result.strategy, "forward")
        self.assertTrue(result.complete)
        self.assertTrue(result.proven)
        self.assertTrue(result.solutions)
        self.assertEqual(
            {solution.binding_map()["?z"] for solution in result.solutions},
            {"b", "c"},
        )
        self.assertEqual(result.features.free_variables, 1)

    def test_controller_records_observed_costs(self):
        projection = Rule(
            "projection",
            (Pattern("?x", "link", "?y"),),
            Pattern("?x", "emailed", "?y"),
        )
        controller = AdaptiveReasoningController(self.store, [projection])
        results = [controller.prove(("a", "emailed", "b")) for _ in range(3)]
        self.assertEqual(sum(controller.observations.values()), 3)
        self.assertEqual(set(controller.observations), {"backward", "hybrid", "forward"})
        self.assertEqual(controller.historical_queries, 3)
        self.assertTrue(all(result.features.historical_queries <= 2 for result in results))
        self.assertEqual(set(controller.estimated_cost_ns), {"backward", "hybrid", "forward"})
        self.assertEqual(AdaptiveReasoningController(self.store, [projection]).observations, {})

    def test_backward_and_hybrid_reject_open_goals_instead_of_returning_false_bindings(self):
        with self.assertRaisesRegex(ValueError, "ground goal"):
            BackwardInference(self.store, [self.rule]).prove(("a", "link", "?z"))
        with self.assertRaisesRegex(ValueError, "ground goal"):
            HybridInference(self.store, [self.rule]).prove(("a", "link", "?z"))

    def test_holdout_does_not_train_and_rule_change_resets_cost_history(self):
        projection = Rule(
            "projection",
            (Pattern("?x", "link", "?y"),),
            Pattern("?x", "emailed", "?y"),
        )
        controller = AdaptiveReasoningController(self.store, [projection])
        for _ in range(3):
            controller.prove(("a", "emailed", "b"))
        before = (controller.observations, controller.estimated_cost_ns)
        held_out = controller.prove(("a", "emailed", "b"), learn=False)
        self.assertTrue(held_out.complete)
        self.assertEqual((controller.observations, controller.estimated_cost_ns), before)
        self.assertEqual(controller.historical_queries, 4)

        changed = Rule(
            "projection",
            (Pattern("?x", "link", "?y"),),
            Pattern("?x", "connected", "?y"),
        )
        revised = controller.replace_rule("projection", changed)
        self.assertEqual(revised.revision, 2)
        self.assertEqual(controller.observations, {})
        self.assertEqual(controller.estimated_cost_ns, {})
        self.assertTrue(controller.prove(("a", "connected", "b")).proven)


if __name__ == "__main__":
    unittest.main()
