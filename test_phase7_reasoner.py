import unittest

from aether_inference import Pattern, Rule
from aether_knowledge import KnowledgeStore, Provenance
from aether_reasoner import KnowledgeReasoner


class KnowledgeReasonerTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for entity in ("a", "b", "c"):
            self.store.add_entity(entity)
        source = Provenance("fixture")
        self.first, _ = self.store.add_fact("a", "p", "b", provenance=source)
        self.second, _ = self.store.add_fact("b", "p", "c", provenance=source)
        self.rule = Rule("transitive", (Pattern("?x", "p", "?y"), Pattern("?y", "p", "?z")), Pattern("?x", "p", "?z"))
        self.reasoner = KnowledgeReasoner(self.store, [self.rule])

    def test_recompute_produces_complete_state(self):
        state = self.reasoner.recompute()
        self.assertTrue(state.complete_for_current_store)
        self.assertIn(("a", "p", "c"), {fact.key for fact in state.result.conclusions})

    def test_new_fact_is_propagated_by_incremental_agenda(self):
        self.reasoner.recompute()
        self.reasoner.add_entity("d")
        fact, inserted = self.reasoner.add_fact("c", "p", "d", provenance=Provenance("fixture"))
        self.assertTrue(inserted)
        self.assertTrue(self.reasoner.state.complete_for_current_store)
        self.assertIn(("a", "p", "d"), {item.key for item in self.reasoner.conclusions()})

    def test_external_store_mutation_requires_recompute_before_reading_conclusions(self):
        self.reasoner.recompute()
        self.store.add_fact("c", "p", "a", provenance=Provenance("external"))

        state = self.reasoner.state
        self.assertFalse(state.complete_for_current_store)
        self.assertEqual(state.stale_reason, "external_store_mutation_requires_recompute")
        with self.assertRaisesRegex(RuntimeError, "call recompute"):
            self.reasoner.conclusions()

        state = self.reasoner.recompute()
        self.assertTrue(state.complete_for_current_store)
        self.assertIn(("a", "p", "a"), {item.key for item in self.reasoner.conclusions()})

    def test_entity_updates_through_reasoner_preserve_complete_inference_state(self):
        self.reasoner.recompute()
        self.reasoner.add_entity("d", {"kind": "person"})
        state = self.reasoner.state
        self.assertTrue(state.complete_for_current_store)
        self.assertIsNone(state.stale_reason)

    def test_removal_invalidates_only_dependent_conclusions_and_marks_alternatives_uncertain(self):
        self.reasoner.recompute()
        stats = self.reasoner.remove_fact(self.first.fact_id)
        self.assertEqual(stats.conclusions_invalidated, 1)
        self.assertFalse(self.reasoner.state.complete_for_current_store)
        self.assertNotIn(("a", "p", "c"), {item.key for item in self.reasoner.conclusions()})
        self.assertEqual(self.store.query(subject="b")[0].object, "c")

    def test_removal_before_first_inference_is_direct(self):
        stats = self.reasoner.remove_fact(self.first.fact_id)
        self.assertIsNone(stats)
        self.assertEqual(self.store.query(subject="a"), ())


if __name__ == "__main__":
    unittest.main()
