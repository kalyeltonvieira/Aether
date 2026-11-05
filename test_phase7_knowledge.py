import unittest

from aether_knowledge import KnowledgeStore, Provenance


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        self.store.add_entity("earth", {"kind": "planet", "year": 2026})
        self.store.add_entity("sun", {"kind": "star"})
        self.store.add_entity("system", {"kind": "collection"})

    def test_entities_are_explicit_and_property_queries_are_index_free_but_exact(self):
        self.assertEqual(self.store.get_entity("earth").property_map()["kind"], "planet")
        self.assertEqual(self.store.query_property("earth", "kind", "planet")[0].entity_id, "earth")
        self.assertEqual(self.store.query_property("earth", "missing"), ())

    def test_facts_have_deterministic_ids_and_provenance(self):
        fact, inserted = self.store.add_fact(
            "earth", "orbits", "sun",
            provenance=Provenance("astronomy-record", "observation-1", 20261105),
            confidence=0.99,
        )
        self.assertTrue(inserted)
        self.assertEqual(fact.fact_id, 1)
        self.assertEqual(fact.provenance.source, "astronomy-record")
        self.assertEqual(fact.confidence, 0.99)

    def test_duplicate_fact_does_not_duplicate_indexes_or_increment_version(self):
        first, inserted = self.store.add_fact("earth", "belongs_to", "system")
        version = self.store.version
        second, inserted_again = self.store.add_fact("earth", "belongs_to", "system")
        self.assertTrue(inserted)
        self.assertFalse(inserted_again)
        self.assertEqual(first, second)
        self.assertEqual(self.store.version, version)
        self.assertEqual(len(self.store.query(subject="earth", predicate="belongs_to")), 1)

    def test_queries_use_combined_subject_predicate_object_semantics(self):
        self.store.add_fact("earth", "orbits", "sun")
        self.store.add_fact("earth", "belongs_to", "system")
        self.store.add_fact("sun", "belongs_to", "system")
        self.assertEqual(len(self.store.query(subject="earth")), 2)
        self.assertEqual(len(self.store.query(predicate="belongs_to")), 2)
        self.assertEqual(self.store.query(object="sun")[0].subject, "earth")
        self.assertEqual(len(self.store.query(subject="earth", predicate="orbits", object="sun")), 1)

    def test_query_results_are_deterministic_by_fact_id(self):
        self.store.add_fact("earth", "related", "sun")
        self.store.add_fact("earth", "related", "system")
        self.assertEqual([fact.fact_id for fact in self.store.query(subject="earth")], [1, 2])

    def test_unknown_subject_is_rejected_and_unknown_entity_is_not_implicitly_created(self):
        with self.assertRaises(KeyError):
            self.store.add_fact("moon", "orbits", "earth")
        with self.assertRaises(KeyError):
            self.store.get_entity("moon")

    def test_remove_fact_updates_all_indexes_and_version(self):
        fact, _ = self.store.add_fact("earth", "orbits", "sun")
        version = self.store.version
        removed = self.store.remove_fact(fact.fact_id)
        self.assertEqual(removed, fact)
        self.assertGreater(self.store.version, version)
        self.assertEqual(self.store.query(subject="earth"), ())
        self.assertEqual(self.store.query(predicate="orbits"), ())
        self.assertEqual(self.store.query(object="sun"), ())

    def test_entity_updates_are_explicit_and_do_not_change_facts(self):
        self.store.add_fact("earth", "belongs_to", "system")
        self.store.update_entity("earth", {"kind": "planet", "status": "active"})
        self.assertEqual(self.store.query(subject="earth")[0].predicate, "belongs_to")
        self.assertEqual(self.store.get_entity("earth").property_map()["status"], "active")

    def test_invalid_confidence_and_provenance_are_rejected(self):
        with self.assertRaises(ValueError):
            Provenance("")
        with self.assertRaises(ValueError):
            self.store.add_fact("earth", "orbits", "sun", confidence=1.1)
        with self.assertRaises(TypeError):
            self.store.add_fact("earth", "orbits", "sun", confidence=True)

    def test_stats_expose_storage_and_index_cardinality(self):
        self.store.add_fact("earth", "orbits", "sun")
        self.store.add_fact("sun", "belongs_to", "system")
        stats = self.store.stats()
        self.assertEqual(stats["entities"], 3)
        self.assertEqual(stats["facts"], 2)
        self.assertEqual(stats["predicate_index_keys"], 2)
        self.assertEqual(stats["version"], 5)


if __name__ == "__main__":
    unittest.main()
