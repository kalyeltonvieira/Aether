import tempfile
import unittest
from pathlib import Path

from aether.core.knowledge.store import KnowledgeStore
from aether.reasoning.inference import Pattern, Rule
from aether.reasoning.reasoner import KnowledgeReasoner
from aether.temporal.engine import EventEngine
from aether.temporal.knowledge import KnowledgeEventProcessor


class KnowledgeEventIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = KnowledgeStore()
        self.store.add_entity("alice")
        self.store.add_entity("bob")
        rule = Rule(
            "edge-implies-reachable",
            (Pattern("?x", "sent_email_to", "?y"),),
            Pattern("?x", "can_reach", "?y"),
        )
        self.reasoner = KnowledgeReasoner(self.store, [rule])
        self.reasoner.recompute()
        self.events = EventEngine(self.root / "events.sqlite3")
        self.processor = KnowledgeEventProcessor(
            self.reasoner, snapshot_path=self.root / "knowledge.json"
        )

    def tearDown(self):
        self.events.close()
        self.temporary.cleanup()

    def test_fact_event_updates_incremental_conclusion_and_snapshot(self):
        receipt = self.events.enqueue(
            "fact.add",
            {
                "subject": "alice",
                "predicate": "sent_email_to",
                "object": "bob",
                "confidence": 0.9,
                "properties": {"channel": "smtp"},
                "context": {"domain": "contacts", "period": "2026"},
            },
            source="studio",
            event_id="request-add-1",
        )
        history_size = self.store.history_stats()["retained_changes"]
        self.processor(receipt.event)  # Simulate a delivery whose ack was lost.
        first_version = self.store.version
        self.processor(receipt.event)  # Duplicate event evidence is idempotent.
        self.assertEqual(self.store.version, first_version)
        stored = self.store.query(subject="alice", predicate="sent_email_to")[0]
        self.assertEqual(stored.evidence_records[0].context_map, {"domain": "contacts", "period": "2026"})
        self.assertEqual(
            self.store.history_stats()["retained_changes"], history_size + 1
        )

        result = self.events.process_batch(self.processor, limit=10)
        self.assertEqual(result.processed, 1)
        self.assertEqual(
            [fact.key for fact in self.reasoner.conclusions()],
            [("alice", "can_reach", "bob")],
        )
        restored = KnowledgeStore.load(self.root / "knowledge.json")
        self.assertEqual(restored.query(subject="alice", predicate="sent_email_to")[0].object, "bob")
        self.assertEqual(restored.query(subject="alice", predicate="sent_email_to")[0].provenances[0].record_id,
                         "request-add-1")

    def test_remove_event_invalidates_dependents_and_recomputes_to_oracle(self):
        add = self.events.enqueue(
            "fact.add",
            {"subject": "alice", "predicate": "sent_email_to", "object": "bob"},
            source="studio",
            event_id="request-add-2",
        )
        self.events.process_batch(self.processor)
        fact = self.store.query(subject="alice", predicate="sent_email_to")[0]
        self.assertEqual(len(self.reasoner.conclusions()), 1)

        self.events.enqueue(
            "fact.remove", {"fact_id": fact.fact_id}, source="studio", event_id="request-remove-1"
        )
        result = self.events.process_batch(self.processor)
        self.assertEqual(result.processed, 1)
        self.assertFalse(self.reasoner.state.complete_for_current_store)
        self.assertEqual(self.reasoner.recompute().result.conclusions, ())
        restored = KnowledgeStore.load(self.root / "knowledge.json")
        self.assertEqual(restored.query(subject="alice", predicate="sent_email_to"), ())

        # A duplicate delete delivery is a no-op, not a second mutation.
        version = self.store.version
        self.processor(self.events.events(after_sequence=1, limit=1).events[0])
        self.assertEqual(self.store.version, version)
        self.assertTrue(add.inserted)


if __name__ == "__main__":
    unittest.main()
