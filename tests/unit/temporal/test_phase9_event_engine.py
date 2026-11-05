import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aether.temporal.engine import BackpressureError, EventEngine


class EventEngineTests(unittest.TestCase):
    def test_idempotent_enqueue_and_backpressure(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = EventEngine(Path(folder) / "events.sqlite3", max_pending=1)
            first = engine.enqueue(
                "fact.add", {"subject": "alice", "active": True},
                source="studio", event_id="request-1",
            )
            duplicate = engine.enqueue(
                "fact.add", {"subject": "alice", "active": True},
                source="studio", event_id="request-1",
            )
            self.assertTrue(first.inserted)
            self.assertFalse(duplicate.inserted)
            self.assertEqual(first.event.sequence, duplicate.event.sequence)
            self.assertEqual(first.event.timestamp_ns, duplicate.event.timestamp_ns)
            with self.assertRaises(BackpressureError):
                engine.enqueue("fact.add", {"subject": "bob"}, source="studio")
            with self.assertRaisesRegex(ValueError, "different payload"):
                engine.enqueue(
                    "fact.add", {"subject": "mallory"}, source="studio", event_id="request-1"
                )
            engine.close()

    def test_out_of_order_timestamps_are_processed_in_sequence_order(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = EventEngine(Path(folder) / "events.sqlite3", max_pending=8)
            first = engine.enqueue("edge.add", {"from": "a", "to": "b"}, source="test", timestamp_ns=200)
            second = engine.enqueue("edge.add", {"from": "b", "to": "c"}, source="test", timestamp_ns=100)
            seen = []
            result = engine.process_batch(lambda event: seen.append(event.sequence), limit=8)
            self.assertEqual([first.event.sequence, second.event.sequence], [1, 2])
            self.assertEqual(seen, [1, 2])
            self.assertEqual(result.processed, 2)
            self.assertEqual(result.queue_depth, 0)
            page = engine.events(limit=8, status="processed")
            self.assertEqual([event.timestamp_ns for event in page.events], [200, 100])
            engine.close()

    def test_pending_queue_survives_engine_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.sqlite3"
            first = EventEngine(path)
            receipt = first.enqueue("fact.add", {"subject": "alice"}, source="test")
            first.close()

            recovered = EventEngine(path)
            pending = recovered.events(limit=1).events[0]
            self.assertEqual(pending.event_id, receipt.event.event_id)
            self.assertEqual(pending.status, "pending")
            seen = []
            self.assertEqual(recovered.process_batch(lambda event: seen.append(event.event_id)).processed, 1)
            self.assertEqual(seen, [receipt.event.event_id])
            recovered.close()

    def test_failure_becomes_terminal_and_manual_requeue_is_auditable(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = EventEngine(Path(folder) / "events.sqlite3")
            receipt = engine.enqueue("index.refresh", {"predicate": "edge"}, source="test")
            failed = engine.process_batch(
                lambda _event: (_ for _ in ()).throw(RuntimeError("temporary failure")),
                max_attempts=1,
                retry_delay_seconds=0,
            )
            self.assertEqual(failed.failed, 1)
            self.assertEqual(failed.failures[0].error_type, "RuntimeError")
            stored = engine.events(limit=1).events[0]
            self.assertEqual(stored.status, "failed")
            self.assertIn("temporary failure", stored.last_error)
            self.assertFalse(engine.process_batch(lambda _event: None).processed)

            self.assertTrue(engine.requeue(receipt.event.event_id))
            seen = []
            retried = engine.process_batch(lambda event: seen.append(event.event_id), max_attempts=2)
            self.assertEqual(retried.processed, 1)
            self.assertEqual(seen, [receipt.event.event_id])
            self.assertEqual(engine.events(limit=1).events[0].status, "processed")
            engine.close()

    def test_expired_lease_is_recovered_and_delivered_again(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = EventEngine(Path(folder) / "events.sqlite3", lease_seconds=1)
            receipt = engine.enqueue("fact.update", {"subject": "a"}, source="test")
            with engine._write_transaction():
                engine._db.execute(
                    "UPDATE events SET status='processing',attempts=1,claimed_by='dead-worker',"
                    "lease_until_ns=1 WHERE event_id=?",
                    (receipt.event.event_id,),
                )
            self.assertEqual(engine.recover_interrupted(now_ns=2), 1)
            seen = []
            result = engine.process_batch(lambda event: seen.append(event.attempts), max_attempts=3)
            self.assertEqual(result.processed, 1)
            self.assertEqual(seen, [2])
            engine.close()

    def test_history_pagination_filtering_and_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = EventEngine(Path(folder) / "events.sqlite3")
            events = [
                engine.enqueue("fact.add", {"n": index}, source="test", timestamp_ns=100 + index).event
                for index in range(5)
            ]
            engine.process_batch(lambda _event: None, limit=10)
            first = engine.events(limit=2, status="processed")
            self.assertEqual([event.sequence for event in first.events], [1, 2])
            self.assertFalse(first.complete)
            second = engine.events(after_sequence=first.next_after, limit=2, status="processed")
            self.assertEqual([event.sequence for event in second.events], [3, 4])
            third = engine.events(after_sequence=second.next_after, limit=2, status="processed")
            self.assertEqual([event.sequence for event in third.events], [5])
            self.assertTrue(third.complete)
            filtered = engine.events(timestamp_from_ns=102, timestamp_to_ns=103, limit=10)
            self.assertEqual([event.sequence for event in filtered.events], [3, 4])

            replayed = []
            replay_result = engine.replay(lambda event: replayed.append(event.sequence), page_size=2)
            self.assertEqual(replay_result.events_replayed, 5)
            self.assertEqual(replayed, [1, 2, 3, 4, 5])
            self.assertEqual(events[-1].sequence, replay_result.last_sequence)
            engine.close()

    def test_checkpoints_are_verified_and_comparable(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = EventEngine(Path(folder) / "events.sqlite3")
            engine.enqueue("fact.add", {"subject": "a"}, source="test")
            engine.process_batch(lambda _event: None)
            first = engine.save_checkpoint(b"state-v1", checkpoint_id="cp-1")
            second = engine.save_checkpoint(b"state-v2", sequence=1, checkpoint_id="cp-2")
            self.assertEqual(first.sequence, 1)
            self.assertFalse(engine.compare_checkpoints("cp-1", "cp-2").same_state)
            self.assertEqual(engine.load_checkpoint().checkpoint_id, "cp-2")
            with engine._write_transaction():
                engine._db.execute(
                    "UPDATE checkpoints SET state=? WHERE checkpoint_id=?",
                    (b"tampered", "cp-1"),
                )
            with self.assertRaisesRegex(RuntimeError, "corrupt event checkpoint"):
                engine.load_checkpoint("cp-1")
            self.assertEqual(engine.integrity_check(), "ok")
            engine.close()

    def test_two_consumers_share_fifo_claims_without_duplicate_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.sqlite3"
            first = EventEngine(path, lease_seconds=5)
            second = EventEngine(path, lease_seconds=5)
            for index in range(12):
                first.enqueue("observe", {"index": index}, source="test", event_id=f"e-{index}")
            delivered = []
            lock = threading.Lock()

            def handler(event):
                time.sleep(0.001)
                with lock:
                    delivered.append(event.sequence)

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(engine.process_batch, handler, limit=20)
                    for engine in (first, second)
                ]
                for future in futures:
                    future.result()
            self.assertEqual(delivered, list(range(1, 13)))
            self.assertEqual(len(delivered), len(set(delivered)))
            first.close()
            second.close()

    def test_payload_validation_rejects_non_json_and_non_finite_values(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = EventEngine(Path(folder) / "events.sqlite3")
            for payload in ({"nested": {1: "bad"}}, {"value": (1, 2)}, {"value": float("nan")}):
                with self.subTest(payload=payload):
                    with self.assertRaises(ValueError):
                        engine.enqueue("invalid", payload, source="test")
            engine.close()

    def test_incompatible_database_schema_is_rejected(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.sqlite3"
            with sqlite3.connect(path) as database:
                database.execute("PRAGMA user_version = 999")
            with self.assertRaisesRegex(RuntimeError, "unsupported event database schema"):
                EventEngine(path)


if __name__ == "__main__":
    unittest.main()
