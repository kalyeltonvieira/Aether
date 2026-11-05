import unittest

from aether_consistency import ConsistencyValidator
from aether_inference import InferenceEngine, Pattern, Rule
from aether_knowledge import KnowledgeStore, Provenance


class ConsistencyValidatorTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for entity in ("a", "b", "c"):
            self.store.add_entity(entity)

    def test_missing_provenance_is_reported_without_rejecting_storage(self):
        self.store.add_fact("a", "related", "b")
        report = ConsistencyValidator(self.store).validate()
        self.assertFalse(report.consistent)
        self.assertEqual(report.issues[0].code, "missing_provenance")

    def test_explicit_incompatible_facts_are_reported(self):
        source = Provenance("fixture")
        self.store.add_fact("a", "active", "b", provenance=source)
        self.store.add_fact("a", "inactive", "b", provenance=source)
        report = ConsistencyValidator(self.store).validate(incompatible_predicates=(("active", "inactive"),))
        self.assertIn("incompatible_facts", {issue.code for issue in report.issues})

    def test_forbidden_cycles_are_reported_but_not_resolved(self):
        source = Provenance("fixture")
        self.store.add_fact("a", "depends_on", "b", provenance=source)
        self.store.add_fact("b", "depends_on", "a", provenance=source)
        report = ConsistencyValidator(self.store).validate(acyclic_predicates=("depends_on",))
        self.assertIn("forbidden_cycle", {issue.code for issue in report.issues})
        self.assertEqual(len(self.store.query(predicate="depends_on")), 2)

    def test_deep_cycle_detection_does_not_use_python_recursion(self):
        store = KnowledgeStore()
        source = Provenance("deep-fixture")
        count = 1200
        nodes = [f"node-{index}" for index in range(count)]
        for node in nodes:
            store.add_entity(node)
        for index in range(count - 1):
            store.add_fact(nodes[index], "depends_on", nodes[index + 1], provenance=source)
        store.add_fact(nodes[-1], "depends_on", nodes[0], provenance=source)

        report = ConsistencyValidator(store).validate(acyclic_predicates=("depends_on",))
        cycle_issues = [issue for issue in report.issues if issue.code == "forbidden_cycle"]
        self.assertEqual(len(cycle_issues), 1)
        self.assertEqual(len(cycle_issues[0].facts), count)

    def test_contradictory_rules_are_reported(self):
        first = Rule("r1", (Pattern("?x", "p", "?y"),), Pattern("?x", "q", "?y"))
        second = Rule("r2", (Pattern("?x", "p", "?y"),), Pattern("?x", "not_q", "?y"))
        report = ConsistencyValidator(self.store).validate(rules=(first, second))
        self.assertIn("contradictory_rules", {issue.code for issue in report.issues})

    def test_inference_dependency_is_validated_against_current_store(self):
        source = Provenance("fixture")
        self.store.add_fact("a", "p", "b", provenance=source)
        self.store.add_fact("b", "p", "c", provenance=source)
        rule = Rule("transitive", (Pattern("?x", "p", "?y"), Pattern("?y", "p", "?z")), Pattern("?x", "p", "?z"))
        result = InferenceEngine(self.store, (rule,)).infer()
        self.assertTrue(ConsistencyValidator(self.store).validate(inference=result, rules=(rule,)).consistent)

    def test_missing_dependency_is_reported(self):
        source = Provenance("fixture")
        fact, _ = self.store.add_fact("a", "p", "b", provenance=source)
        rule = Rule("copy", (Pattern("?x", "p", "?y"),), Pattern("?x", "q", "?y"))
        result = InferenceEngine(self.store, (rule,)).infer()
        self.store.remove_fact(fact.fact_id)
        report = ConsistencyValidator(self.store).validate(inference=result, rules=(rule,))
        self.assertIn("invalid_dependency", {issue.code for issue in report.issues})


if __name__ == "__main__":
    unittest.main()
