"""Bounded adaptive operational memory for AETHER phase 6.

This module stores opaque byte payloads, tracks operational access frequency and
keeps only a bounded working set in RAM. Optional append-only persistence is a
cold-store fallback; it is not semantic knowledge or an LLM memory.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import threading
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path


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
    """A bounded hot/warm/cold memory with exact key-value retrieval.

    The policy is intentionally operational: access counts and recency determine
    residency. It never infers semantic relevance. Payloads are opaque bytes so
    memory accounting is reproducible and serialization is explicit.
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
        self._entries: dict[str, _Entry] = {}
        self._digest_to_payload: dict[str, bytes] = {}
        self._lru: OrderedDict[str, None] = OrderedDict()
        self._clock = 0
        self._resident_bytes = 0
        self._persisted: dict[str, dict] = {}
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.persist_writes = 0
        self.deduplicated_puts = 0
        self.compactions = 0
        if self.cold_store and self.cold_store.exists():
            self._load_cold_index()

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

    def _load_cold_index(self) -> None:
        assert self.cold_store is not None
        try:
            with self.cold_store.open("r", encoding="utf-8") as stream:
                for line in stream:
                    record = json.loads(line)
                    if record.get("op") != "put":
                        continue
                    key = str(record["key"])
                    self._persisted[key] = record
        except (OSError, ValueError, KeyError) as exc:
            raise RuntimeError(f"cold store is not readable: {self.cold_store}") from exc

    def _append_persisted(self, entry: _Entry) -> None:
        if self.cold_store is None:
            return
        record = {
            "op": "put",
            "key": entry.key,
            "digest": entry.digest,
            "payload": base64.b64encode(entry.payload).decode("ascii"),
            "accesses": entry.accesses,
            "last_access": entry.last_access,
            "created_ns": entry.created_ns,
        }
        temporary = self.cold_store.with_suffix(self.cold_store.suffix + ".part")
        with self.cold_store.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        self._persisted[entry.key] = record
        self.persist_writes += 1
        temporary.unlink(missing_ok=True)

    def _remove_persisted(self, key: str) -> None:
        self._persisted.pop(key, None)

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

    def _evict_until_within_budget(self, protected: str | None = None) -> None:
        while self._resident_bytes > self.max_bytes and self._lru:
            candidates = [key for key in self._lru if key != protected]
            if not candidates:
                raise MemoryError("single payload exceeds adaptive memory budget")
            # Prefer cold entries, then warm; hot entries are evicted only last.
            victim = min(
                candidates,
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
            self._append_persisted(entry)
            self.evictions += 1

    def put(self, key: str, payload) -> dict:
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        data = self._coerce_payload(payload)
        digest = self._digest(data)
        with self._lock:
            current = self._entries.get(key)
            if current is not None and current.digest == digest:
                current.accesses += 1
                self._touch(current)
                self.deduplicated_puts += 1
                return self.metadata(key)
            persisted = self._persisted.get(key)
            if persisted and persisted.get("digest") == digest:
                accesses = int(persisted.get("accesses", 0)) + 1
                created_ns = int(persisted.get("created_ns", time.time_ns()))
            else:
                accesses = 1
                created_ns = time.time_ns()
            entry = _Entry(key, digest, data, accesses, self._clock, created_ns)
            self._remove_persisted(key)
            self._resident_put(entry)
            self._evict_until_within_budget(protected=key)
            return self.metadata(key)

    def get(self, key: str) -> bytes | None:
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.accesses += 1
                self.hits += 1
                self._touch(entry)
                return entry.payload
            record = self._persisted.get(key)
            if record is None:
                self.misses += 1
                return None
            try:
                payload = base64.b64decode(record["payload"].encode("ascii"), validate=True)
            except (KeyError, ValueError) as exc:
                raise RuntimeError(f"corrupt cold-store record for key {key!r}") from exc
            self.hits += 1
            entry = _Entry(
                key,
                str(record["digest"]),
                payload,
                int(record.get("accesses", 0)) + 1,
                self._clock,
                int(record.get("created_ns", time.time_ns())),
            )
            self._remove_persisted(key)
            self._resident_put(entry)
            self._evict_until_within_budget(protected=key)
            return payload

    def delete(self, key: str) -> bool:
        with self._lock:
            entry = self._entries.pop(key, None)
            if entry is not None:
                self._lru.pop(key, None)
                self._resident_bytes -= entry.size
                self._remove_persisted(key)
                return True
            existed = key in self._persisted
            self._remove_persisted(key)
            return existed

    def compact(self) -> dict:
        """Rewrite the cold store without stale append-only records."""
        with self._lock:
            self.compactions += 1
            if self.cold_store is None:
                return self.stats()
            records = list(self._persisted.values())
            temporary = self.cold_store.with_suffix(self.cold_store.suffix + ".compact")
            with temporary.open("w", encoding="utf-8") as stream:
                for record in records:
                    stream.write(json.dumps(record, sort_keys=True) + "\n")
            temporary.replace(self.cold_store)
            return self.stats()

    def metadata(self, key: str) -> dict:
        with self._lock:
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
            record = self._persisted.get(key)
            if record is not None:
                payload_size = len(base64.b64decode(record["payload"]))
                accesses = int(record.get("accesses", 0))
                return {
                    "key": key,
                    "digest": str(record["digest"]),
                    "bytes": payload_size,
                    "accesses": accesses,
                    "tier": "cold",
                    "resident": False,
                }
            raise KeyError(key)

    def stats(self) -> dict:
        with self._lock:
            tiers = defaultdict(int)
            for entry in self._entries.values():
                tiers[self._tier(entry.accesses)] += 1
            return {
                "resident_entries": len(self._entries),
                "cold_entries": len(self._persisted),
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
            }

    def keys(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._entries) + tuple(key for key in self._persisted if key not in self._entries)


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
