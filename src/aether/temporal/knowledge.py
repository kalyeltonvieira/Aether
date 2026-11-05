"""Idempotent event handlers that bridge the durable log to AETHER knowledge."""
from __future__ import annotations

import os
from pathlib import Path

from aether.core.knowledge.store import Entity, KnowledgeStore, Provenance
from aether.reasoning.reasoner import KnowledgeReasoner
from aether.temporal.engine import EventRecord


class KnowledgeEventProcessor:
    """Apply supported entity/fact events through a KnowledgeReasoner.

    When ``snapshot_path`` is set, a mutation is followed by an atomic store
    snapshot before the event handler returns. The event queue and store snapshot
    are separate SQLite/JSON transactions; redelivery is safe for the operations
    supported here but is not a distributed exactly-once transaction.
    """

    _SUPPORTED = {"entity.add", "entity.update", "fact.add", "fact.remove"}

    def __init__(
        self,
        target: KnowledgeReasoner | KnowledgeStore,
        *,
        snapshot_path: str | os.PathLike | None = None,
    ):
        if isinstance(target, KnowledgeReasoner):
            self.reasoner = target
        elif isinstance(target, KnowledgeStore):
            self.reasoner = KnowledgeReasoner(target)
        else:
            raise TypeError("target must be a KnowledgeReasoner or KnowledgeStore")
        self.store = self.reasoner.store
        self.snapshot_path = None if snapshot_path is None else Path(snapshot_path).expanduser()
        self._dirty = False

    @staticmethod
    def _provenance(event: EventRecord, value) -> Provenance:
        if value is None:
            return Provenance(event.source, record_id=event.event_id, evidence_type="event")
        if not isinstance(value, dict):
            raise TypeError("provenance payload must be a JSON object")
        data = dict(value)
        data.setdefault("source", event.source)
        data.setdefault("record_id", event.event_id)
        return Provenance(**data)

    def __call__(self, event: EventRecord) -> int:
        if not isinstance(event, EventRecord):
            raise TypeError("event must be an EventRecord")
        if event.event_type not in self._SUPPORTED:
            raise ValueError(f"unsupported knowledge event type: {event.event_type}")
        if self.snapshot_path is not None and self._dirty:
            self.store.save(self.snapshot_path)
            self._dirty = False

        payload = event.payload
        before_version = self.store.version
        try:
            if event.event_type == "entity.add":
                self.reasoner.add_entity(payload["entity_id"], payload.get("properties"))
            elif event.event_type == "entity.update":
                entity_id = payload["entity_id"]
                properties = payload["properties"]
                normalized = self.store._properties(properties)
                current = self.store.get_entity(entity_id)
                if current != Entity(entity_id, normalized):
                    self.reasoner.update_entity(entity_id, properties)
            elif event.event_type == "fact.add":
                provenance = self._provenance(event, payload.get("provenance"))
                self.reasoner.add_fact(
                    payload["subject"],
                    payload["predicate"],
                    payload["object"],
                    provenance=provenance,
                    confidence=payload.get("confidence"),
                    properties=payload.get("properties"),
                    context=payload.get("context"),
                )
            elif event.event_type == "fact.remove":
                fact_id = payload["fact_id"]
                if isinstance(fact_id, bool) or not isinstance(fact_id, int):
                    raise TypeError("fact_id must be an integer")
                try:
                    self.reasoner.remove_fact(fact_id)
                except KeyError:
                    # A retry after a successful removal is an idempotent no-op.
                    pass
        finally:
            # A reasoner may fail after the explicit store mutation. Preserve the
            # dirty marker so the next delivery retries the snapshot first.
            if self.store.version != before_version:
                self._dirty = True

        if self.snapshot_path is not None and self._dirty:
            self.store.save(self.snapshot_path)
            self._dirty = False
        return self.store.version
