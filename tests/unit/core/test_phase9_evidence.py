import unittest

from aether.core.knowledge.store import KnowledgeStore, Provenance
from aether.reasoning.consistency import ConsistencyValidator, KnowledgeStatus
from aether.reasoning.inference import InferenceEngine, Pattern, Rule


class MultipleFactEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        self.store.add_entity("alice")

    def test_duplicate_claim_keeps_distinct_provenance_and_confidence(self):
        original, inserted = self.store.add_fact(
            "alice", "sent_email_to", "bob",
            provenance=Provenance("mail-archive", record_id="mail-1"),
            confidence=0.8,
        )
        self.assertTrue(inserted)
        version = self.store.version

        merged, inserted_again = self.store.add_fact(
            "alice", "sent_email_to", "bob",
            provenance=Provenance("audit-log", record_id="audit-9"),
            confidence=0.6,
        )

        self.assertFalse(inserted_again)
        self.assertEqual(merged.fact_id, original.fact_id)
        self.assertGreater(self.store.version, version)
        self.assertEqual(
            {p.source for p in merged.provenances},
            {"mail-archive", "audit-log"},
        )
        self.assertEqual(merged.confidence_values, (0.8, 0.6))
        self.assertEqual(len(self.store.query(subject="alice")), 1)

        result = InferenceEngine(self.store).infer()
        explanation = InferenceEngine(self.store).explain_all(
            result, ("alice", "sent_email_to", "bob")
        )[0]
        self.assertEqual({p.source for p in explanation.provenances}, {"mail-archive", "audit-log"})

    def test_later_provenance_can_complete_an_initially_unprovenanced_fact(self):
        fact, _ = self.store.add_fact("alice", "name", "Alice")
        self.store.add_fact(
            "alice", "name", "Alice", provenance=Provenance("directory")
        )
        assessment = ConsistencyValidator(self.store).assess(fact.key)
        self.assertEqual(assessment.status, KnowledgeStatus.EXPLICIT)
        self.assertTrue(assessment.evidence_sufficient)
        self.assertEqual(assessment.explicit_fact_ids, (fact.fact_id,))

    def test_removing_evidence_preserves_fact_until_its_last_support_is_withdrawn(self):
        first, _ = self.store.add_fact(
            "alice", "name", "Alice", provenance=Provenance("directory")
        )
        second, inserted = self.store.add_fact(
            "alice", "name", "Alice", provenance=Provenance("archive")
        )
        self.assertFalse(inserted)
        self.assertEqual(first.fact_id, second.fact_id)
        first_id, second_id = [item.evidence_id for item in second.evidence_records]
        structural_version = self.store.structural_version

        partial = self.store.remove_evidence(first.fact_id, first_id)
        self.assertEqual(partial.evidence.evidence_id, first_id)
        self.assertEqual(partial.fact_after.fact_id, first.fact_id)
        self.assertEqual([item.evidence_id for item in partial.fact_after.evidence_records], [second_id])
        self.assertEqual(self.store.structural_version, structural_version)
        latest = self.store.history_stats()["retained_changes"] - 1
        self.assertEqual(self.store.history_changes(offset=latest, limit=1)[0].operation, "fact_evidence_removed")

        final = self.store.remove_evidence(first.fact_id, second_id)
        self.assertIsNone(final.fact_after)
        self.assertEqual(self.store.query(subject="alice", predicate="name"), ())
        self.assertEqual(self.store.structural_version, structural_version + 1)
        with self.assertRaises(KeyError):
            self.store.remove_evidence(first.fact_id, second_id)

    def test_conflicting_fact_properties_are_not_silently_discarded(self):
        self.store.add_fact("alice", "name", "Alice", properties={"language": "en"})
        with self.assertRaises(ValueError):
            self.store.add_fact("alice", "name", "Alice", properties={"language": "pt"})
        current = self.store.query(subject="alice", predicate="name")[0]
        self.assertEqual(current.property_map(), {"language": "en"})

    def test_context_is_per_evidence_and_contextual_view_does_not_mutate_store(self):
        self.store.add_fact("alice", "legacy_note", "unscoped")
        fact, _ = self.store.add_fact(
            "alice", "name", "A.", provenance=Provenance("directory"),
            context={"domain": "people", "period": "2026"},
        )
        merged, inserted = self.store.add_fact(
            "alice", "name", "A.", provenance=Provenance("archive"),
            context={"domain": "people", "period": "2025"},
        )
        self.assertFalse(inserted)
        self.assertEqual(merged.fact_id, fact.fact_id)

        view = self.store.contextual_view({"domain": "people", "period": "2026"})
        scoped = view.get_fact(fact.fact_id)
        self.assertEqual([item.context_map for item in scoped.evidence_records], [
            {"domain": "people", "period": "2026"},
        ])
        self.assertEqual(len(self.store.get_fact(fact.fact_id).evidence_records), 2)
        self.assertEqual(self.store.contextual_view({}).stats()["facts"], 2)
        self.assertEqual(view.query(predicate="legacy_note"), ())
        self.assertEqual(len(self.store.query(predicate="legacy_note")), 1)

    def test_inference_does_not_join_supports_across_contexts(self):
        self.store.add_entity("team-1")
        self.store.add_fact("alice", "member_of", "team-1", context={"domain": "hr"})
        self.store.add_fact("team-1", "classification", "restricted", context={"domain": "security"})
        rule = Rule(
            "membership-classification",
            (Pattern("?person", "member_of", "?team"), Pattern("?team", "classification", "?label")),
            Pattern("?person", "access_level", "?label"),
        )

        unrestricted = InferenceEngine(self.store, [rule]).infer()
        contextual = InferenceEngine(self.store.contextual_view({"domain": "hr"}), [rule]).infer()
        self.assertEqual([fact.key for fact in unrestricted.conclusions], [
            ("alice", "access_level", "restricted"),
        ])
        self.assertEqual(contextual.conclusions, ())

    def test_invalid_context_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "context keys"):
            self.store.add_fact("alice", "name", "A.", context={" ": "people"})
        with self.assertRaisesRegex(ValueError, "context values"):
            self.store.add_fact("alice", "name", "A.", context={"domain": " "})


if __name__ == "__main__":
    unittest.main()
