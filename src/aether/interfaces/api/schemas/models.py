"""Validated HTTP request models for AETHER Studio.

The domain store remains the source of truth; these models only validate the
JSON boundary and preserve scalar type identity rather than coercing values.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Scalar = Any
_ALLOWED_OBJECT_TYPES = {"str", "int", "float", "bool", "null", "none"}


def validate_scalar(value: Any, field: str = "value") -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError(f"{field} must be finite")
        return value
    raise ValueError(f"{field} must be a scalar JSON value")


def validate_object_type(value: Any, object_type: str | None, field: str = "object_type") -> None:
    if object_type is None:
        return
    if object_type not in _ALLOWED_OBJECT_TYPES:
        raise ValueError(f"{field} must be one of str, int, float, bool, null")
    actual = "none" if value is None else type(value).__name__
    expected = "none" if object_type == "null" else object_type
    if actual != expected:
        raise ValueError(f"{field}={object_type!r} does not match object type {actual!r}")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, strict=True)

    @model_validator(mode="before")
    @classmethod
    def declared_float_type(cls, values):
        # JSON.stringify(1.0) emits 1. The explicit tag preserves its float identity.
        if isinstance(values, dict) and values.get("object_type") == "float" and type(values.get("object")) is int:
            values = dict(values)
            try:
                values["object"] = float(values["object"])
            except OverflowError as exc:
                raise ValueError("object is outside the finite float range") from exc
        return values


class ProvenanceInput(StrictModel):
    source: str = Field(min_length=1, max_length=512)
    evidence_type: str | None = Field(default=None, max_length=256)
    timestamp_ns: int | None = Field(default=None, ge=0)
    detail: str | None = Field(default=None, max_length=4096)
    source_url: str | None = Field(default=None, max_length=4096)
    source_line: int | None = Field(default=None, ge=1)
    record_id: str | None = Field(default=None, max_length=512)
    transformation: str | None = Field(default=None, max_length=1024)
    observed_at_iso: str | None = Field(default=None, max_length=128)


class EntityCreate(StrictModel):
    entity_id: str = Field(min_length=1, max_length=512)
    properties: dict[str, Scalar] = Field(default_factory=dict)

    @field_validator("properties")
    @classmethod
    def properties_are_scalar(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("property names must be non-empty strings")
            validate_scalar(item, f"properties.{key}")
        return value


class EntityPatch(StrictModel):
    properties: dict[str, Scalar]

    @field_validator("properties")
    @classmethod
    def properties_are_scalar(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("property names must be non-empty strings")
            validate_scalar(item, f"properties.{key}")
        return value


class FactCreate(StrictModel):
    subject: str = Field(min_length=1, max_length=512)
    predicate: str = Field(min_length=1, max_length=512)
    object: Scalar
    object_type: str | None = None
    properties: dict[str, Scalar] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance: ProvenanceInput | None = None

    @model_validator(mode="after")
    def validate_values(self):
        validate_scalar(self.object, "object")
        validate_object_type(self.object, self.object_type)
        for key, item in self.properties.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("property names must be non-empty strings")
            validate_scalar(item, f"properties.{key}")
        return self


class FactPatch(StrictModel):
    subject: str | None = Field(default=None, min_length=1, max_length=512)
    predicate: str | None = Field(default=None, min_length=1, max_length=512)
    object: Scalar = None
    object_type: str | None = None
    properties: dict[str, Scalar] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance: ProvenanceInput | None = None
    object_provided: bool = False

    @model_validator(mode="before")
    @classmethod
    def mark_object(cls, values):
        if isinstance(values, dict):
            values = dict(values)
            values["object_provided"] = "object" in values
        return values

    @model_validator(mode="after")
    def validate_values(self):
        if self.object_type is not None and not self.object_provided:
            raise ValueError("object_type requires object")
        if self.object_provided:
            validate_scalar(self.object, "object")
            validate_object_type(self.object, self.object_type)
        if self.properties is not None:
            for key, item in self.properties.items():
                if not isinstance(key, str) or not key.strip():
                    raise ValueError("property names must be non-empty strings")
                validate_scalar(item, f"properties.{key}")
        if not any((self.subject is not None, self.predicate is not None, self.object_provided,
                    self.properties is not None, self.confidence is not None, self.provenance is not None)):
            raise ValueError("patch must contain at least one field")
        return self


class PatternInput(StrictModel):
    subject: str = Field(min_length=1, max_length=512)
    predicate: str = Field(min_length=1, max_length=512)
    object: Scalar

    @model_validator(mode="after")
    def validate_values(self):
        validate_scalar(self.object, "object")
        return self


class RuleCreate(StrictModel):
    rule_id: str = Field(min_length=1, max_length=256)
    revision: int | None = Field(default=None, ge=1)
    enabled: bool = True
    antecedents: list[PatternInput] = Field(min_length=1, max_length=128)
    consequent: PatternInput


class QueryCreate(StrictModel):
    subject: str = Field(min_length=1, max_length=512)
    predicate: str = Field(min_length=1, max_length=512)
    object: Scalar
    object_type: str | None = None
    strategy: Literal["forward", "backward", "hybrid", "adaptive"] | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_values(self):
        validate_scalar(self.object, "object")
        validate_object_type(self.object, self.object_type)
        return self


class ExplanationCreate(StrictModel):
    subject: str = Field(min_length=1, max_length=512)
    predicate: str = Field(min_length=1, max_length=512)
    object: Scalar
    object_type: str | None = None

    @model_validator(mode="after")
    def validate_values(self):
        validate_scalar(self.object, "object")
        validate_object_type(self.object, self.object_type)
        return self


class MemoryBudgetUpdate(StrictModel):
    max_bytes: int = Field(ge=1, le=2**40)


class EventCreate(StrictModel):
    event_type: Literal["entity.add", "fact.add", "fact.remove"]
    source: str = Field(min_length=1, max_length=256)
    payload: dict[str, Any]
    event_id: str | None = Field(default=None, max_length=128)
    provenance: dict[str, Any] | None = None


class EventProcess(StrictModel):
    limit: int | None = Field(default=None, ge=1, le=10000)


class ConfigUpdate(StrictModel):
    memory_max_bytes: int | None = Field(default=None, ge=1, le=2**40)
    max_depth: int | None = Field(default=None, ge=1, le=1000)
    max_operations: int | None = Field(default=None, ge=1, le=10_000_000)
    max_conclusions: int | None = Field(default=None, ge=1, le=1_000_000)
    default_strategy: Literal["forward", "backward", "hybrid"] | None = None
    join_planner: Literal["input", "selective"] | None = None
    persistence_enabled: bool | None = None
    rust_enabled: bool | None = None
    event_batch_size: int | None = Field(default=None, ge=1, le=10000)

    @model_validator(mode="after")
    def not_empty(self):
        if not self.model_fields_set:
            raise ValueError("at least one configuration field is required")
        return self


class AuthLogin(StrictModel):
    token: str = Field(min_length=1, max_length=4096)


class PaginationQuery(StrictModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)
