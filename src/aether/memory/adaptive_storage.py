"""Bounded adaptive operational memory with a durable SQLite cold tier.

This module stores opaque byte payloads, not semantic knowledge. Resident payload
bytes are bounded by ``max_bytes``; when ``cold_store`` is configured, every put
is committed to SQLite before the resident state changes. Older JSONL cold stores
are validated and atomically migrated in place on first open.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path


_SCHEMA_VERSION = 1
_SQLITE_MAGIC = b"SQLite format 3\x00"
_APPLICATION_ID = 0x41455448  # ASCII "AETH"


@dataclass
class _Entry:
    key: str
    digest: str
    payload: bytes
    accesses: int
    last_access: int
    created_ns: int

    @property
    def size(self) -> int:
        return len(self.payload)


class AdaptiveMemory:
    """A bounded hot/warm/cold operational byte store.

    Frequency and recency affect resident tiering and eviction only. The cold
    tier is disk-backed and checks SHA-256 on recovery; this class makes no
    semantic-relevance or exactly-once processing claim.
    """

    def __init__(
        self,
        max_bytes: int,
        *,
        warm_accesses: int = 2,
        hot_accesses: int = 4,
        cold_store: str | os.PathLike | None = None,
    ):
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        if isinstance(warm_accesses, bool) or isinstance(hot_accesses, bool):
            raise TypeError("access thresholds must be integers")
        if not isinstance(warm_accesses, int) or not isinstance(hot_accesses, int):
            raise TypeError("access thresholds must be integers")
        if warm_accesses < 1 or hot_accesses < warm_accesses:
            raise ValueError("thresholds must satisfy 1 <= warm_accesses <= hot_accesses")

        self.max_bytes = max_bytes
        self.warm_accesses = warm_accesses
        self.hot_accesses = hot_accesses
        self.cold_store = Path(cold_store).expanduser() if cold_store else None
        if self.cold_store:
            self.cold_store.parent.mkdir(parents=True, exist_ok=True)
        self._db: sqlite3.Connection | None = None
        self._closed = False
        self._entries: dict[str, _Entry] = {}
        self._lru: OrderedDict[str, None] = OrderedDict()
        self._clock = 0
        self._resident_bytes = 0
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.persist_writes = 0
        self.deduplicated_puts = 0
        self.compactions = 0
        if self.cold_store:
            self._initialize_cold_store()

    @staticmethod
    def _coerce_payload(payload) -> bytes:
        if isinstance(payload, bytes):
            return payload
        if isinstance(payload, bytearray):
            return bytes(payload)
        if isinstance(payload, memoryview):
            return payload.tobytes()
        raise TypeError("payload must be bytes-like")

    @staticmethod
    def _digest(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _positive_int(value, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise RuntimeError(f"corrupt cold-store field: {field}")
        return value

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("AdaptiveMemory is closed")

    @staticmethod
    def _create_schema(db: sqlite3.Connection) -> None:
        db.execute(
            "CREATE TABLE IF NOT EXISTS cold_entries ("
            "key TEXT PRIMARY KEY NOT NULL, digest TEXT NOT NULL, "
            "payload BLOB NOT NULL, accesses INTEGER NOT NULL, created_ns INTEGER NOT NULL)"
        )
        db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def _initialize_cold_store(self) -> None:
        assert self.cold_store is not None
        if self.cold_store.exists():
            with self.cold_store.open("rb") as stream:
                magic = stream.read(len(_SQLITE_MAGIC))
            if magic != _SQLITE_MAGIC:
                self._migrate_legacy_jsonl()

        try:
            db = sqlite3.connect(
                str(self.cold_store), timeout=10.0, check_same_thread=False
            )
            db.execute("PRAGMA busy_timeout = 10000")
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = FULL")
            application_id = int(db.execute("PRAGMA application_id").fetchone()[0])
            user_version = int(db.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if application_id not in (0, _APPLICATION_ID):
                raise RuntimeError("cold store belongs to a different SQLite application")
            if user_version not in (0, _SCHEMA_VERSION):
                raise RuntimeError(f"unsupported cold-store schema version: {user_version}")
            if application_id == 0 and tables and "cold_entries" not in tables:
                raise RuntimeError("existing SQLite file is not an AETHER cold store")
            self._create_schema(db)
            if tables and "cold_entries" not in tables:
                raise RuntimeError("existing SQLite file has no AETHER cold_entries table")
            check = db.execute("PRAGMA integrity_check").fetchone()
            if check is None or check[0] != "ok":
                raise RuntimeError(f"cold-store integrity check failed: {check}")
            self._db = db
        except (sqlite3.Error, OSError) as exc:
            raise RuntimeError(f"cold store is not readable: {self.cold_store}") from exc

    def _migrate_legacy_jsonl(self) -> None:
        """Validate a legacy append-only journal, then replace it atomically."""
        assert self.cold_store is not None
        latest: dict[str, tuple[str, bytes, int, int]] = {}
        if self.cold_store.exists():
            try:
                raw = self.cold_store.read_bytes()
                lines = raw.splitlines(keepends=True)
                for index, line in enumerate(lines):
                    if index == len(lines) - 1 and not line.endswith(b"\n"):
                        # A torn final append was never committed as a full record.
                        break
                    if not line.strip():
                        continue
                    record = json.loads(line.decode("utf-8"))
                    if not isinstance(record, dict):
                        raise ValueError("journal records must be objects")
                    operation = record.get("op")
                    key = record.get("key")
                    if not isinstance(key, str) or not key:
                        raise ValueError("journal key must be a non-empty string")
                    if operation == "delete":
                        latest.pop(key, None)
                        continue
                    if operation != "put":
                        raise ValueError(f"unknown journal operation: {operation!r}")
                    payload = base64.b64decode(record["payload"].encode("ascii"), validate=True)
                    digest = record["digest"]
                    if not isinstance(digest, str) or self._digest(payload) != digest:
                        raise ValueError(f"journal digest mismatch for {key!r}")
                    accesses = self._positive_int(record.get("accesses"), "accesses")
                    created_ns = self._positive_int(record.get("created_ns"), "created_ns")
                    latest[key] = (digest, payload, accesses, created_ns)
            except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
                raise RuntimeError(f"legacy cold-store journal is invalid: {self.cold_store}") from exc

        temporary = self.cold_store.with_name(self.cold_store.name + ".migration")
        temporary.unlink(missing_ok=True)
        db = sqlite3.connect(str(temporary))
        try:
            db.execute("PRAGMA journal_mode = DELETE")
            self._create_schema(db)
            with db:
                db.executemany(
                    "INSERT INTO cold_entries(key,digest,payload,accesses,created_ns) VALUES(?,?,?,?,?)",
                    [
                        (key, digest, sqlite3.Binary(payload), accesses, created_ns)
                        for key, (digest, payload, accesses, created_ns) in latest.items()
                    ],
                )
            check = db.execute("PRAGMA integrity_check").fetchone()
            if check is None or check[0] != "ok":
                raise RuntimeError("migrated cold store failed integrity check")
        except Exception:
            db.close()
            temporary.unlink(missing_ok=True)
            raise
        db.close()
        os.replace(temporary, self.cold_store)

    @property
    def _db_connection(self) -> sqlite3.Connection | None:
        return self.__dict__.get("_db")

    def _record(self, key: str):
        db = self._db_connection
        if db is None:
            return None
        return db.execute(
            "SELECT digest, accesses, created_ns, length(payload) "
            "FROM cold_entries WHERE key = ?",
            (key,),
        ).fetchone()

    def _payload_record(self, key: str):
        db = self._db_connection
        if db is None:
            return None
        return db.execute(
            "SELECT digest, payload, accesses, created_ns FROM cold_entries WHERE key = ?",
            (key,),
        ).fetchone()

    def _persist_entry(
        self, key: str, digest: str, payload: bytes, accesses: int, created_ns: int
    ) -> None:
        db = self._db_connection
        if db is None:
            return
        try:
            with db:
                db.execute(
                    "INSERT INTO cold_entries(key,digest,payload,accesses,created_ns) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                    "digest=excluded.digest,payload=excluded.payload,"
                    "accesses=excluded.accesses,created_ns=excluded.created_ns",
                    (key, digest, sqlite3.Binary(payload), accesses, created_ns),
                )
            self.persist_writes += 1
        except sqlite3.Error as exc:
            raise RuntimeError(f"could not persist cold-store key {key!r}") from exc

    def _persist_access(self, key: str, accesses: int) -> None:
        db = self._db_connection
        if db is None:
            return
        try:
            with db:
                db.execute(
                    "UPDATE cold_entries SET accesses = ? WHERE key = ?",
                    (accesses, key),
                )
            self.persist_writes += 1
        except sqlite3.Error as exc:
            raise RuntimeError(f"could not persist access count for {key!r}") from exc

    def _tier(self, accesses: int) -> str:
        if accesses >= self.hot_accesses:
            return "hot"
        if accesses >= self.warm_accesses:
            return "warm"
        return "cold"

    def _touch(self, entry: _Entry) -> None:
        self._clock += 1
        entry.last_access = self._clock
        self._lru.pop(entry.key, None)
        self._lru[entry.key] = None

    def _resident_put(self, entry: _Entry) -> None:
        previous = self._entries.get(entry.key)
        if previous is not None:
            self._resident_bytes -= previous.size
        self._entries[entry.key] = entry
        self._resident_bytes += entry.size
        self._touch(entry)

    def _evict_until_within_budget(self, required_bytes: int = 0) -> None:
        while self._resident_bytes + required_bytes > self.max_bytes and self._lru:
            victim = min(
                self._lru,
                key=lambda key: (
                    self._tier(self._entries[key].accesses) != "cold",
                    self._tier(self._entries[key].accesses) == "hot",
                    self._entries[key].accesses,
                    self._entries[key].last_access,
                ),
            )
            entry = self._entries.pop(victim)
            self._lru.pop(victim, None)
            self._resident_bytes -= entry.size
            self.evictions += 1
        if self._resident_bytes + required_bytes > self.max_bytes:
            raise MemoryError("single payload exceeds adaptive memory budget")

    def put(self, key: str, payload) -> dict:
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        data = self._coerce_payload(payload)
        if len(data) > self.max_bytes:
            raise MemoryError("single payload exceeds adaptive memory budget")
        digest = self._digest(data)
        with self._lock:
            self._ensure_open()
            current = self._entries.get(key)
            persisted = self._record(key)
            previous_digest = current.digest if current is not None else (
                persisted[0] if persisted is not None else None
            )
            if previous_digest == digest:
                accesses = current.accesses + 1 if current is not None else int(persisted[1]) + 1
                created_ns = current.created_ns if current is not None else int(persisted[2])
                self.deduplicated_puts += 1
            else:
                accesses = 1
                created_ns = time.time_ns()

            # Durability is established before changing or evicting resident state.
            self._persist_entry(key, digest, data, accesses, created_ns)
            if current is not None and current.digest == digest:
                current.accesses = accesses
                self._touch(current)
                return self.metadata(key)

            if current is not None:
                self._entries.pop(key, None)
                self._lru.pop(key, None)
                self._resident_bytes -= current.size
            self._evict_until_within_budget(len(data))
            entry = _Entry(key, digest, data, accesses, self._clock, created_ns)
            self._resident_put(entry)
            return self.metadata(key)

    def get(self, key: str) -> bytes | None:
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        with self._lock:
            self._ensure_open()
            entry = self._entries.get(key)
            if entry is not None:
                accesses = entry.accesses + 1
                self._persist_access(key, accesses)
                entry.accesses = accesses
                self.hits += 1
                self._touch(entry)
                return entry.payload

            record = self._payload_record(key)
            if record is None:
                self.misses += 1
                return None
            digest, raw_payload, old_accesses, created_ns = record
            payload = bytes(raw_payload)
            if self._digest(payload) != digest:
                raise RuntimeError(f"corrupt cold-store record for key {key!r}")
            if len(payload) > self.max_bytes:
                raise MemoryError("cold-store payload exceeds current adaptive memory budget")
            accesses = int(old_accesses) + 1
            self._persist_access(key, accesses)
            self._evict_until_within_budget(len(payload))
            recovered = _Entry(
                key, str(digest), payload, accesses, self._clock, int(created_ns)
            )
            self._resident_put(recovered)
            self.hits += 1
            return payload

    def delete(self, key: str) -> bool:
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        with self._lock:
            self._ensure_open()
            entry = self._entries.get(key)
            persisted = self._record(key)
            existed = entry is not None or persisted is not None
            db = self._db_connection
            if db is not None and persisted is not None:
                try:
                    with db:
                        db.execute("DELETE FROM cold_entries WHERE key = ?", (key,))
                    self.persist_writes += 1
                except sqlite3.Error as exc:
                    raise RuntimeError(f"could not delete cold-store key {key!r}") from exc
            if entry is not None:
                self._entries.pop(key, None)
                self._lru.pop(key, None)
                self._resident_bytes -= entry.size
            return existed

    def compact(self) -> dict:
        """Reclaim SQLite free pages and validate the durable cold tier."""
        with self._lock:
            self._ensure_open()
            self.compactions += 1
            db = self._db_connection
            if db is not None:
                try:
                    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    db.execute("VACUUM")
                    check = db.execute("PRAGMA integrity_check").fetchone()
                    if check is None or check[0] != "ok":
                        raise RuntimeError(f"cold-store integrity check failed: {check}")
                except sqlite3.Error as exc:
                    raise RuntimeError("could not compact cold store") from exc
            return self.stats()

    def metadata(self, key: str) -> dict:
        with self._lock:
            self._ensure_open()
            entry = self._entries.get(key)
            if entry is not None:
                return {
                    "key": key,
                    "digest": entry.digest,
                    "bytes": entry.size,
                    "accesses": entry.accesses,
                    "tier": self._tier(entry.accesses),
                    "resident": True,
                }
            record = self._record(key)
            if record is not None:
                return {
                    "key": key,
                    "digest": str(record[0]),
                    "bytes": int(record[3]),
                    "accesses": int(record[1]),
                    "tier": "cold",
                    "resident": False,
                }
            raise KeyError(key)

    def stats(self) -> dict:
        with self._lock:
            self._ensure_open()
            tiers = defaultdict(int)
            for entry in self._entries.values():
                tiers[self._tier(entry.accesses)] += 1
            db = self._db_connection
            disk_entries = 0 if db is None else int(
                db.execute("SELECT COUNT(*) FROM cold_entries").fetchone()[0]
            )
            return {
                "resident_entries": len(self._entries),
                "cold_entries": max(0, disk_entries - len(self._entries)),
                "resident_bytes": self._resident_bytes,
                "budget_bytes": self.max_bytes,
                "resident_utilization": self._resident_bytes / self.max_bytes,
                "tiers": dict(tiers),
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "persist_writes": self.persist_writes,
                "deduplicated_puts": self.deduplicated_puts,
                "compactions": self.compactions,
                "persistence": "sqlite" if db is not None else None,
                "schema_version": _SCHEMA_VERSION if db is not None else None,
            }

    def keys(self) -> tuple[str, ...]:
        with self._lock:
            self._ensure_open()
            resident = set(self._entries)
            db = self._db_connection
            if db is None:
                return tuple(self._entries)
            persisted = tuple(
                row[0] for row in db.execute("SELECT key FROM cold_entries ORDER BY rowid")
                if row[0] not in resident
            )
            return tuple(self._entries) + persisted

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            db = self._db_connection
            if db is not None:
                db.close()
                self._db = None
            self._closed = True

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class MemoryPolicyComparison:
    """Small deterministic policy harness used by Phase 6 benchmarks."""

    @staticmethod
    def names() -> tuple[str, ...]:
        return ("unbounded_lru", "bounded_lru", "frequency_aware")

    @staticmethod
    def build(name: str, max_bytes: int, cold_store=None) -> AdaptiveMemory:
        if name == "unbounded_lru":
            return AdaptiveMemory(max_bytes=max_bytes, warm_accesses=2, hot_accesses=10**9)
        if name == "bounded_lru":
            return AdaptiveMemory(max_bytes=max_bytes, warm_accesses=2, hot_accesses=4, cold_store=cold_store)
        if name == "frequency_aware":
            return AdaptiveMemory(max_bytes=max_bytes, warm_accesses=1, hot_accesses=3, cold_store=cold_store)
        raise ValueError(f"unknown memory policy: {name}")
