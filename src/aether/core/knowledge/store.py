"""Explicit structured knowledge storage for AETHER.

This module stores entities and directed facts with deterministic IDs,
provenance, type-aware scalar identity and query indexes; it does not infer.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import struct
from typing import Mapping

Scalar = str | int | float | bool | None
ScalarIdentity = tuple[str, object]
FactIdentity = tuple[str, str, ScalarIdentity]


def scalar_identity(value: Scalar) -> ScalarIdentity:
    """Return a stable, type-tagged identity for a supported scalar.

    Python's normal equality treats ``True == 1 == 1.0`` and ``0.0 == -0.0``.
    Knowledge facts require value-type identity, so floats are encoded by their
    IEEE-754 bytes and all other supported scalar types use explicit tags.
    """
    if value is None:
        return ("none", None)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, float):
        return ("float64", struct.pack("!d", value))
    if isinstance(value, str):
        return ("str", value)
    raise TypeError("value must be a supported scalar")


def scalar_equal(left: Scalar, right: Scalar) -> bool:
    return scalar_identity(left) == scalar_identity(right)


def fact_key_identity(key: tuple[str, str, Scalar]) -> FactIdentity:
    return key[0], key[1], scalar_identity(key[2])


def _properties_identity(properties: tuple[tuple[str, Scalar], ...]) -> tuple:
    return tuple((name, scalar_identity(value)) for name, value in properties)


@dataclass(frozen=True, eq=False)
class Provenance:
    source: str
    evidence: str | None = None
    observed_at: int | None = None
    source_url: str | None = None
    source_line: int | None = None
    record_id: str | None = None
    evidence_type: str | None = None
    transformation: str | None = None
    observed_at_iso: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("provenance source must be a non-empty string")
        if self.evidence is not None and not isinstance(self.evidence, str):
            raise TypeError("evidence must be a string or None")
        if self.observed_at is not None and (
            isinstance(self.observed_at, bool) or not isinstance(self.observed_at, int)
        ):
            raise ValueError("observed_at must be an integer or None")
        for name in ("source_url", "record_id", "evidence_type", "transformation"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string or None")
        if self.source_line is not None and (
            isinstance(self.source_line, bool)
            or not isinstance(self.source_line, int)
            or self.source_line < 1
        ):
            raise ValueError("source_line must be a positive integer or None")
        if self.observed_at_iso is not None:
            if not isinstance(self.observed_at_iso, str) or not self.observed_at_iso.strip():
                raise ValueError("observed_at_iso must be a non-empty ISO date/time or None")
            from datetime import date, datetime

            try:
                date.fromisoformat(self.observed_at_iso)
            except ValueError:
                try:
                    datetime.fromisoformat(self.observed_at_iso.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError("observed_at_iso must be an ISO date/time") from exc

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Provenance):
            return NotImplemented
        return (
            self.source, self.evidence, self.observed_at, self.source_url,
            self.source_line, self.record_id, self.evidence_type,
            self.transformation, self.observed_at_iso,
        ) == (
            other.source, other.evidence, other.observed_at, other.source_url,
            other.source_line, other.record_id, other.evidence_type,
            other.transformation, other.observed_at_iso,
        )

    def __hash__(self) -> int:
        return hash((
            self.source, self.evidence, self.observed_at, self.source_url,
            self.source_line, self.record_id, self.evidence_type,
            self.transformation, self.observed_at_iso,
        ))


@dataclass(frozen=True)
class FactEvidence:
    """One declared support record for a fact, including its own confidence."""

    provenance: Provenance | None
    confidence: float | None


@dataclass(frozen=True, eq=False)
class Entity:
    entity_id: str
    properties: tuple[tuple[str, Scalar], ...] = ()

    def property_map(self) -> dict[str, Scalar]:
        return dict(self.properties)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return NotImplemented
        return self.entity_id == other.entity_id and _properties_identity(self.properties) == _properties_identity(other.properties)

    def __hash__(self) -> int:
        return hash((self.entity_id, _properties_identity(self.properties)))


@dataclass(frozen=True, eq=False)
class Fact:
    fact_id: int
    subject: str
    predicate: str
    object: Scalar
    provenance: Provenance | None
    confidence: float | None
    properties: tuple[tuple[str, Scalar], ...] = ()
    evidence_records: tuple[FactEvidence, ...] = ()

    def __post_init__(self) -> None:
        records = tuple(self.evidence_records) or (FactEvidence(self.provenance, self.confidence),)
        if any(not isinstance(record, FactEvidence) for record in records):
            raise TypeError("evidence_records must contain FactEvidence values")
        unique = tuple(dict.fromkeys(records))
        object.__setattr__(self, "evidence_records", unique)

    @property
    def provenances(self) -> tuple[Provenance, ...]:
        return tuple(dict.fromkeys(
            record.provenance for record in self.evidence_records
            if record.provenance is not None
        ))

    @property
    def confidence_values(self) -> tuple[float, ...]:
        return tuple(dict.fromkeys(
            record.confidence for record in self.evidence_records
            if record.confidence is not None
        ))

    def property_map(self) -> dict[str, Scalar]:
        return dict(self.properties)

    @property
    def key(self) -> tuple[str, str, Scalar]:
        return self.subject, self.predicate, self.object

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Fact):
            return NotImplemented
        return (
            self.fact_id == other.fact_id
            and self.subject == other.subject
            and self.predicate == other.predicate
            and scalar_equal(self.object, other.object)
            and self.provenance == other.provenance
            and self.confidence == other.confidence
            and _properties_identity(self.properties) == _properties_identity(other.properties)
            and self.evidence_records == other.evidence_records
        )

    def __hash__(self) -> int:
        return hash((
            self.fact_id, self.subject, self.predicate, scalar_identity(self.object),
            self.provenance, self.confidence, _properties_identity(self.properties),
            self.evidence_records,
        ))


class KnowledgeStore:
    """Versioned entity/fact store with indexes for the three fact positions."""

    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}
        self._facts: dict[int, Fact] = {}
        self._fact_keys: dict[FactIdentity, int] = {}
        self._by_subject: dict[str, set[int]] = {}
        self._by_predicate: dict[str, set[int]] = {}
        self._by_object: dict[ScalarIdentity, set[int]] = {}
        self._next_fact_id = 1
        self.version = 0
        self.structural_version = 0

    @staticmethod
    def _entity_id(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("entity_id must be a non-empty string")
        return value

    @staticmethod
    def _predicate(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("predicate must be a non-empty string")
        return value

    @staticmethod
    def _scalar(value: Scalar) -> Scalar:
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            raise TypeError("fact objects and properties must be scalar values")
        return value

    @staticmethod
    def _properties(properties: Mapping[str, Scalar] | None) -> tuple[tuple[str, Scalar], ...]:
        if properties is None:
            return ()
        if not isinstance(properties, Mapping):
            raise TypeError("properties must be a mapping")
        normalized = []
        for key, value in properties.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("property names must be non-empty strings")
            normalized.append((key, KnowledgeStore._scalar(value)))
        return tuple(sorted(normalized))

    @staticmethod
    def _confidence(confidence: float | None) -> float | None:
        if confidence is None:
            return None
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise TypeError("confidence must be a number or None")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        return float(confidence)

    def add_entity(self, entity_id: str, properties: Mapping[str, Scalar] | None = None) -> Entity:
        entity_id = self._entity_id(entity_id)
        normalized = self._properties(properties)
        existing = self._entities.get(entity_id)
        if existing is not None:
            if normalized and _properties_identity(existing.properties) != _properties_identity(normalized):
                raise ValueError(f"entity already exists with different properties: {entity_id}")
            return existing
        entity = Entity(entity_id, normalized)
        self._entities[entity_id] = entity
        self.version += 1
        self.structural_version += 1
        return entity

    def update_entity(self, entity_id: str, properties: Mapping[str, Scalar]) -> Entity:
        entity_id = self._entity_id(entity_id)
        if entity_id not in self._entities:
            raise KeyError(entity_id)
        entity = Entity(entity_id, self._properties(properties))
        self._entities[entity_id] = entity
        self.version += 1
        return entity

    def get_entity(self, entity_id: str) -> Entity:
        try:
            return self._entities[self._entity_id(entity_id)]
        except KeyError as exc:
            raise KeyError(entity_id) from exc

    def entities(self) -> tuple[Entity, ...]:
        return tuple(self._entities.values())

    def add_fact(
        self,
        subject: str,
        predicate: str,
        object: Scalar,
        *,
        provenance: Provenance | None = None,
        confidence: float | None = None,
        properties: Mapping[str, Scalar] | None = None,
    ) -> tuple[Fact, bool]:
        subject = self._entity_id(subject)
        predicate = self._predicate(predicate)
        object = self._scalar(object)
        if provenance is not None and not isinstance(provenance, Provenance):
            raise TypeError("provenance must be Provenance or None")
        confidence = self._confidence(confidence)
        if subject not in self._entities:
            raise KeyError(f"unknown subject entity: {subject}")
        key = (subject, predicate, scalar_identity(object))
        existing_id = self._fact_keys.get(key)
        if existing_id is not None:
            existing = self._facts[existing_id]
            merged_properties = dict(existing.properties)
            changed = False
            for name, value in self._properties(properties):
                current = merged_properties.get(name, ...)
                if current is not ... and not scalar_equal(current, value):
                    raise ValueError(
                        f"duplicate fact has conflicting property {name!r}: "
                        f"{current!r} != {value!r}"
                    )
                if current is ...:
                    merged_properties[name] = value
                    changed = True
            evidence = FactEvidence(provenance, confidence)
            evidence_records = existing.evidence_records
            if evidence not in evidence_records:
                evidence_records = evidence_records + (evidence,)
                changed = True
            if changed:
                existing = replace(
                    existing,
                    properties=tuple(sorted(merged_properties.items())),
                    evidence_records=evidence_records,
                )
                self._facts[existing_id] = existing
                self.version += 1
            return existing, False
        fact = Fact(
            self._next_fact_id,
            subject,
            predicate,
            object,
            provenance,
            confidence,
            self._properties(properties),
            (FactEvidence(provenance, confidence),),
        )
        self._next_fact_id += 1
        self._facts[fact.fact_id] = fact
        self._fact_keys[key] = fact.fact_id
        self._by_subject.setdefault(subject, set()).add(fact.fact_id)
        self._by_predicate.setdefault(predicate, set()).add(fact.fact_id)
        self._by_object.setdefault(scalar_identity(object), set()).add(fact.fact_id)
        self.version += 1
        self.structural_version += 1
        return fact, True

    def get_fact(self, fact_id: int) -> Fact:
        if isinstance(fact_id, bool) or not isinstance(fact_id, int):
            raise TypeError("fact_id must be an integer")
        try:
            return self._facts[fact_id]
        except KeyError as exc:
            raise KeyError(fact_id) from exc

    def remove_fact(self, fact_id: int) -> Fact:
        fact = self.get_fact(fact_id)
        del self._facts[fact.fact_id]
        del self._fact_keys[(fact.subject, fact.predicate, scalar_identity(fact.object))]
        self._by_subject[fact.subject].remove(fact.fact_id)
        self._by_predicate[fact.predicate].remove(fact.fact_id)
        self._by_object[scalar_identity(fact.object)].remove(fact.fact_id)
        self.version += 1
        self.structural_version += 1
        return fact

    def query(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        object: Scalar = ...,
    ) -> tuple[Fact, ...]:
        if subject is not None:
            subject = self._entity_id(subject)
        if predicate is not None:
            predicate = self._predicate(predicate)
        if object is not ...:
            object = self._scalar(object)
        candidates: set[int]
        indexes = []
        if subject is not None:
            indexes.append(self._by_subject.get(subject, set()))
        if predicate is not None:
            indexes.append(self._by_predicate.get(predicate, set()))
        if object is not ...:
            indexes.append(self._by_object.get(scalar_identity(object), set()))
        candidates = set(min(indexes, key=len)) if indexes else set(self._facts)
        result = []
        for fact_id in sorted(candidates):
            fact = self._facts[fact_id]
            if subject is not None and fact.subject != subject:
                continue
            if predicate is not None and fact.predicate != predicate:
                continue
            if object is not ... and not scalar_equal(fact.object, object):
                continue
            result.append(fact)
        return tuple(result)

    def query_property(self, entity_id: str, name: str, value: Scalar = ...) -> tuple[Entity, ...]:
        entity = self.get_entity(entity_id)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("property name must be a non-empty string")
        properties = entity.property_map()
        if value is ...:
            return (entity,) if name in properties else ()
        current = properties.get(name, ...)
        return (entity,) if current is not ... and scalar_equal(current, self._scalar(value)) else ()

    def stats(self) -> dict[str, int]:
        return {
            "entities": len(self._entities),
            "facts": len(self._facts),
            "subject_index_keys": len(self._by_subject),
            "predicate_index_keys": len(self._by_predicate),
            "object_index_keys": len(self._by_object),
            "version": self.version,
            "structural_version": self.structural_version,
        }
