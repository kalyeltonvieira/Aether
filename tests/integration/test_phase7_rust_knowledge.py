import shutil
import unittest

from aether.core.knowledge.store import KnowledgeStore, Provenance
from aether.graph.indexing.rust_knowledge import RustKnowledgeIndex


@unittest.skipUnless(shutil.which("rustc"), "Rust toolchain is not installed")
class RustKnowledgeIndexTests(unittest.TestCase):
    def test_rust_index_matches_python_fact_and_keeps_provenance(self):
        store = KnowledgeStore()
        for entity in ("a", "b", "c"):
            store.add_entity(entity)
        store.add_fact("a", "sent_email_to", "b", provenance=Provenance("fixture", "line:1"))
        store.add_fact("b", "sent_email_to", "c", provenance=Provenance("fixture", "line:2"))
        with RustKnowledgeIndex(store, "sent_email_to") as index:
            self.assertTrue(index.has_fact("a", "b"))
            self.assertFalse(index.has_fact("a", "c"))
            self.assertTrue(index.reachable("a", "c"))
            self.assertGreater(index.build.conversion_ns, 0)
            self.assertGreater(index.build.rust_build_ns, 0)
        self.assertEqual(store.query(subject="a", predicate="sent_email_to")[0].provenance.evidence, "line:1")


if __name__ == "__main__":
    unittest.main()
