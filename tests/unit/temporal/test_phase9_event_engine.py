import os
import subprocess
import sys
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

    def test_stale_same_worker_claim_cannot_ack_a_new_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.sqlite3"
            first = EventEngine(path, lease_seconds=5)
            second = EventEngine(path, lease_seconds=5)
            receipt = first.enqueue("fact.add", {"subject": "alice"}, source="test")
            first_started = threading.Event()
            second_started = threading.Event()
            release_first = threading.Event()
            release_second = threading.Event()

            def first_handler(_event):
                first_started.set()
                if not release_first.wait(10):
                    raise TimeoutError("first handler release timed out")

            def second_handler(_event):
                second_started.set()
                if not release_second.wait(10):
                    raise TimeoutError("second handler release timed out")

            with ThreadPoolExecutor(max_workers=2) as executor:
                first_future = executor.submit(
                    first.process_batch, first_handler, limit=1, worker_id="reused-worker"
                )
                self.assertTrue(first_started.wait(2), "first claim did not start")
                with second._write_transaction():
                    second._db.execute(
                        "UPDATE events SET lease_until_ns=0 WHERE event_id=?",
                        (receipt.event.event_id,),
                    )
                second_future = executor.submit(
                    second.process_batch, second_handler, limit=1, worker_id="reused-worker"
                )
                self.assertTrue(second_started.wait(2), "expired event was not reclaimed")

                release_first.set()
                first_result = first_future.result(timeout=2)
                self.assertEqual(first_result.processed, 0)
                self.assertEqual(first_result.lost_claims, 1)
                current = second.events(limit=1).events[0]
                self.assertEqual(current.status, "processing")
                self.assertEqual(current.attempts, 2)

                release_second.set()
                second_result = second_future.result(timeout=2)
                self.assertEqual(second_result.processed, 1)
                self.assertEqual(second.events(limit=1).events[0].status, "processed")
            first.close()
            second.close()

    def test_claimed_event_recovers_after_abrupt_process_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.sqlite3"
            repo_root = Path(__file__).resolve().parents[3]
            child = """
import os, sys, time
from aether.temporal.engine import EventEngine
engine = EventEngine(sys.argv[1], lease_seconds=0.01)
engine.enqueue('fact.add', {'subject': 'crash-test'}, source='subprocess', event_id='crash-event')
engine._claim_next('crashed-worker', time.time_ns(), 3)
os._exit(0)
"""
            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root / "src") + os.pathsep + env.get("PYTHONPATH", "")
            completed = subprocess.run(
                [sys.executable, "-c", child, str(path)],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            recovered = EventEngine(path)
            claimed = recovered.events(limit=1).events[0]
            self.assertEqual(claimed.status, "processing")
            self.assertEqual(claimed.attempts, 1)
            self.assertEqual(recovered.recover_interrupted(now_ns=2**63 - 1), 1)
            seen = []
            result = recovered.process_batch(
                lambda event: seen.append((event.event_id, event.attempts)), max_attempts=3
            )
            self.assertEqual(result.processed, 1)
            self.assertEqual(seen, [("crash-event", 2)])
            self.assertEqual(recovered.events(limit=1).events[0].status, "processed")
            recovered.close()

    def test_checkpoints_reopen_with_integrity_and_use_processed_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.sqlite3"
            engine = EventEngine(path)
            first = engine.enqueue("fact.add", {"n": 1}, source="test")
            engine.process_batch(lambda _event: None)
            cp1 = engine.save_checkpoint(b"state-one", checkpoint_id="reopen-one")
            second = engine.enqueue("fact.add", {"n": 2}, source="test")
            engine.process_batch(lambda _event: None)
            cp2 = engine.save_checkpoint(b"state-two", checkpoint_id="reopen-two")
            self.assertEqual((cp1.sequence, cp2.sequence), (first.event.sequence, second.event.sequence))
            engine.close()

            reopened = EventEngine(path)
            selected = reopened.load_checkpoint()
            self.assertEqual(selected.checkpoint_id, "reopen-two")
            self.assertEqual(selected.state, b"state-two")
            self.assertEqual(selected.schema_version, 1)
            with reopened._write_transaction():
                reopened._db.execute(
                    "UPDATE checkpoints SET state=? WHERE checkpoint_id=?",
                    (b"corrupt", "reopen-two"),
                )
            with self.assertRaisesRegex(RuntimeError, "corrupt event checkpoint"):
                reopened.load_checkpoint()
            self.assertEqual(reopened.load_checkpoint("reopen-one").state, b"state-one")
            reopened.close()

            prefix = EventEngine(Path(folder) / "prefix.sqlite3")
            prefix.enqueue("fact.add", {"n": 1}, source="test")
            later = prefix.enqueue("fact.add", {"n": 2}, source="test")
            with prefix._write_transaction():
                prefix._db.execute(
                    "UPDATE events SET status='processed', processed_ns=? WHERE event_id=?",
                    (time.time_ns(), later.event.event_id),
                )
            checkpoint = prefix.save_checkpoint(b"prefix-default")
            self.assertEqual(checkpoint.sequence, 0)
            with self.assertRaisesRegex(ValueError, "includes unprocessed events"):
                prefix.save_checkpoint(b"invalid-prefix", sequence=2)
            prefix.close()

    def test_schema_v1_database_migrates_to_fenced_claims(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy-v1.sqlite3"
            database = sqlite3.connect(path)
            database.executescript(
                """
                CREATE TABLE events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE, event_type TEXT NOT NULL,
                    timestamp_ns INTEGER NOT NULL, source TEXT NOT NULL,
                    payload_json TEXT NOT NULL, provenance_json TEXT, event_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','processing','processed','failed')),
                    attempts INTEGER NOT NULL DEFAULT 0, available_at_ns INTEGER NOT NULL,
                    claimed_by TEXT, lease_until_ns INTEGER, created_ns INTEGER NOT NULL,
                    processed_ns INTEGER, last_error TEXT
                );
                CREATE TABLE checkpoints (
                    checkpoint_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL,
                    created_ns INTEGER NOT NULL, state BLOB NOT NULL,
                    digest TEXT NOT NULL, schema_version INTEGER NOT NULL
                );
                PRAGMA application_id = 1095062600;
                PRAGMA user_version = 1;
                """
            )
            database.close()

            migrated = EventEngine(path)
            columns = {row[1] for row in migrated._db.execute("PRAGMA table_info(events)")}
            self.assertIn("claim_token", columns)
            self.assertEqual(migrated._db.execute("PRAGMA user_version").fetchone()[0], 2)
            receipt = migrated.enqueue("fact.add", {"subject": "legacy"}, source="migration")
            result = migrated.process_batch(lambda _event: None)
            self.assertEqual(result.processed, 1)
            self.assertEqual(migrated.events(limit=1).events[0].event_id, receipt.event.event_id)
            migrated.close()

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
            database = sqlite3.connect(path)
            try:
                database.execute("PRAGMA user_version = 999")
            finally:
                database.close()
            with self.assertRaisesRegex(RuntimeError, "unsupported event database schema"):
                EventEngine(path)


if __name__ == "__main__":
    unittest.main()
