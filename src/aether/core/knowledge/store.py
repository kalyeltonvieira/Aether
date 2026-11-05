"""Explicit structured knowledge storage for AETHER phase 7.

This module intentionally does not infer new facts. It stores explicit entities
and directed facts with deterministic identifiers, provenance and query indexes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Hashable, Mapping


Scalar = str | int | float | bool | None


@dataclass(frozen=True)
class Provenance:
    source: str
    evidence: str | None = None
    observed_at: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("provenance source must be a non-empty string")
        if self.observed_at is not None and (
            isinstance(self.observed_at, bool) or not isinstance(self.observed_at, int)
        ):
            raise ValueError("observed_at must be an integer or None")


@dataclass(frozen=True)
class Entity:
    entity_id: str
    properties: tuple[tuple[str, Scalar], ...] = ()

    def property_map(self) -> dict[str, Scalar]:
        return dict(self.properties)


@dataclass(frozen=True)
class Fact:
    fact_id: int
    subject: str
    predicate: str
    object: Scalar
    provenance: Provenance | None
    confidence: float | None
    properties: tuple[tuple[str, Scalar], ...] = ()

    def property_map(self) -> dict[str, Scalar]:
        return dict(self.properties)


class KnowledgeStore:
    """Versioned entity/fact store with indexes for the three fact positions."""

    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}
        self._facts: dict[int, Fact] = {}
        self._fact_keys: dict[tuple[str, str, Hashable], int] = {}
        self._by_subject: dict[str, set[int]] = {}
        self._by_predicate: dict[str, set[int]] = {}
        self._by_object: dict[Hashable, set[int]] = {}
        self._next_fact_id = 1
        self.version = 0

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
        try:
            hash(value)
        except TypeError as exc:
            raise TypeError("fact object must be hashable") from exc
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
            if normalized and existing.properties != normalized:
                raise ValueError(f"entity already exists with different properties: {entity_id}")
            return existing
        entity = Entity(entity_id, normalized)
        self._entities[entity_id] = entity
        self.version += 1
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
        confidence = self._confidence(confidence)
        if subject not in self._entities:
            raise KeyError(f"unknown subject entity: {subject}")
        key = (subject, predicate, object)
        existing_id = self._fact_keys.get(key)
        if existing_id is not None:
            return self._facts[existing_id], False
        fact = Fact(
            self._next_fact_id,
            subject,
            predicate,
            object,
            provenance,
            confidence,
            self._properties(properties),
        )
        self._next_fact_id += 1
        self._facts[fact.fact_id] = fact
        self._fact_keys[key] = fact.fact_id
        self._by_subject.setdefault(subject, set()).add(fact.fact_id)
        self._by_predicate.setdefault(predicate, set()).add(fact.fact_id)
        self._by_object.setdefault(object, set()).add(fact.fact_id)
        self.version += 1
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
        del self._fact_keys[(fact.subject, fact.predicate, fact.object)]
        self._by_subject[fact.subject].remove(fact.fact_id)
        self._by_predicate[fact.predicate].remove(fact.fact_id)
        self._by_object[fact.object].remove(fact.fact_id)
        self.version += 1
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
        candidates: set[int] | None = None
        indexes = []
        if subject is not None:
            indexes.append(self._by_subject.get(subject, set()))
        if predicate is not None:
            indexes.append(self._by_predicate.get(predicate, set()))
        if object is not ...:
            indexes.append(self._by_object.get(object, set()))
        if indexes:
            candidates = set(min(indexes, key=len))
        else:
            candidates = set(self._facts)
        result = []
        for fact_id in sorted(candidates):
            fact = self._facts[fact_id]
            if subject is not None and fact.subject != subject:
                continue
            if predicate is not None and fact.predicate != predicate:
                continue
            if object is not ... and fact.object != object:
                continue
            result.append(fact)
        return tuple(result)

    def query_property(self, entity_id: str, name: str, value: Scalar = ...) -> tuple[Entity, ...]:
        entity = self.get_entity(entity_id)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("property name must be a non-empty string")
        if value is ...:
            return (entity,) if name in entity.property_map() else ()
        return (entity,) if entity.property_map().get(name, ...) == self._scalar(value) else ()

    def stats(self) -> dict[str, int]:
        return {
            "entities": len(self._entities),
            "facts": len(self._facts),
            "subject_index_keys": len(self._by_subject),
            "predicate_index_keys": len(self._by_predicate),
            "object_index_keys": len(self._by_object),
            "version": self.version,
        }
