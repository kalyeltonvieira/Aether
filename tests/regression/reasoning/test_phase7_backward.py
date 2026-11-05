import unittest

from aether.reasoning.backward import BackwardInference, BackwardLimits
from aether.reasoning.inference import Pattern, Rule
from aether.core.knowledge.store import KnowledgeStore, Provenance


class BackwardInferenceTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for entity in ("a", "b", "c", "d"):
            self.store.add_entity(entity)
        source = Provenance("fixture")
        self.store.add_fact("a", "link", "b", provenance=source)
        self.store.add_fact("b", "link", "c", provenance=source)
        self.store.add_fact("c", "link", "d", provenance=source)
        self.rule = Rule("transitive", (Pattern("?x", "link", "?y"), Pattern("?y", "link", "?z")), Pattern("?x", "link", "?z"))

    def test_direct_fact_is_proven_without_rules(self):
        proof = BackwardInference(self.store).prove(("a", "link", "b"))
        self.assertTrue(proof.proven)
        self.assertEqual(proof.rule_id, None)
        self.assertEqual(proof.supports, (1,))

    def test_query_driven_transitive_proof(self):
        proof = BackwardInference(self.store, [self.rule]).prove(("a", "link", "c"))
        self.assertTrue(proof.proven)
        self.assertEqual(proof.rule_id, "transitive")
        self.assertEqual(set(proof.supports), {1, 2})

    def test_search_does_not_stop_at_first_failing_candidate(self):
        self.store.add_entity("dead")
        self.store.add_fact("a", "link", "dead", provenance=Provenance("fixture"))
        proof = BackwardInference(self.store, [self.rule]).prove(("a", "link", "c"))
        self.assertTrue(proof.proven)
        self.assertEqual(set(proof.supports), {1, 2})

    def test_unproven_goal_is_not_invented(self):
        proof = BackwardInference(self.store, [self.rule]).prove(("d", "link", "a"))
        self.assertFalse(proof.proven)
        self.assertFalse(proof.complete)
        self.assertEqual(proof.stop_reason, "unbound_variables")

    def test_depth_limit_is_explicit(self):
        proof = BackwardInference(self.store, [self.rule]).prove(("a", "link", "d"), BackwardLimits(max_depth=1))
        self.assertFalse(proof.proven)
        self.assertFalse(proof.complete)
        self.assertEqual(proof.stop_reason, "max_depth")

    def test_operation_limit_is_explicit(self):
        proof = BackwardInference(self.store, [self.rule]).prove(("a", "link", "d"), BackwardLimits(max_operations=1))
        self.assertFalse(proof.proven)
        self.assertFalse(proof.complete)
        self.assertEqual(proof.stop_reason, "max_operations")


if __name__ == "__main__":
    unittest.main()
