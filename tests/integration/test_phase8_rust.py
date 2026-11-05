import unittest

from aether_knowledge import KnowledgeStore, Provenance
from aether_knowledge_rust import RustKnowledgeIndex


class VersionedRustKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for entity in ("a", "b", "c", "d"):
            self.store.add_entity(entity)
        self.ab, _ = self.store.add_fact("a", "link", "b", provenance=Provenance("fixture"))
        self.bc, _ = self.store.add_fact("b", "link", "c", provenance=Provenance("fixture"))
        self.index = RustKnowledgeIndex(self.store, "link")

    def tearDown(self):
        self.index.close()

    def test_direct_edge_and_transitive_reachability_are_distinct(self):
        self.assertTrue(self.index.has_fact("a", "b"))
        self.assertFalse(self.index.has_fact("a", "c"))
        self.assertTrue(self.index.reachable("a", "c"))
        self.assertTrue(self.index.reachable_transitively("a", "c"))
        self.assertFalse(self.index.reachable("c", "a"))
        self.assertTrue(self.index.reachable("a", "a"))

    def test_mutations_are_rejected_until_atomic_refresh(self):
        initial_version = self.index.store_version
        self.store.add_fact("c", "link", "d", provenance=Provenance("fixture"))
        self.assertGreater(self.store.version, initial_version)
        with self.assertRaisesRegex(RuntimeError, "stale"):
            self.index.has_fact("c", "d")
        self.index.refresh()
        self.assertEqual(self.index.store_version, self.store.version)
        self.assertTrue(self.index.has_fact("c", "d"))
        self.assertTrue(self.index.reachable("a", "d"))

        self.store.remove_fact(self.bc.fact_id)
        with self.assertRaisesRegex(RuntimeError, "stale"):
            self.index.reachable("a", "c")
        self.index.refresh()
        self.assertFalse(self.index.reachable("a", "c"))
        self.assertTrue(self.index.has_fact("a", "b"))

    def test_duplicate_fact_does_not_make_the_snapshot_stale(self):
        version = self.store.version
        structural_version = self.store.structural_version
        fact, inserted = self.store.add_fact("a", "link", "b", provenance=Provenance("other"))
        self.assertFalse(inserted)
        self.assertEqual(self.store.version, version + 1)
        self.assertEqual(self.store.structural_version, structural_version)
        self.assertEqual({item.source for item in fact.provenances}, {"fixture", "other"})
        self.assertTrue(self.index.has_fact("a", "b"))

    def test_refresh_after_entity_addition_reassigns_dense_node_ids_safely(self):
        self.store.add_entity("0-new")
        self.store.add_fact("0-new", "link", "d", provenance=Provenance("fixture"))
        with self.assertRaises(RuntimeError):
            self.index.reachable("0-new", "d")
        self.index.refresh()
        self.assertTrue(self.index.has_fact("0-new", "d"))
        self.assertEqual(set(self.index.entity_to_node), {"0-new", "a", "b", "c", "d"})


if __name__ == "__main__":
    unittest.main()
