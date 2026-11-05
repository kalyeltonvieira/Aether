import gzip
import hashlib
import tempfile
import unittest
from pathlib import Path

from aether_snap_semantic import load_email_eu_core


class SemanticSnapTests(unittest.TestCase):
    def test_projection_is_auditable_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "edges.txt.gz"
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                stream.write("# directed interaction\n0 1\n1 2\n0 1\n")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            store, report = load_email_eu_core(path, expected_sha256=digest, source_url="snap://fixture")
            self.assertEqual(report.edge_records, 3)
            self.assertEqual(report.unique_facts, 2)
            self.assertEqual(report.duplicate_records, 1)
            self.assertEqual(report.node_count, 3)
            facts = store.query(predicate="sent_email_to")
            self.assertEqual([(fact.subject, fact.object) for fact in facts], [
                ("snap:email-eu-core:node:0", "snap:email-eu-core:node:1"),
                ("snap:email-eu-core:node:1", "snap:email-eu-core:node:2"),
            ])
            self.assertEqual(facts[0].provenance.source, "snap://fixture")
            self.assertIn("line:2", facts[0].provenance.evidence)
            self.assertEqual(facts[0].property_map()["source_node"], 0)

    def test_hash_mismatch_is_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", encoding="utf-8") as stream:
            stream.write("0 1\n")
            stream.flush()
            with self.assertRaises(ValueError):
                load_email_eu_core(stream.name, expected_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
