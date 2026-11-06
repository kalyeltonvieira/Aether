"""Durable ordered event queue, replay log, and verified checkpoints for AETHER.

The delivery contract is at-least-once: a crash or lease expiry after a handler
side effect but before the status commit can invoke the same event again, even
while an older handler is still running. Consumers must make side effects
idempotent by ``event_id``. Events are claimed in durable sequence order, and a
per-claim fencing token prevents stale handlers from acknowledging a newer claim.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable, Mapping
import uuid


_SCHEMA_VERSION = 2
_CHECKPOINT_SCHEMA_VERSION = 1
_APPLICATION_ID = 0x41455448  # "AETH"
_STATUSES = {"pending", "processing", "processed", "failed"}


class BackpressureError(RuntimeError):
    """Raised when the configured number of unprocessed events is reached."""


@dataclass(frozen=True)
class EventRecord:
    sequence: int
    event_id: str
    event_type: str
    timestamp_ns: int
    source: str
    payload: dict[str, Any]
    provenance: dict[str, Any] | None
    status: str
    attempts: int
    created_ns: int
    processed_ns: int | None
    last_error: str | None


@dataclass(frozen=True)
class EventReceipt:
    event: EventRecord
    inserted: bool


@dataclass(frozen=True)
class EventPage:
    events: tuple[EventRecord, ...]
    next_after: int | None
    complete: bool


@dataclass(frozen=True)
class EventFailure:
    event_id: str
    attempts: int
    error_type: str
    message: str
    terminal: bool


@dataclass(frozen=True)
class EventBatchResult:
    attempted: int
    processed: int
    retried: int
    failed: int
    lost_claims: int
    failures: tuple[EventFailure, ...]
    queue_depth: int


@dataclass(frozen=True)
class EventCheckpoint:
    checkpoint_id: str
    sequence: int
    created_ns: int
    state: bytes
    digest: str
    schema_version: int


@dataclass(frozen=True)
class CheckpointComparison:
    left_id: str
    right_id: str
    left_sequence: int
    right_sequence: int
    same_state: bool
    left_digest: str
    right_digest: str


@dataclass(frozen=True)
class ReplayResult:
    events_replayed: int
    after_sequence: int
    through_sequence: int
    last_sequence: int


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _non_empty(value: Any, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _normalize_mapping(value: Mapping[str, Any], field: str) -> tuple[dict[str, Any], str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a JSON object")

    def normalize(item, location: str):
        if item is None or isinstance(item, (str, bool, int)):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError(f"{location} must not contain NaN or infinity")
            return item
        if isinstance(item, Mapping):
            result = {}
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise TypeError(f"{location} keys must be strings")
                result[key] = normalize(nested, f"{location}.{key}")
            return result
        if isinstance(item, list):
            return [normalize(nested, f"{location}[]") for nested in item]
        raise TypeError(f"{location} contains a non-JSON value")

    try:
        normalized = normalize(value, field)
        encoded = _canonical_json(normalized)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must contain only finite JSON values") from exc
    return normalized, encoded


class EventEngine:
    """SQLite-backed, ordered event log and single-consumer queue."""

    def __init__(
        self,
        path: str | os.PathLike,
        *,
        max_pending: int = 10_000,
        max_payload_bytes: int = 1_048_576,
        lease_seconds: float = 60.0,
    ):
        self.max_pending = _positive_int(max_pending, "max_pending")
        self.max_payload_bytes = _positive_int(max_payload_bytes, "max_payload_bytes")
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, (int, float))
            or not math.isfinite(float(lease_seconds))
            or lease_seconds <= 0
        ):
            raise ValueError("lease_seconds must be positive")
        self.lease_ns = int(float(lease_seconds) * 1_000_000_000)
        self.path = str(path) if str(path) == ":memory:" else str(Path(path).expanduser())
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        try:
            self._db = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA busy_timeout = 10000")
            self._db.execute("PRAGMA journal_mode = WAL")
            self._db.execute("PRAGMA synchronous = FULL")
            self._initialize_schema()
        except Exception:
            db = getattr(self, "_db", None)
            if db is not None:
                db.close()
            raise

    def _initialize_schema(self) -> None:
        db = self._db
        app_id = int(db.execute("PRAGMA application_id").fetchone()[0])
        schema = int(db.execute("PRAGMA user_version").fetchone()[0])
        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if app_id not in (0, _APPLICATION_ID):
            raise RuntimeError("event database belongs to a different SQLite application")
        if schema not in (0, 1, _SCHEMA_VERSION):
            raise RuntimeError(f"unsupported event database schema version: {schema}")
        if app_id == 0 and tables and "events" not in tables:
            raise RuntimeError("existing SQLite file is not an AETHER event database")
        db.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_id TEXT NOT NULL UNIQUE, event_type TEXT NOT NULL, "
            "timestamp_ns INTEGER NOT NULL, source TEXT NOT NULL, "
            "payload_json TEXT NOT NULL, provenance_json TEXT, event_hash TEXT NOT NULL, "
            "status TEXT NOT NULL CHECK(status IN ('pending','processing','processed','failed')), "
            "attempts INTEGER NOT NULL DEFAULT 0, available_at_ns INTEGER NOT NULL, "
            "claimed_by TEXT, claim_token TEXT, lease_until_ns INTEGER, created_ns INTEGER NOT NULL, "
            "processed_ns INTEGER, last_error TEXT)"
        )
        event_columns = {
            row[1] for row in db.execute("PRAGMA table_info(events)").fetchall()
        }
        if "claim_token" not in event_columns:
            db.execute("ALTER TABLE events ADD COLUMN claim_token TEXT")
        db.execute("CREATE INDEX IF NOT EXISTS events_status_sequence ON events(status, sequence)")
        db.execute(
            "CREATE TABLE IF NOT EXISTS checkpoints ("
            "checkpoint_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL, created_ns INTEGER NOT NULL, "
            "state BLOB NOT NULL, digest TEXT NOT NULL, schema_version INTEGER NOT NULL)"
        )
        db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        check = db.execute("PRAGMA integrity_check").fetchone()
        if check is None or check[0] != "ok":
            raise RuntimeError(f"event database integrity check failed: {check}")

    @contextmanager
    def _write_transaction(self):
        self._ensure_open()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("EventEngine is closed")

    def _record_from_row(self, row: sqlite3.Row) -> EventRecord:
        payload = json.loads(row["payload_json"])
        provenance = None if row["provenance_json"] is None else json.loads(row["provenance_json"])
        return EventRecord(
            int(row["sequence"]),
            str(row["event_id"]),
            str(row["event_type"]),
            int(row["timestamp_ns"]),
            str(row["source"]),
            payload,
            provenance,
            str(row["status"]),
            int(row["attempts"]),
            int(row["created_ns"]),
            None if row["processed_ns"] is None else int(row["processed_ns"]),
            row["last_error"],
        )

    def enqueue(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        source: str,
        event_id: str | None = None,
        timestamp_ns: int | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> EventReceipt:
        event_type = _non_empty(event_type, "event_type", maximum=128)
        source = _non_empty(source, "source", maximum=256)
        event_id = uuid.uuid4().hex if event_id is None else _non_empty(event_id, "event_id", maximum=128)
        timestamp_was_supplied = timestamp_ns is not None
        timestamp_ns = time.time_ns() if timestamp_ns is None else _non_negative_int(timestamp_ns, "timestamp_ns")
        normalized_payload, payload_json = _normalize_mapping(payload, "payload")
        if provenance is not None:
            normalized_provenance, provenance_json = _normalize_mapping(provenance, "provenance")
        else:
            normalized_provenance, provenance_json = None, None
        body_size = len(payload_json.encode("utf-8")) + (
            0 if provenance_json is None else len(provenance_json.encode("utf-8"))
        )
        if body_size > self.max_payload_bytes:
            raise ValueError("event payload exceeds max_payload_bytes")
        envelope = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp_ns": timestamp_ns,
            "source": source,
            "payload": normalized_payload,
            "provenance": normalized_provenance,
        }
        event_hash = hashlib.sha256(_canonical_json(envelope).encode("utf-8")).hexdigest()
        now_ns = time.time_ns()
        with self._lock, self._write_transaction():
            existing = self._db.execute(
                "SELECT * FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if existing is not None:
                if existing["event_hash"] != event_hash:
                    if not timestamp_was_supplied:
                        envelope["timestamp_ns"] = int(existing["timestamp_ns"])
                        retry_hash = hashlib.sha256(
                            _canonical_json(envelope).encode("utf-8")
                        ).hexdigest()
                        if retry_hash == existing["event_hash"]:
                            return EventReceipt(self._record_from_row(existing), False)
                    raise ValueError("event_id already exists with a different payload")
                return EventReceipt(self._record_from_row(existing), False)
            pending = int(self._db.execute(
                "SELECT COUNT(*) FROM events WHERE status IN ('pending','processing','failed')"
            ).fetchone()[0])
            if pending >= self.max_pending:
                raise BackpressureError("event queue is full; retry after processing or requeue")
            cursor = self._db.execute(
                "INSERT INTO events(event_id,event_type,timestamp_ns,source,payload_json,"
                "provenance_json,event_hash,status,attempts,available_at_ns,created_ns) "
                "VALUES(?,?,?,?,?,?,?,'pending',0,?,?)",
                (event_id, event_type, timestamp_ns, source, payload_json, provenance_json,
                 event_hash, now_ns, now_ns),
            )
            row = self._db.execute(
                "SELECT * FROM events WHERE sequence = ?", (cursor.lastrowid,)
            ).fetchone()
            return EventReceipt(self._record_from_row(row), True)

    def events(
        self,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        event_type: str | None = None,
        status: str | None = None,
        timestamp_from_ns: int | None = None,
        timestamp_to_ns: int | None = None,
    ) -> EventPage:
        after_sequence = _non_negative_int(after_sequence, "after_sequence")
        limit = _positive_int(limit, "limit")
        if limit > 10_000:
            raise ValueError("limit must not exceed 10000")
        if event_type is not None:
            event_type = _non_empty(event_type, "event_type", maximum=128)
        if status is not None and status not in _STATUSES:
            raise ValueError("invalid event status")
        if timestamp_from_ns is not None:
            timestamp_from_ns = _non_negative_int(timestamp_from_ns, "timestamp_from_ns")
        if timestamp_to_ns is not None:
            timestamp_to_ns = _non_negative_int(timestamp_to_ns, "timestamp_to_ns")
        if timestamp_from_ns is not None and timestamp_to_ns is not None and timestamp_from_ns > timestamp_to_ns:
            raise ValueError("timestamp_from_ns must be <= timestamp_to_ns")
        conditions = ["sequence > ?"]
        params: list[Any] = [after_sequence]
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if timestamp_from_ns is not None:
            conditions.append("timestamp_ns >= ?")
            params.append(timestamp_from_ns)
        if timestamp_to_ns is not None:
            conditions.append("timestamp_ns <= ?")
            params.append(timestamp_to_ns)
        query = "SELECT * FROM events WHERE " + " AND ".join(conditions) + " ORDER BY sequence LIMIT ?"
        params.append(limit + 1)
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(query, params).fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        records = tuple(self._record_from_row(row) for row in selected)
        next_after = records[-1].sequence if has_more and records else None
        return EventPage(records, next_after, not has_more)

    def _claim_next(
        self, worker_id: str, now_ns: int, max_attempts: int
    ) -> tuple[EventRecord, str] | None:
        with self._write_transaction():
            row = self._db.execute(
                "SELECT * FROM events WHERE status != 'processed' ORDER BY sequence LIMIT 1"
            ).fetchone()
            if row is None or row["status"] == "failed":
                return None
            if row["status"] == "processing" and int(row["lease_until_ns"] or 0) > now_ns:
                return None
            if row["status"] == "pending" and int(row["available_at_ns"]) > now_ns:
                return None
            attempts = int(row["attempts"])
            if attempts >= max_attempts:
                self._db.execute(
                    "UPDATE events SET status='failed', claimed_by=NULL, claim_token=NULL, lease_until_ns=NULL, "
                    "last_error=COALESCE(last_error,'retry limit reached') WHERE sequence=?",
                    (int(row["sequence"]),),
                )
                return None
            claim_token = uuid.uuid4().hex
            self._db.execute(
                "UPDATE events SET status='processing', attempts=attempts+1, claimed_by=?, "
                "claim_token=?, lease_until_ns=? WHERE sequence=?",
                (worker_id, claim_token, now_ns + self.lease_ns, int(row["sequence"])),
            )
            updated = self._db.execute(
                "SELECT * FROM events WHERE sequence=?", (int(row["sequence"]),)
            ).fetchone()
            return self._record_from_row(updated), claim_token

    def process_batch(
        self,
        handler: Callable[[EventRecord], Any],
        *,
        limit: int = 100,
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.5,
        worker_id: str | None = None,
    ) -> EventBatchResult:
        if not callable(handler):
            raise TypeError("handler must be callable")
        limit = _positive_int(limit, "limit")
        max_attempts = _positive_int(max_attempts, "max_attempts")
        if (
            isinstance(retry_delay_seconds, bool)
            or not isinstance(retry_delay_seconds, (int, float))
            or not math.isfinite(float(retry_delay_seconds))
            or retry_delay_seconds < 0
        ):
            raise ValueError("retry_delay_seconds must be non-negative")
        worker_id = (
            f"worker-{uuid.uuid4().hex}"
            if worker_id is None
            else _non_empty(worker_id, "worker_id", maximum=128)
        )
        attempted = processed = retried = failed = lost_claims = 0
        failures = []
        for _ in range(limit):
            now_ns = time.time_ns()
            with self._lock:
                self._ensure_open()
                claim = self._claim_next(worker_id, now_ns, max_attempts)
            if claim is None:
                break
            event, claim_token = claim
            attempted += 1
            try:
                handler(event)
            except Exception as exc:
                error_type = type(exc).__name__[:128]
                message = str(exc).replace("\x00", "")[:1000]
                terminal = event.attempts >= max_attempts
                multiplier = 2 ** min(max(0, event.attempts - 1), 20)
                delay_ns = int(float(retry_delay_seconds) * 1_000_000_000 * multiplier)
                new_status = "failed" if terminal else "pending"
                with self._lock, self._write_transaction():
                    cursor = self._db.execute(
                        "UPDATE events SET status=?, available_at_ns=?, claimed_by=NULL, claim_token=NULL, "
                        "lease_until_ns=NULL, last_error=? WHERE event_id=? AND "
                        "status='processing' AND claimed_by=? AND claim_token=?",
                        (new_status, time.time_ns() + delay_ns, f"{error_type}: {message}", event.event_id, worker_id, claim_token),
                    )
                if cursor.rowcount != 1:
                    lost_claims += 1
                elif terminal:
                    failed += 1
                else:
                    retried += 1
                failures.append(EventFailure(event.event_id, event.attempts, error_type, message, terminal))
                break  # FIFO stream: later events wait for this event to complete/requeue.
            else:
                with self._lock, self._write_transaction():
                    cursor = self._db.execute(
                        "UPDATE events SET status='processed', processed_ns=?, claimed_by=NULL, claim_token=NULL, "
                        "lease_until_ns=NULL, last_error=NULL WHERE event_id=? AND "
                        "status='processing' AND claimed_by=? AND claim_token=?",
                        (time.time_ns(), event.event_id, worker_id, claim_token),
                    )
                if cursor.rowcount == 1:
                    processed += 1
                else:
                    lost_claims += 1
                    break
        return EventBatchResult(
            attempted, processed, retried, failed, lost_claims, tuple(failures),
            self.queue_stats()["unprocessed"],
        )

    def recover_interrupted(self, *, now_ns: int | None = None) -> int:
        """Release expired processing leases; such events may be delivered again."""
        now_ns = time.time_ns() if now_ns is None else _non_negative_int(now_ns, "now_ns")
        with self._lock, self._write_transaction():
            cursor = self._db.execute(
                "UPDATE events SET status='pending', claimed_by=NULL, claim_token=NULL, lease_until_ns=NULL "
                "WHERE status='processing' AND lease_until_ns <= ?",
                (now_ns,),
            )
            return cursor.rowcount

    def requeue(self, event_id: str) -> bool:
        event_id = _non_empty(event_id, "event_id", maximum=128)
        with self._lock, self._write_transaction():
            cursor = self._db.execute(
                "UPDATE events SET status='pending', attempts=0, available_at_ns=?, "
                "claimed_by=NULL, claim_token=NULL, lease_until_ns=NULL, processed_ns=NULL, last_error=NULL "
                "WHERE event_id=? AND status='failed'",
                (time.time_ns(), event_id),
            )
            return cursor.rowcount == 1

    def replay(
        self,
        handler: Callable[[EventRecord], Any],
        *,
        after_sequence: int = 0,
        through_sequence: int | None = None,
        page_size: int = 1000,
    ) -> ReplayResult:
        """Replay processed events in enqueue order without changing queue status."""
        if not callable(handler):
            raise TypeError("handler must be callable")
        after_sequence = _non_negative_int(after_sequence, "after_sequence")
        page_size = _positive_int(page_size, "page_size")
        if page_size > 10_000:
            raise ValueError("page_size must not exceed 10000")
        with self._lock:
            self._ensure_open()
            max_sequence = int(self._db.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM events"
            ).fetchone()[0])
        through_sequence = max_sequence if through_sequence is None else _non_negative_int(through_sequence, "through_sequence")
        if through_sequence > max_sequence:
            raise ValueError("through_sequence exceeds the event log")
        last_sequence = after_sequence
        replayed = 0
        while True:
            with self._lock:
                rows = self._db.execute(
                    "SELECT * FROM events WHERE status='processed' AND sequence>? AND sequence<=? "
                    "ORDER BY sequence LIMIT ?",
                    (last_sequence, through_sequence, page_size),
                ).fetchall()
            if not rows:
                break
            for row in rows:
                record = self._record_from_row(row)
                handler(record)
                replayed += 1
                last_sequence = record.sequence
            if len(rows) < page_size:
                break
        return ReplayResult(replayed, after_sequence, through_sequence, last_sequence)

    def save_checkpoint(
        self,
        state: bytes | bytearray | memoryview,
        *,
        sequence: int | None = None,
        checkpoint_id: str | None = None,
    ) -> EventCheckpoint:
        if isinstance(state, memoryview):
            state = state.tobytes()
        elif isinstance(state, bytearray):
            state = bytes(state)
        if not isinstance(state, bytes):
            raise TypeError("checkpoint state must be bytes-like")
        if len(state) > self.max_payload_bytes:
            raise ValueError("checkpoint state exceeds max_payload_bytes")
        checkpoint_id = uuid.uuid4().hex if checkpoint_id is None else _non_empty(checkpoint_id, "checkpoint_id", maximum=128)
        digest = hashlib.sha256(state).hexdigest()
        created_ns = time.time_ns()
        with self._lock, self._write_transaction():
            max_sequence = int(self._db.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM events"
            ).fetchone()[0])
            if sequence is None:
                first_unprocessed = self._db.execute(
                    "SELECT MIN(sequence) FROM events WHERE status!='processed'"
                ).fetchone()[0]
                sequence = (
                    max_sequence
                    if first_unprocessed is None
                    else int(first_unprocessed) - 1
                )
            else:
                sequence = _non_negative_int(sequence, "sequence")
            if sequence > max_sequence:
                raise ValueError("checkpoint sequence exceeds the event log")
            unprocessed = int(self._db.execute(
                "SELECT COUNT(*) FROM events WHERE sequence<=? AND status!='processed'",
                (sequence,),
            ).fetchone()[0])
            if unprocessed:
                raise ValueError("checkpoint sequence includes unprocessed events")
            self._db.execute(
                "INSERT INTO checkpoints(checkpoint_id,sequence,created_ns,state,digest,schema_version) "
                "VALUES(?,?,?,?,?,?)",
                (checkpoint_id, sequence, created_ns, sqlite3.Binary(state), digest, _CHECKPOINT_SCHEMA_VERSION),
            )
            return EventCheckpoint(checkpoint_id, sequence, created_ns, state, digest, _CHECKPOINT_SCHEMA_VERSION)

    def load_checkpoint(self, checkpoint_id: str | None = None) -> EventCheckpoint | None:
        with self._lock:
            self._ensure_open()
            if checkpoint_id is None:
                row = self._db.execute(
                    "SELECT * FROM checkpoints ORDER BY sequence DESC, created_ns DESC LIMIT 1"
                ).fetchone()
            else:
                checkpoint_id = _non_empty(checkpoint_id, "checkpoint_id", maximum=128)
                row = self._db.execute(
                    "SELECT * FROM checkpoints WHERE checkpoint_id=?", (checkpoint_id,)
                ).fetchone()
        if row is None:
            return None
        state = bytes(row["state"])
        digest = hashlib.sha256(state).hexdigest()
        if digest != row["digest"]:
            raise RuntimeError(f"corrupt event checkpoint {row['checkpoint_id']!r}")
        if int(row["schema_version"]) != _CHECKPOINT_SCHEMA_VERSION:
            raise RuntimeError("event checkpoint schema version is incompatible")
        return EventCheckpoint(
            str(row["checkpoint_id"]), int(row["sequence"]), int(row["created_ns"]),
            state, digest, int(row["schema_version"]),
        )

    def compare_checkpoints(self, left_id: str, right_id: str) -> CheckpointComparison:
        left = self.load_checkpoint(left_id)
        right = self.load_checkpoint(right_id)
        if left is None or right is None:
            missing = left_id if left is None else right_id
            raise KeyError(missing)
        return CheckpointComparison(
            left.checkpoint_id, right.checkpoint_id, left.sequence, right.sequence,
            left.digest == right.digest, left.digest, right.digest,
        )

    def queue_stats(self) -> dict[str, int | str | None]:
        with self._lock:
            self._ensure_open()
            counts = {status: 0 for status in _STATUSES}
            for row in self._db.execute("SELECT status,COUNT(*) AS count FROM events GROUP BY status"):
                counts[str(row["status"])] = int(row["count"])
            max_sequence = int(self._db.execute("SELECT COALESCE(MAX(sequence),0) FROM events").fetchone()[0])
            oldest = self._db.execute(
                "SELECT MIN(created_ns) FROM events WHERE status IN ('pending','processing','failed')"
            ).fetchone()[0]
            return {
                **counts,
                "unprocessed": counts["pending"] + counts["processing"] + counts["failed"],
                "max_pending": self.max_pending,
                "oldest_unprocessed_age_ns": None if oldest is None else max(0, time.time_ns() - int(oldest)),
                "last_sequence": max_sequence,
                "schema_version": _SCHEMA_VERSION,
            }

    def integrity_check(self) -> str:
        with self._lock:
            self._ensure_open()
            row = self._db.execute("PRAGMA integrity_check").fetchone()
            return str(row[0]) if row is not None else "unknown"

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._db.close()
            self._closed = True

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *_):
        self.close()
