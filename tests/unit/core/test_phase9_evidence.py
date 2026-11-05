import unittest

from aether.core.knowledge.store import KnowledgeStore, Provenance
from aether.reasoning.consistency import ConsistencyValidator, KnowledgeStatus
from aether.reasoning.inference import InferenceEngine


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

    def test_conflicting_fact_properties_are_not_silently_discarded(self):
        self.store.add_fact("alice", "name", "Alice", properties={"language": "en"})
        with self.assertRaises(ValueError):
            self.store.add_fact("alice", "name", "Alice", properties={"language": "pt"})
        current = self.store.query(subject="alice", predicate="name")[0]
        self.assertEqual(current.property_map(), {"language": "en"})


if __name__ == "__main__":
    unittest.main()
