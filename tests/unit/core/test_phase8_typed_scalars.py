import unittest

from aether_knowledge import KnowledgeStore, Provenance, scalar_identity


class TypedScalarIdentityTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        self.store.add_entity("e")

    def test_scalar_types_have_distinct_fact_ids_and_object_index_entries(self):
        values = (True, 1, 1.0, "1", None)
        facts = []
        for value in values:
            fact, inserted = self.store.add_fact("e", "value", value)
            self.assertTrue(inserted)
            facts.append(fact)
        self.assertEqual(len({fact.fact_id for fact in facts}), len(values))
        for value, fact in zip(values, facts):
            self.assertEqual(self.store.query(predicate="value", object=value), (fact,))
            duplicate, inserted = self.store.add_fact("e", "value", value)
            self.assertFalse(inserted)
            self.assertEqual(duplicate.fact_id, fact.fact_id)
        self.assertEqual(self.store.stats()["facts"], len(values))

    def test_float_signed_zero_and_nan_payload_identity_is_explicit(self):
        positive, inserted_pos = self.store.add_fact("e", "number", 0.0)
        negative, inserted_neg = self.store.add_fact("e", "number", -0.0)
        self.assertTrue(inserted_pos)
        self.assertTrue(inserted_neg)
        self.assertNotEqual(positive.fact_id, negative.fact_id)
        self.assertEqual(self.store.query(predicate="number", object=0.0), (positive,))
        self.assertEqual(self.store.query(predicate="number", object=-0.0), (negative,))
        self.assertNotEqual(scalar_identity(float("nan")), scalar_identity(float("inf")))

    def test_property_lookup_and_entity_conflict_check_are_type_aware(self):
        self.store.update_entity("e", {"flag": True})
        self.assertEqual(self.store.query_property("e", "flag", True), (self.store.get_entity("e"),))
        self.assertEqual(self.store.query_property("e", "flag", 1), ())
        with self.assertRaises(ValueError):
            self.store.add_entity("e", {"flag": 1})

    def test_unsupported_composites_are_rejected_consistently(self):
        for value in ((1, 2), [1, 2], {"x": 1}):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    self.store.add_fact("e", "value", value)
                with self.assertRaises(TypeError):
                    self.store.update_entity("e", {"value": value})

    def test_provenance_metadata_is_optional_typed_and_legacy_compatible(self):
        legacy = Provenance("source", "old evidence", 123)
        self.assertIsNone(legacy.source_url)
        enriched = Provenance(
            "SNAP",
            evidence="row 2",
            source_url="https://example.test/data",
            source_line=2,
            record_id="email-Eu-core:2",
            evidence_type="dataset_row",
            transformation="edge_list_to_directed_relation",
            observed_at_iso="2026-11-05T10:00:00Z",
        )
        self.assertEqual(enriched.source_line, 2)
        with self.assertRaises(ValueError):
            Provenance("source", source_line=0)
        with self.assertRaises(ValueError):
            Provenance("source", observed_at_iso="not-a-date")


if __name__ == "__main__":
    unittest.main()
