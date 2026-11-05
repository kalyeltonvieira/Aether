import unittest

from aether_dependencies import DependencyTracker
from aether_inference import (
    InferenceEngine,
    InferenceLimits,
    Pattern,
    Rule,
)
from aether_knowledge import KnowledgeStore, Provenance
from aether_reasoner import KnowledgeReasoner


class Phase8ReasoningTests(unittest.TestCase):
    def test_two_independent_proofs_survive_removal_of_one_support(self):
        store = KnowledgeStore()
        for entity in ("b", "c", "d", "e", "target"):
            store.add_entity(entity)
        first, _ = store.add_fact("b", "supports", "c", provenance=Provenance("source-bc"))
        second, _ = store.add_fact("d", "supports", "e", provenance=Provenance("source-de"))
        rules = [
            Rule("via-bc", (Pattern("b", "supports", "c"),), Pattern("target", "ready", True)),
            Rule("via-de", (Pattern("d", "supports", "e"),), Pattern("target", "ready", True)),
        ]
        engine = InferenceEngine(store, rules)
        result = engine.infer()
        target = result.by_key(("target", "ready", True))
        self.assertIsNotNone(target)
        self.assertEqual({proof.rule_id for proof in target.proofs}, {"via-bc", "via-de"})
        explanation = engine.explain_all(result, target.key)[0]
        self.assertEqual(len(explanation.proofs), 2)
        support_sources = {
            node.provenance.source
            for branch in explanation.proofs
            for node in branch.supports
            if node.provenance is not None
        }
        self.assertEqual(support_sources, {"source-bc", "source-de"})

        tracker = DependencyTracker(result)
        first_removal = tracker.invalidate({first.fact_id})
        remaining = next(f for f in tracker.active if f.key == target.key)
        self.assertEqual([proof.rule_id for proof in remaining.proofs], ["via-de"])
        self.assertEqual(first_removal.conclusions_invalidated, 0)
        self.assertEqual(first_removal.proofs_invalidated, 1)
        self.assertEqual(first_removal.conclusions_preserved_by_alternative, 1)

        second_removal = tracker.invalidate({second.fact_id})
        self.assertNotIn(target.key, {fact.key for fact in tracker.active})
        self.assertEqual(second_removal.conclusions_invalidated, 1)

    def test_open_query_enumerates_bindings_and_derivation_explanations(self):
        store = KnowledgeStore()
        for entity in ("a", "b", "c", "d"):
            store.add_entity(entity)
        provenance = Provenance("edge-fixture", evidence_type="fixture")
        store.add_fact("a", "edge", "b", provenance=provenance)
        store.add_fact("b", "edge", "c", provenance=provenance)
        store.add_fact("c", "edge", "d", provenance=provenance)
        direct = Rule(
            "direct-reach",
            (Pattern("?x", "edge", "?y"),),
            Pattern("?x", "reach", "?y"),
        )
        transitive = Rule(
            "transitive-reach",
            (Pattern("?x", "reach", "?y"), Pattern("?y", "edge", "?z")),
            Pattern("?x", "reach", "?z"),
        )
        engine = InferenceEngine(store, [direct, transitive])
        result = engine.query(Pattern("?x", "reach", "?y"))
        self.assertTrue(result.complete)
        pairs = {(s.binding_map()["?x"], s.binding_map()["?y"]) for s in result.solutions}
        self.assertEqual(pairs, {
            ("a", "b"), ("a", "c"), ("a", "d"),
            ("b", "c"), ("b", "d"), ("c", "d"),
        })
        a_to_d = next(s for s in result.solutions if s.binding_map() == {"?x": "a", "?y": "d"})
        self.assertEqual(len(a_to_d.proofs), 1)
        self.assertTrue(a_to_d.explanation.proofs)
        base_sources = {
            node.provenance.source
            for proof in a_to_d.explanation.proofs
            for node in proof.supports
            if node.provenance is not None
        }
        self.assertEqual(base_sources, {"edge-fixture"})

    def test_repeated_variables_require_typed_equality(self):
        store = KnowledgeStore()
        store.add_entity("a")
        store.add_entity("b")
        store.add_fact("a", "same", "a")
        store.add_fact("a", "same", "b")
        store.add_fact("b", "same", "b")
        result = InferenceEngine(store).query(Pattern("?x", "same", "?x"))
        self.assertTrue(result.complete)
        self.assertEqual(
            {solution.binding_map()["?x"] for solution in result.solutions},
            {"a", "b"},
        )

        typed = KnowledgeStore()
        typed.add_entity("v")
        typed.add_fact("v", "value", True)
        typed.add_fact("v", "value", 1)
        typed_result = InferenceEngine(typed).query(Pattern("v", "value", "?x"))
        self.assertEqual({type(s.binding_map()["?x"]) for s in typed_result.solutions}, {bool, int})

    def test_result_limit_and_empty_query_completeness_are_explicit(self):
        store = KnowledgeStore()
        for entity in ("a", "b", "c"):
            store.add_entity(entity)
        store.add_fact("a", "edge", "b")
        store.add_fact("b", "edge", "c")
        engine = InferenceEngine(store)
        limited = engine.query(Pattern("?x", "edge", "?y"), max_results=1)
        self.assertEqual(len(limited.solutions), 1)
        self.assertFalse(limited.complete)
        self.assertEqual(limited.stop_reason, "max_results")
        exact = engine.query(Pattern("a", "edge", "b"), max_results=1)
        self.assertEqual(len(exact.solutions), 1)
        self.assertTrue(exact.complete)
        empty = engine.query(Pattern("?x", "missing", "?y"))
        self.assertEqual(empty.solutions, ())
        self.assertTrue(empty.complete)

    def test_query_does_not_report_partial_inference_as_complete(self):
        store = KnowledgeStore()
        for entity in ("a", "b", "c"):
            store.add_entity(entity)
        store.add_fact("a", "edge", "b")
        store.add_fact("b", "edge", "c")
        rule = Rule(
            "transitive",
            (Pattern("?x", "edge", "?y"), Pattern("?y", "edge", "?z")),
            Pattern("?x", "reach", "?z"),
        )
        result = InferenceEngine(store, [rule]).query(
            Pattern("?x", "reach", "?y"),
            InferenceLimits(max_depth=1, max_operations=1, max_conclusions=10),
        )
        self.assertFalse(result.complete)
        self.assertIsNotNone(result.stop_reason)

    def test_rule_revisions_are_versioned_and_enabled_state_is_explicit(self):
        rule = Rule("r", (Pattern("?x", "edge", "?y"),), Pattern("?x", "reach", "?y"))
        engine = InferenceEngine(KnowledgeStore(), [rule])
        version = engine.rules_version
        revised = engine.set_rule_enabled("r", False)
        self.assertFalse(revised.enabled)
        self.assertEqual(revised.revision, 2)
        self.assertGreater(engine.rules_version, version)
        self.assertNotEqual(engine.rules_fingerprint[0], ("r", 1, True, (), ()))
        with self.assertRaises(ValueError):
            engine.add_rule(rule)

    def test_reasoner_rule_lifecycle_requires_recompute_before_current_conclusions(self):
        store = KnowledgeStore()
        store.add_entity("a")
        store.add_entity("b")
        store.add_fact("a", "edge", "b", provenance=Provenance("source"))
        initial = Rule("copy", (Pattern("?x", "edge", "?y"),), Pattern("?x", "reach", "?y"))
        reasoner = KnowledgeReasoner(store, [initial])
        self.assertTrue(reasoner.recompute().complete_for_current_store)
        self.assertEqual(len(reasoner.conclusions()), 1)

        changed = Rule("copy", (Pattern("?x", "edge", "?y"),), Pattern("?x", "connected", "?y"))
        revised = reasoner.replace_rule("copy", changed)
        self.assertEqual(revised.revision, 2)
        self.assertFalse(reasoner.state.complete_for_current_store)
        with self.assertRaises(RuntimeError):
            reasoner.conclusions()
        recomputed = reasoner.recompute()
        self.assertTrue(recomputed.complete_for_current_store)
        self.assertEqual([fact.predicate for fact in reasoner.conclusions()], ["connected"])

        reasoner.set_rule_enabled("copy", False)
        self.assertFalse(reasoner.state.complete_for_current_store)
        self.assertEqual(reasoner.recompute().result.conclusions, ())
        reasoner.set_rule_enabled("copy", True)
        self.assertEqual(len(reasoner.recompute().result.conclusions), 1)
        reasoner.remove_rule("copy")
        self.assertFalse(reasoner.state.complete_for_current_store)
        self.assertEqual(reasoner.recompute().result.conclusions, ())


if __name__ == "__main__":
    unittest.main()
