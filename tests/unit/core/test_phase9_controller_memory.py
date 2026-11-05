import unittest
from unittest.mock import patch

from aether.core.knowledge.store import KnowledgeStore
from aether.reasoning.controller import AdaptiveReasoningController


class ControllerMemoryAwarenessTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for index in range(30):
            self.store.add_entity(f"node-{index}")
            if index:
                self.store.add_fact(f"node-{index - 1}", "edge", f"node-{index}")

    @patch("aether.reasoning.controller.available_memory_bytes", return_value=1_000_000_000)
    @patch("aether.reasoning.controller.total_physical_memory_bytes", return_value=100_000_000_000)
    def test_real_memory_pressure_is_a_feature_and_affects_cost_prior(self, _total, _available):
        constrained = AdaptiveReasoningController(self.store)
        features = constrained._features(("node-0", "reach", "node-29"))
        self.assertEqual(features.memory_available_bytes, 1_000_000_000)
        self.assertEqual(features.memory_total_bytes, 100_000_000_000)
        self.assertAlmostEqual(features.memory_pressure, 0.99)
        constrained_costs = constrained._prior_costs(features)

        with patch("aether.reasoning.controller.available_memory_bytes", return_value=30_000_000_000):
            normal = AdaptiveReasoningController(self.store)
            normal_features = normal._features(("node-0", "reach", "node-29"))
        self.assertAlmostEqual(normal_features.memory_pressure, 0.7)
        normal_costs = normal._prior_costs(normal_features)

        self.assertGreater(constrained_costs["forward"], normal_costs["forward"])
        self.assertGreater(constrained_costs["hybrid"], normal_costs["hybrid"])
        self.assertNotEqual(
            constrained._feature_bucket(features),
            normal._feature_bucket(normal_features),
        )

    @patch("aether.reasoning.controller.available_memory_bytes", return_value=None)
    @patch("aether.reasoning.controller.total_physical_memory_bytes", return_value=None)
    def test_unavailable_memory_is_none_not_fabricated_as_zero(self, _total, _available):
        features = AdaptiveReasoningController(self.store)._features(("node-0", "edge", "node-1"))
        self.assertIsNone(features.memory_available_bytes)
        self.assertIsNone(features.memory_total_bytes)
        self.assertIsNone(features.memory_pressure)
        self.assertEqual(AdaptiveReasoningController._feature_bucket(features)[-1], "unknown")


if __name__ == "__main__":
    unittest.main()
