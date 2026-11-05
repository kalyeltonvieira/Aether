import json
import tempfile
import unittest
from pathlib import Path

from aether.core.knowledge.store import KnowledgeStore, Provenance


class KnowledgeStorePersistenceTests(unittest.TestCase):
    def test_snapshot_round_trip_preserves_typed_facts_evidence_ids_and_history(self):
        store = KnowledgeStore(history_limit=4)
        store.add_entity("álîce", {"active": True, "label": "AETHER"})
        store.add_entity("bob")
        original, _ = store.add_fact(
            "álîce", "sent_email_to", "bob",
            provenance=Provenance("mailbox", record_id="message-1"),
            confidence=0.91,
            properties={"channel": "smtp"},
        )
        merged, inserted = store.add_fact(
            "álîce", "sent_email_to", "bob",
            provenance=Provenance("audit", source_line=7),
            confidence=0.73,
        )
        self.assertFalse(inserted)
        self.assertEqual(merged.fact_id, original.fact_id)
        store.add_fact("álîce", "typed", True)
        store.add_fact("álîce", "typed", 1)
        store.add_fact("álîce", "zero", 0.0)
        store.add_fact("álîce", "zero", -0.0)
        store.add_fact("álîce", "missing", None)
        store.add_fact("álîce", "large", 2**200)

        with tempfile.TemporaryDirectory(prefix="aether snapshot-ä ") as folder:
            path = Path(folder) / "knowledge snapshot.json"
            store.save(path)
            restored = KnowledgeStore.load(path)

        self.assertEqual(restored.version, store.version)
        self.assertEqual(restored.structural_version, store.structural_version)
        self.assertEqual(restored.stats(), store.stats())
        self.assertEqual(restored.get_fact(original.fact_id), store.get_fact(original.fact_id))
        self.assertEqual(
            {item.source for item in restored.get_fact(original.fact_id).provenances},
            {"mailbox", "audit"},
        )
        self.assertEqual(
            {type(fact.object) for fact in restored.query(subject="álîce", predicate="typed")},
            {bool, int},
        )
        self.assertEqual(
            {fact.fact_id for fact in restored.query(subject="álîce", predicate="zero")},
            {fact.fact_id for fact in store.query(subject="álîce", predicate="zero")},
        )
        self.assertEqual(
            restored.query(subject="álîce", predicate="missing", object=None),
            store.query(subject="álîce", predicate="missing", object=None),
        )
        self.assertEqual(
            restored.query(subject="álîce", predicate="large", object=2**200),
            store.query(subject="álîce", predicate="large", object=2**200),
        )
        self.assertEqual(restored.history_stats(), store.history_stats())
        self.assertEqual(restored.history_changes(limit=4), store.history_changes(limit=4))
        self.assertGreater(restored.history_stats()["truncated_through"], 0)

    def test_tampered_snapshot_is_rejected_before_loading(self):
        store = KnowledgeStore()
        store.add_entity("alice")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "knowledge.json"
            store.save(path)
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["payload"]["state"]["entities"][0]["entity_id"] = "mallory"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                KnowledgeStore.load(path)

    def test_bad_history_arguments_are_explicit(self):
        store = KnowledgeStore(history_limit=2)
        store.add_entity("a")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "knowledge.json"
            store.save(path)
            with self.assertRaises(ValueError):
                store.history_changes(offset=-1)
            with self.assertRaises(ValueError):
                store.history_changes(limit=0)

    def test_unknown_schema_is_rejected(self):
        import hashlib

        store = KnowledgeStore()
        store.add_entity("a")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "knowledge.json"
            store.save(path)
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["payload"]["schema_version"] = 999
            canonical = json.dumps(
                envelope["payload"], sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")
            envelope["sha256"] = hashlib.sha256(canonical).hexdigest()
            path.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported knowledge snapshot schema"):
                KnowledgeStore.load(path)


if __name__ == "__main__":
    unittest.main()
