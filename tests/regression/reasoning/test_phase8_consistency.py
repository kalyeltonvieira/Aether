import unittest

from aether_consistency import (
    ConsistencyValidator,
    IncompatibilityRule,
    KnowledgeStatus,
)
from aether_inference import InferenceEngine, Pattern, Rule, InferenceLimits
from aether_knowledge import KnowledgeStore, Provenance


class Phase8ConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for entity in ("a", "b", "c"):
            self.store.add_entity(entity)
        self.validator = ConsistencyValidator(self.store)

    def test_explicit_derived_unknown_and_insufficient_evidence_are_distinct(self):
        self.store.add_fact("a", "documented", "b", provenance=Provenance("catalogue"))
        self.store.add_fact("a", "undocumented", "b")
        self.store.add_fact("a", "edge", "b", provenance=Provenance("edge-source"))
        rule = Rule(
            "derive-edge",
            (Pattern("?x", "edge", "?y"),),
            Pattern("?x", "linked", "?y"),
        )
        inference = InferenceEngine(self.store, [rule]).infer()

        explicit = self.validator.assess(("a", "documented", "b"), inference=inference)
        weak = self.validator.assess(("a", "undocumented", "b"), inference=inference)
        derived = self.validator.assess(("a", "linked", "b"), inference=inference)
        unknown = self.validator.assess(("a", "missing", "b"), inference=inference)

        self.assertEqual(explicit.status, KnowledgeStatus.EXPLICIT)
        self.assertTrue(explicit.is_explicit)
        self.assertEqual(weak.status, KnowledgeStatus.INSUFFICIENT_EVIDENCE)
        self.assertTrue(weak.is_explicit)
        self.assertEqual(derived.status, KnowledgeStatus.DERIVED)
        self.assertTrue(derived.is_derived)
        self.assertEqual(unknown.status, KnowledgeStatus.UNKNOWN)
        self.assertTrue(unknown.complete)
        self.assertEqual(unknown.note.count("not"), 1)

    def test_incomplete_inference_yields_insufficient_evidence_not_unknown(self):
        self.store.add_fact("a", "edge", "b", provenance=Provenance("edge-source"))
        rule = Rule("copy", (Pattern("?x", "edge", "?y"),), Pattern("?x", "linked", "?y"))
        incomplete = InferenceEngine(self.store, [rule]).infer(
            InferenceLimits(max_depth=1, max_operations=1, max_conclusions=10)
        )
        self.assertFalse(incomplete.complete)
        assessment = self.validator.assess(("c", "linked", "a"), inference=incomplete)
        self.assertEqual(assessment.status, KnowledgeStatus.INSUFFICIENT_EVIDENCE)
        self.assertFalse(assessment.complete)

    def test_declared_conflict_is_preserved_and_resolution_is_a_separate_record(self):
        alive, _ = self.store.add_fact("a", "alive", True, provenance=Provenance("source-a"))
        dead, _ = self.store.add_fact("a", "dead", True, provenance=Provenance("source-b"))
        rule = IncompatibilityRule("alive", "dead", ((True, True),))
        assessment = self.validator.assess(("a", "alive", True), incompatibilities=(rule,))
        self.assertEqual(assessment.status, KnowledgeStatus.CONTRADICTED)
        self.assertEqual(assessment.explicit_fact_ids, (alive.fact_id,))
        self.assertEqual(assessment.conflicting_fact_ids, (dead.fact_id,))
        self.assertTrue(assessment.evidence_sufficient)
        resolution = self.validator.record_resolution(
            (alive.fact_id, dead.fact_id), (alive.fact_id,),
            reason="external review chose the verified record",
            resolved_by="reviewer-1",
        )
        after = self.validator.assess(("a", "alive", True), incompatibilities=(rule,))
        self.assertEqual(after.status, KnowledgeStatus.CONTRADICTED)
        self.assertEqual(after.resolution, resolution)
        self.assertEqual(len(self.store.query(subject="a")), 2)
        report = self.validator.validate(incompatibilities=(rule,))
        self.assertIn(resolution, report.resolutions)
        self.assertIn("incompatible_facts", {issue.code for issue in report.issues})

    def test_rule_consequents_are_not_contradictory_without_declared_incompatibility(self):
        first = Rule("r1", (Pattern("?x", "p", "?y"),), Pattern("?x", "q", "?y"))
        second = Rule("r2", (Pattern("?x", "p", "?y"),), Pattern("?x", "other_q", "?y"))
        report = self.validator.validate(rules=(first, second))
        self.assertNotIn("contradictory_rules", {issue.code for issue in report.issues})
        declared = self.validator.validate(
            rules=(first, second),
            incompatibilities=(IncompatibilityRule("q", "other_q"),),
        )
        self.assertIn("contradictory_rules", {issue.code for issue in declared.issues})

    def test_incompatibility_value_pairs_use_typed_scalar_identity(self):
        self.store.add_fact("a", "boolean", True, provenance=Provenance("one"))
        self.store.add_fact("a", "integer", 1, provenance=Provenance("two"))
        strict = IncompatibilityRule("boolean", "integer", ((True, 1),))
        self.assertEqual(
            self.validator.assess(("a", "boolean", True), incompatibilities=(strict,)).status,
            KnowledgeStatus.CONTRADICTED,
        )
        not_matching = IncompatibilityRule("boolean", "integer", ((1, True),))
        self.assertEqual(
            self.validator.assess(("a", "boolean", True), incompatibilities=(not_matching,)).status,
            KnowledgeStatus.EXPLICIT,
        )


if __name__ == "__main__":
    unittest.main()
