import random
import unittest

from aether.core.knowledge.store import KnowledgeStore
from aether.reasoning.controller import AdaptiveReasoningController
from aether.reasoning.inference import InferenceEngine, Pattern, Rule
from aether.reasoning.reasoner import KnowledgeReasoner


class SelectiveJoinPlannerTests(unittest.TestCase):
    def _selectivity_fixture(self, seed=0):
        rng = random.Random(seed)
        store = KnowledgeStore()
        for entity in [*(f"source-{i}" for i in range(100)), "alice", "key", "bob"]:
            store.add_entity(entity)
        insertion_order = list(range(100))
        rng.shuffle(insertion_order)
        for index in insertion_order:
            store.add_fact(f"source-{index}", "broad", f"sink-{index}")
        broad, _ = store.add_fact("alice", "broad", "bob")
        narrow, _ = store.add_fact("alice", "narrow", "key")
        target, _ = store.add_fact("key", "target", "bob")
        rule = Rule(
            "selective-join",
            (
                Pattern("?x", "broad", "?y"),
                Pattern("?x", "narrow", "?z"),
                Pattern("?z", "target", "?y"),
            ),
            Pattern("?x", "reachable", "?y"),
        )
        return store, rule, (broad.fact_id, narrow.fact_id, target.fact_id)

    def test_selective_order_preserves_results_and_support_order_while_examining_less(self):
        store, rule, expected_supports = self._selectivity_fixture()
        fixed = InferenceEngine(store, [rule], join_planner="input")
        selective = InferenceEngine(store, [rule], join_planner="selective")
        fixed_result = fixed.infer()
        selective_result = selective.infer()

        self.assertEqual(selective_result.conclusions, fixed_result.conclusions)
        self.assertEqual(
            [fact.key for fact in selective_result.conclusions],
            [("alice", "reachable", "bob")],
        )
        self.assertEqual(selective_result.conclusions[0].proofs[0].supports, expected_supports)
        self.assertEqual(selective.last_join_plan.order, (1, 2, 0))
        self.assertEqual(selective.last_join_plan.candidate_estimates, (101, 1, 1))
        self.assertLess(selective_result.facts_examined, fixed_result.facts_examined)
        self.assertEqual(fixed.last_join_plan.order, (0, 1, 2))
        self.assertEqual(fixed.last_join_plan.candidate_estimates, ())

    def test_invalid_join_planner_is_rejected(self):
        store = KnowledgeStore()
        with self.assertRaisesRegex(ValueError, "join_planner"):
            InferenceEngine(store, join_planner="guess")

    def test_reasoner_and_controller_can_use_selective_planner(self):
        store, rule, _ = self._selectivity_fixture()
        reasoner = KnowledgeReasoner(store, [rule], join_planner="selective")
        self.assertTrue(reasoner.recompute().complete_for_current_store)
        self.assertEqual(reasoner._incremental.join_planner, "selective")
        reasoner.add_entity("new-key")
        reasoner.add_fact("alice", "narrow", "new-key")
        reasoner.add_fact("new-key", "target", "bob")
        self.assertIn(("alice", "reachable", "bob"), [fact.key for fact in reasoner.conclusions()])

        controller = AdaptiveReasoningController(store, [rule], join_planner="selective")
        result = controller.prove(("?x", "reachable", "?y"), learn=False)
        self.assertTrue(result.complete)
        self.assertIn({"?x": "alice", "?y": "bob"}, [solution.binding_map() for solution in result.solutions])

    def test_randomized_fixtures_match_for_thirty_seeds(self):
        for seed in range(30):
            with self.subTest(seed=seed):
                store, rule, _ = self._selectivity_fixture(seed)
                fixed = InferenceEngine(store, [rule], join_planner="input").infer()
                selective = InferenceEngine(store, [rule], join_planner="selective").infer()
                self.assertEqual(selective.conclusions, fixed.conclusions)
                self.assertEqual(selective.complete, fixed.complete)


if __name__ == "__main__":
    unittest.main()
