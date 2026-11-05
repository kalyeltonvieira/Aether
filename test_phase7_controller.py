import unittest

from aether_inference import Pattern, Rule
from aether_knowledge import KnowledgeStore, Provenance
from aether_reasoning_controller import AdaptiveReasoningController


class AdaptiveControllerTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for entity in ("a", "b", "c"):
            self.store.add_entity(entity)
        source = Provenance("fixture")
        self.store.add_fact("a", "link", "b", provenance=source)
        self.store.add_fact("b", "link", "c", provenance=source)
        self.rule = Rule("transitive", (Pattern("?x", "link", "?y"), Pattern("?y", "link", "?z")), Pattern("?x", "link", "?z"))

    def test_sparse_ground_query_starts_with_backward(self):
        controller = AdaptiveReasoningController(self.store, [self.rule])
        result = controller.prove(("a", "link", "c"))
        self.assertEqual(result.strategy, "backward")
        self.assertTrue(result.proven)
        self.assertGreaterEqual(result.decision_ns, 0)
        self.assertGreater(result.execution_ns, 0)

    def test_open_query_uses_forward_closure(self):
        controller = AdaptiveReasoningController(self.store, [self.rule])
        result = controller.prove(("a", "link", "?z"))
        self.assertEqual(result.strategy, "forward")
        self.assertTrue(result.complete)
        self.assertTrue(result.proven)

    def test_controller_records_observed_costs(self):
        controller = AdaptiveReasoningController(self.store, [self.rule])
        controller.prove(("a", "link", "c"))
        controller.prove(("a", "link", "c"))
        self.assertEqual(controller.observations["backward"], 2)
        self.assertIn("backward", controller.estimated_cost_ns)


if __name__ == "__main__":
    unittest.main()
