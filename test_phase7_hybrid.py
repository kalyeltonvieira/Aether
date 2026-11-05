import unittest

from aether_hybrid import HybridInference
from aether_inference import InferenceLimits, Pattern, Rule
from aether_knowledge import KnowledgeStore, Provenance


class HybridInferenceTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for entity in ("a", "b", "c"):
            self.store.add_entity(entity)
        source = Provenance("fixture")
        self.store.add_fact("a", "link", "b", provenance=source)
        self.store.add_fact("b", "link", "c", provenance=source)
        self.rule = Rule("transitive", (Pattern("?x", "link", "?y"), Pattern("?y", "link", "?z")), Pattern("?x", "link", "?z"))

    def test_hybrid_uses_backward_for_ground_query(self):
        result = HybridInference(self.store, [self.rule]).prove(("a", "link", "c"))
        self.assertTrue(result.proven)
        self.assertEqual(result.strategy, "backward")

    def test_hybrid_uses_forward_fallback_when_backward_is_limited(self):
        result = HybridInference(self.store, [self.rule]).prove(("a", "link", "c"), backward_limits=__import__("aether_backward", fromlist=["BackwardLimits"]).BackwardLimits(max_operations=1), forward_limits=InferenceLimits(max_operations=1000))
        self.assertFalse(result.proven)
        self.assertFalse(result.complete)
        self.assertEqual(result.strategy, "backward_limited")

    def test_unknown_goal_falls_back_to_complete_forward_search(self):
        result = HybridInference(self.store, [self.rule]).prove(("c", "link", "a"))
        self.assertFalse(result.proven)
        self.assertTrue(result.complete)
        self.assertEqual(result.strategy, "forward_fallback")


if __name__ == "__main__":
    unittest.main()
