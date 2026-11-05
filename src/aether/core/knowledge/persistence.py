"""Integrity-checked, atomic snapshots for the structured knowledge store."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import struct
import tempfile
from pathlib import Path
from typing import Any

from aether.core.knowledge.store import (
    Entity,
    Fact,
    FactEvidence,
    KnowledgeChange,
    KnowledgeStore,
    Provenance,
    Scalar,
    fact_key_identity,
    scalar_identity,
)


_FORMAT = "aether.knowledge-store"
_SCHEMA_VERSION = 2
_PROVENANCE_FIELDS = (
    "source",
    "evidence",
    "observed_at",
    "source_url",
    "source_line",
    "record_id",
    "evidence_type",
    "transformation",
    "observed_at_iso",
)


def _encode_scalar(value: Scalar) -> dict[str, str]:
    if value is None:
        return {"type": "none"}
    if isinstance(value, bool):
        return {"type": "bool", "value": "true" if value else "false"}
    if isinstance(value, int):
        return {"type": "int", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float64", "value": struct.pack("!d", value).hex()}
    if isinstance(value, str):
        return {"type": "str", "value": value}
    raise TypeError("unsupported scalar in knowledge snapshot")


def _decode_scalar(value: Any) -> Scalar:
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise ValueError("invalid typed scalar in knowledge snapshot")
    kind = value["type"]
    if kind == "none" and set(value) == {"type"}:
        return None
    if set(value) != {"type", "value"}:
        raise ValueError("invalid typed scalar fields in knowledge snapshot")
    raw = value["value"]
    if not isinstance(raw, str):
        raise ValueError("typed scalar value must be a string")
    if kind == "bool":
        if raw not in {"true", "false"}:
            raise ValueError("invalid boolean scalar")
        return raw == "true"
    if kind == "int":
        try:
            result = int(raw)
        except ValueError as exc:
            raise ValueError("invalid integer scalar") from exc
        if str(result) != raw:
            raise ValueError("integer scalar is not canonically encoded")
        return result
    if kind == "float64":
        try:
            raw_bytes = bytes.fromhex(raw)
            if len(raw_bytes) != 8:
                raise ValueError
            return struct.unpack("!d", raw_bytes)[0]
        except (ValueError, struct.error) as exc:
            raise ValueError("invalid float64 scalar") from exc
    if kind == "str":
        return raw
    raise ValueError(f"unsupported scalar type in snapshot: {kind!r}")


def _encode_provenance(value: Provenance | None) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, Provenance):
        raise TypeError("provenance must be Provenance or None")
    return {name: getattr(value, name) for name in _PROVENANCE_FIELDS}


def _decode_provenance(value: Any) -> Provenance | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != set(_PROVENANCE_FIELDS):
        raise ValueError("invalid provenance record in knowledge snapshot")
    return Provenance(**value)


def _encode_properties(properties: tuple[tuple[str, Scalar], ...]) -> list[dict]:
    return [
        {"name": name, "value": _encode_scalar(value)}
        for name, value in properties
    ]


def _decode_properties(value: Any) -> tuple[tuple[str, Scalar], ...]:
    if not isinstance(value, list):
        raise ValueError("properties must be a list in knowledge snapshot")
    result: dict[str, Scalar] = {}
    for record in value:
        if not isinstance(record, dict) or set(record) != {"name", "value"}:
            raise ValueError("invalid property record in knowledge snapshot")
        name = record["name"]
        if not isinstance(name, str) or not name.strip() or name in result:
            raise ValueError("invalid or duplicate property name in knowledge snapshot")
        result[name] = _decode_scalar(record["value"])
    return KnowledgeStore._properties(result)


def _encode_entity(entity: Entity) -> dict:
    return {"entity_id": entity.entity_id, "properties": _encode_properties(entity.properties)}


def _decode_entity(value: Any) -> Entity:
    if not isinstance(value, dict) or set(value) != {"entity_id", "properties"}:
        raise ValueError("invalid entity record in knowledge snapshot")
    entity_id = KnowledgeStore._entity_id(value["entity_id"])
    return Entity(entity_id, _decode_properties(value["properties"]))


def _encode_fact(fact: Fact) -> dict:
    return {
        "fact_id": fact.fact_id,
        "subject": fact.subject,
        "predicate": fact.predicate,
        "object": _encode_scalar(fact.object),
        "properties": _encode_properties(fact.properties),
        "evidence_records": [
            {
                "provenance": _encode_provenance(record.provenance),
                "confidence": record.confidence,
                "context": record.context_map,
            }
            for record in fact.evidence_records
        ],
    }


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _decode_fact(value: Any, *, schema_version: int = _SCHEMA_VERSION) -> Fact:
    required = {"fact_id", "subject", "predicate", "object", "properties", "evidence_records"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("invalid fact record in knowledge snapshot")
    fact_id = _positive_int(value["fact_id"], "fact_id")
    subject = KnowledgeStore._entity_id(value["subject"])
    predicate = KnowledgeStore._predicate(value["predicate"])
    object_value = KnowledgeStore._scalar(_decode_scalar(value["object"]))
    properties = _decode_properties(value["properties"])
    raw_evidence = value["evidence_records"]
    if not isinstance(raw_evidence, list) or not raw_evidence:
        raise ValueError("fact must contain at least one evidence record")
    evidence_records = []
    evidence_fields = (
        {"provenance", "confidence"}
        if schema_version == 1
        else {"provenance", "confidence", "context"}
    )
    for item in raw_evidence:
        if not isinstance(item, dict) or set(item) != evidence_fields:
            raise ValueError("invalid fact evidence in knowledge snapshot")
        provenance = _decode_provenance(item["provenance"])
        confidence = KnowledgeStore._confidence(item["confidence"])
        evidence_records.append(FactEvidence(provenance, confidence, item.get("context", ())))
    primary = evidence_records[0]
    return Fact(
        fact_id,
        subject,
        predicate,
        object_value,
        primary.provenance,
        primary.confidence,
        properties,
        tuple(evidence_records),
    )


def _encode_change(change: KnowledgeChange) -> dict:
    def encode_snapshot(value):
        if value is None:
            return None
        if isinstance(value, Entity):
            return {"kind": "entity", "value": _encode_entity(value)}
        if isinstance(value, Fact):
            return {"kind": "fact", "value": _encode_fact(value)}
        raise TypeError("unknown change snapshot type")

    return {
        "sequence": change.sequence,
        "version": change.version,
        "structural_version": change.structural_version,
        "timestamp_ns": change.timestamp_ns,
        "operation": change.operation,
        "entity_id": change.entity_id,
        "fact_id": change.fact_id,
        "before": encode_snapshot(change.before),
        "after": encode_snapshot(change.after),
    }


def _decode_change(value: Any, *, schema_version: int = _SCHEMA_VERSION) -> KnowledgeChange:
    expected = {
        "sequence", "version", "structural_version", "timestamp_ns", "operation",
        "entity_id", "fact_id", "before", "after",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("invalid history record in knowledge snapshot")

    def decode_snapshot(snapshot):
        if snapshot is None:
            return None
        if not isinstance(snapshot, dict) or set(snapshot) != {"kind", "value"}:
            raise ValueError("invalid history snapshot payload")
        if snapshot["kind"] == "entity":
            return _decode_entity(snapshot["value"])
        if snapshot["kind"] == "fact":
            return _decode_fact(snapshot["value"], schema_version=schema_version)
        raise ValueError("unknown history snapshot kind")

    operation = value["operation"]
    if not isinstance(operation, str) or not operation:
        raise ValueError("history operation must be a non-empty string")
    entity_id = value["entity_id"]
    fact_id = value["fact_id"]
    if entity_id is not None:
        entity_id = KnowledgeStore._entity_id(entity_id)
    if fact_id is not None:
        fact_id = _positive_int(fact_id, "history fact_id")
    timestamp_ns = _positive_int(value["timestamp_ns"], "history timestamp_ns")
    return KnowledgeChange(
        _positive_int(value["sequence"], "history sequence"),
        _non_negative_int(value["version"], "history version"),
        _non_negative_int(value["structural_version"], "history structural_version"),
        timestamp_ns,
        operation,
        entity_id,
        fact_id,
        decode_snapshot(value["before"]),
        decode_snapshot(value["after"]),
    )


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _payload_for(store: KnowledgeStore) -> dict:
    state = {
        "version": store.version,
        "structural_version": store.structural_version,
        "next_fact_id": store._next_fact_id,
        "history_limit": store.history_limit,
        "history_sequence": store._history_sequence,
        "history_truncated_through": store._history_truncated_through,
        "entities": [
            _encode_entity(entity)
            for entity in sorted(store.entities(), key=lambda item: item.entity_id)
        ],
        "facts": [_encode_fact(fact) for fact in sorted(store.query(), key=lambda item: item.fact_id)],
        "history": [_encode_change(change) for change in store._history],
    }
    return {"format": _FORMAT, "schema_version": _SCHEMA_VERSION, "state": state}


def save_store(store: KnowledgeStore, path: str | os.PathLike) -> Path:
    """Write a checksum-protected snapshot using same-directory atomic replace."""
    if not isinstance(store, KnowledgeStore):
        raise TypeError("store must be a KnowledgeStore")
    destination = Path(path).expanduser()
    if not destination.name:
        raise ValueError("snapshot path must name a file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = _payload_for(store)
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    encoded = _canonical_json({"payload": payload, "sha256": digest})
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=destination.name + ".", suffix=".tmp", dir=str(destination.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        if os.name != "nt":
            try:
                directory_fd = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                # Some filesystems do not permit directory fsync; file durability
                # and atomic replacement still hold to the extent they support.
                pass
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def load_store(path: str | os.PathLike) -> KnowledgeStore:
    """Verify and reconstruct an independent store without mutating live state."""
    source = Path(path).expanduser()
    try:
        envelope = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"knowledge snapshot is unreadable: {source}") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "sha256"}:
        raise ValueError("invalid knowledge snapshot envelope")
    payload = envelope["payload"]
    digest = envelope["sha256"]
    if not isinstance(digest, str) or not hmac.compare_digest(
        hashlib.sha256(_canonical_json(payload)).hexdigest(), digest
    ):
        raise ValueError("knowledge snapshot checksum mismatch")
    if not isinstance(payload, dict) or payload.get("format") != _FORMAT:
        raise ValueError("unknown knowledge snapshot format")
    schema_version = payload.get("schema_version")
    if type(schema_version) is not int or schema_version not in {1, _SCHEMA_VERSION}:
        raise ValueError(f"unsupported knowledge snapshot schema: {schema_version!r}")
    state = payload.get("state")
    required = {
        "version", "structural_version", "next_fact_id", "history_limit",
        "history_sequence", "history_truncated_through", "entities", "facts", "history",
    }
    if not isinstance(state, dict) or set(state) != required:
        raise ValueError("invalid knowledge snapshot state")

    history_limit = _positive_int(state["history_limit"], "history_limit")
    store = KnowledgeStore(history_limit=history_limit)
    raw_entities = state["entities"]
    raw_facts = state["facts"]
    raw_history = state["history"]
    if not isinstance(raw_entities, list) or not isinstance(raw_facts, list) or not isinstance(raw_history, list):
        raise ValueError("snapshot collections must be lists")
    for raw_entity in raw_entities:
        entity = _decode_entity(raw_entity)
        if entity.entity_id in store._entities:
            raise ValueError(f"duplicate entity in knowledge snapshot: {entity.entity_id}")
        store._entities[entity.entity_id] = entity
    max_fact_id = 0
    for raw_fact in raw_facts:
        fact = _decode_fact(raw_fact, schema_version=schema_version)
        if fact.subject not in store._entities:
            raise ValueError(f"snapshot fact {fact.fact_id} has an unknown subject")
        if fact.fact_id in store._facts:
            raise ValueError(f"duplicate fact_id in knowledge snapshot: {fact.fact_id}")
        identity = fact_key_identity(fact.key)
        if identity in store._fact_keys:
            raise ValueError("duplicate typed fact key in knowledge snapshot")
        store._facts[fact.fact_id] = fact
        store._fact_keys[identity] = fact.fact_id
        store._by_subject.setdefault(fact.subject, set()).add(fact.fact_id)
        store._by_predicate.setdefault(fact.predicate, set()).add(fact.fact_id)
        store._by_object.setdefault(scalar_identity(fact.object), set()).add(fact.fact_id)
        max_fact_id = max(max_fact_id, fact.fact_id)

    store.version = _non_negative_int(state["version"], "version")
    store.structural_version = _non_negative_int(state["structural_version"], "structural_version")
    store._next_fact_id = _positive_int(state["next_fact_id"], "next_fact_id")
    if store._next_fact_id <= max_fact_id:
        raise ValueError("next_fact_id must be greater than every stored fact_id")
    store._history = [_decode_change(item, schema_version=schema_version) for item in raw_history]
    if len(store._history) > history_limit:
        raise ValueError("snapshot history exceeds its configured limit")
    sequences = [change.sequence for change in store._history]
    if sequences != sorted(set(sequences)):
        raise ValueError("snapshot history sequence is not strictly increasing")
    store._history_sequence = _non_negative_int(state["history_sequence"], "history_sequence")
    store._history_truncated_through = _non_negative_int(
        state["history_truncated_through"], "history_truncated_through"
    )
    if sequences and sequences[-1] > store._history_sequence:
        raise ValueError("history sequence exceeds the stored sequence watermark")
    if store._history_truncated_through > store._history_sequence:
        raise ValueError("history truncation watermark exceeds the stored sequence")
    return store
