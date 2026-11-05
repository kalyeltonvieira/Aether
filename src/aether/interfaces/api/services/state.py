"""Application service layer for AETHER Studio.

This module intentionally contains no HTTP concerns. It owns one process-local
instance of the real AETHER components and serializes all mutations so a
snapshot, rule set, event delivery, and derived reasoning state cannot race.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import asdict, replace
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import secrets
import threading
import time
from typing import Any, Awaitable, Callable

from aether.core.knowledge.store import (
    Entity,
    Fact,
    FactEvidence,
    KnowledgeChange,
    KnowledgeStore,
    Provenance,
    scalar_identity,
)
from aether.memory.adaptive_storage import AdaptiveMemory
from aether.memory.patterns import IncrementalPatternLearner
from aether.metrics import current_rss_bytes
from aether.reasoning.backward import BackwardInference, BackwardLimits
from aether.reasoning.controller import AdaptiveReasoningController, ControllerResult
from aether.reasoning.hybrid import HybridInference
from aether.reasoning.inference import (
    DerivationProof,
    ExplanationNode,
    InferenceEngine,
    InferenceLimits,
    Pattern,
    Rule,
    QueryResult,
    QuerySolution,
)
from aether.reasoning.reasoner import KnowledgeReasoner
from aether.temporal.engine import EventBatchResult, EventEngine, EventRecord
from aether.temporal.knowledge import KnowledgeEventProcessor


DEFAULT_CONFIG: dict[str, Any] = {
    "memory_max_bytes": 8 * 1024 * 1024,
    "max_depth": 8,
    "max_operations": 10_000,
    "max_conclusions": 1_000,
    "default_strategy": "forward",
    "join_planner": "input",
    "persistence_enabled": True,
    "rust_enabled": False,
    "event_batch_size": 100,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _scalar_json(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "none"}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": value}
    if isinstance(value, float):
        return {"type": "float64", "value": value.hex()}
    if isinstance(value, str):
        return {"type": "str", "value": value}
    raise TypeError("unsupported scalar")


def _typed_input(value: Any) -> dict[str, Any]:
    return _scalar_json(value)


def _scalar_type(value: Any) -> str:
    if value is None:
        return "null"
    return type(value).__name__


def _key_type(key: tuple[Any, Any, Any] | list[Any]) -> list[str]:
    return [_scalar_type(value) for value in key]


def _provenance_dict(value: Provenance | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "source": value.source,
        "evidence": value.evidence,
        "observed_at": value.observed_at,
        "source_url": value.source_url,
        "source_line": value.source_line,
        "record_id": value.record_id,
        "evidence_type": value.evidence_type,
        "transformation": value.transformation,
        "observed_at_iso": value.observed_at_iso,
    }


def _fact_dict(fact: Fact) -> dict[str, Any]:
    return {
        "fact_id": fact.fact_id,
        "subject": fact.subject,
        "predicate": fact.predicate,
        "object": fact.object,
        "object_type": _scalar_type(fact.object),
        "properties": fact.property_map(),
        "confidence": fact.confidence,
        "provenances": [_provenance_dict(item) for item in fact.provenances],
        "evidence_records": [
            {"provenance": _provenance_dict(item.provenance), "confidence": item.confidence}
            for item in fact.evidence_records
        ],
    }


def _entity_dict(entity: Entity) -> dict[str, Any]:
    return {"entity_id": entity.entity_id, "properties": entity.property_map()}


def _change_dict(change: KnowledgeChange) -> dict[str, Any]:
    def snap(value):
        if value is None:
            return None
        return _entity_dict(value) if isinstance(value, Entity) else _fact_dict(value)

    return {
        "sequence": change.sequence,
        "version": change.version,
        "structural_version": change.structural_version,
        "timestamp_ns": change.timestamp_ns,
        "operation": change.operation,
        "entity_id": change.entity_id,
        "fact_id": change.fact_id,
        "before": snap(change.before),
        "after": snap(change.after),
    }


def _pattern_dict(pattern: Pattern) -> dict[str, Any]:
    return {"subject": pattern.subject, "predicate": pattern.predicate, "object": pattern.object}


def _rule_dict(rule: Rule) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "revision": rule.revision,
        "enabled": rule.enabled,
        "antecedents": [_pattern_dict(item) for item in rule.antecedents],
        "consequent": _pattern_dict(rule.consequent),
    }


def _support_dict(value: int | tuple[str, str, Any]) -> Any:
    return value if isinstance(value, int) else list(value)


def _proof_dict(proof: DerivationProof) -> dict[str, Any]:
    return {
        "rule_id": proof.rule_id,
        "rule_revision": proof.rule_revision,
        "depth": proof.depth,
        "supports": [_support_dict(item) for item in proof.supports],
    }


def _explanation_dict(node: ExplanationNode, depth: int = 0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "key": list(node.key),
        "key_type": _key_type(node.key),
        "explicit_fact_id": node.explicit_fact_id,
        "provenance": _provenance_dict(node.provenance),
        "provenances": [_provenance_dict(item) for item in node.provenances],
        "cycle_truncated": node.cycle_truncated,
        "proofs": [],
    }
    if depth >= 64:
        result["cycle_truncated"] = True
        return result
    for branch in node.proofs:
        result["proofs"].append({
            "proof": _proof_dict(branch.proof),
            "supports": [_explanation_dict(item, depth + 1) for item in branch.supports],
        })
    return result


def _event_dict(event: EventRecord) -> dict[str, Any]:
    return {
        "sequence": event.sequence,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "timestamp_ns": event.timestamp_ns,
        "source": event.source,
        "payload": event.payload,
        "provenance": event.provenance,
        "status": event.status,
        "attempts": event.attempts,
        "created_ns": event.created_ns,
        "processed_ns": event.processed_ns,
        "last_error": event.last_error,
    }


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"payload": payload, "sha256": hashlib.sha256(_canonical(payload)).hexdigest()}
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    temporary.write_bytes(_canonical(body) + b"\n")
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _load_json(path: Path) -> Any:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "sha256"}:
        raise ValueError(f"invalid state envelope: {path.name}")
    payload = envelope["payload"]
    digest = envelope["sha256"]
    if not isinstance(digest, str) or not hmac.compare_digest(hashlib.sha256(_canonical(payload)).hexdigest(), digest):
        raise ValueError(f"state checksum mismatch: {path.name}")
    return payload


class QueryCache:
    """A bounded observed JSON cache with explicit hit/eviction counters."""

    def __init__(self, max_entries: int = 512):
        self.max_entries = max_entries
        self._data: OrderedDict[str, bytes] = OrderedDict()
        self.backend: AdaptiveMemory | None = None
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, key: str) -> bytes | None:
        backend_key = f"query:{key}"
        if self.backend is not None:
            value = self.backend.get(backend_key)
            if value is not None:
                self.hits += 1
                self._data[key] = b""
                self._data.move_to_end(key)
                return value
            self.misses += 1
            return None
        if key in self._data:
            self.hits += 1
            self._data.move_to_end(key)
            return self._data[key]
        self.misses += 1
        return None

    def put(self, key: str, value: bytes) -> None:
        if self.backend is not None:
            self.backend.put(f"query:{key}", value)
            self._data[key] = b""
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                oldest, _ = self._data.popitem(last=False)
                self.backend.delete(f"query:{oldest}")
                self.evictions += 1
            return
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.max_entries:
            self._data.popitem(last=False)
            self.evictions += 1

    def clear(self) -> None:
        if self.backend is not None:
            for key in tuple(self._data):
                self.backend.delete(f"query:{key}")
        self._data.clear()

    def stats(self) -> dict[str, Any]:
        return {"entries": len(self._data), "capacity": self.max_entries, "hits": self.hits, "misses": self.misses, "evictions": self.evictions}


class StudioState:
    """One synchronized, durable AETHER Studio backend instance."""

    def __init__(self, data_dir: str | os.PathLike | None = None):
        self.data_dir = Path(data_dir or ".aether-data").expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._listeners: set[Callable[[dict[str, Any]], Awaitable[None]]] = set()
        self.started_ns = time.time_ns()
        self.activity: deque[dict[str, Any]] = deque(maxlen=200)
        self.alerts: deque[dict[str, Any]] = deque(maxlen=100)
        self.metric_samples: deque[dict[str, Any]] = deque(maxlen=2048)
        self.strategy_samples: dict[str, list[float]] = {name: [] for name in ("forward", "backward", "hybrid", "adaptive")}
        self.queries_executed = 0
        self.events_processed = 0
        self.last_query_latency_ms: float | None = None
        self._process_cpu = None
        self._config_version = 0
        self.patterns = IncrementalPatternLearner(max_transition_targets=64)
        self.query_cache = QueryCache()

        self.config = dict(DEFAULT_CONFIG)
        config_path = self.data_dir / "config.json"
        if config_path.exists():
            loaded = _load_json(config_path)
            if not isinstance(loaded, dict):
                raise ValueError("config payload must be an object")
            self.config.update(loaded)
        self._validate_config(self.config)

        snapshot_path = self.data_dir / "knowledge.json"
        if self.config["persistence_enabled"] and snapshot_path.exists():
            self.store = KnowledgeStore.load(snapshot_path)
        else:
            self.store = KnowledgeStore()

        self.rules_path = self.data_dir / "rules.json"
        self.rules = self._load_rules() if self.config["persistence_enabled"] and self.rules_path.exists() else []
        self.reasoner = KnowledgeReasoner(self.store, self.rules, join_planner=self.config["join_planner"])
        self.controller = self._new_controller()
        self.reasoner.recompute(self._limits())

        self.events = EventEngine(self.data_dir / "events.sqlite3")
        self.processor = KnowledgeEventProcessor(self.reasoner, snapshot_path=snapshot_path if self.config["persistence_enabled"] else None)
        self.memory = AdaptiveMemory(
            self.config["memory_max_bytes"],
            cold_store=self.data_dir / "memory.sqlite3",
        )
        self.query_cache.backend = self.memory
        self._rust_available, self._rust_error = self._verify_rust()
        self._persist_config()
        self.sample_metrics()

    @property
    def lock(self):
        return self._lock

    def _validate_config(self, config: dict[str, Any]) -> None:
        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = value
        if config["join_planner"] not in {"input", "selective"}:
            raise ValueError("join_planner must be input or selective")
        if config["default_strategy"] not in {"forward", "backward", "hybrid"}:
            raise ValueError("default_strategy is invalid")
        for name in ("memory_max_bytes", "max_depth", "max_operations", "max_conclusions", "event_batch_size"):
            if isinstance(config[name], bool) or not isinstance(config[name], int) or config[name] < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(config["persistence_enabled"], bool) or not isinstance(config["rust_enabled"], bool):
            raise ValueError("persistence_enabled and rust_enabled must be bool")

    def _limits(self) -> InferenceLimits:
        return InferenceLimits(self.config["max_depth"], self.config["max_operations"], self.config["max_conclusions"])

    def _new_controller(self) -> AdaptiveReasoningController:
        return AdaptiveReasoningController(
            self.store,
            self.rules,
            backward_limits=BackwardLimits(self.config["max_depth"], self.config["max_operations"]),
            forward_limits=self._limits(),
            max_query_results=1000,
            join_planner=self.config["join_planner"],
        )

    def _load_rules(self) -> list[Rule]:
        payload = _load_json(self.rules_path)
        if not isinstance(payload, list):
            raise ValueError("rules payload must be a list")
        result = []
        for raw in payload:
            if not isinstance(raw, dict):
                raise ValueError("rule record must be an object")
            def pattern(value):
                return Pattern(value["subject"], value["predicate"], value["object"])
            result.append(Rule(
                raw["rule_id"], tuple(pattern(item) for item in raw["antecedents"]),
                pattern(raw["consequent"]), raw.get("revision", 1), raw.get("enabled", True),
            ))
        return result

    def _persist_config(self) -> None:
        _atomic_json(self.data_dir / "config.json", dict(self.config))

    def _persist_rules(self) -> None:
        if self.config["persistence_enabled"]:
            _atomic_json(self.rules_path, [_rule_dict(item) for item in self.rules])

    def persist(self) -> None:
        if self.config["persistence_enabled"]:
            self.store.save(self.data_dir / "knowledge.json")
            self._persist_rules()
        self._persist_config()

    def _verify_rust(self) -> tuple[bool, str | None]:
        try:
            from aether.native import bindings
            configured = os.environ.get("AETHER_NATIVE_LIB")
            candidate = Path(configured).expanduser() if configured else bindings._native_build_dir() / bindings._native_filename()
            if not candidate.exists():
                return False, "native library is not built; no operation executed"
            library = bindings._load_library(candidate)
            del library
            return True, None
        except Exception as exc:
            return False, f"{type(exc).__name__}: {str(exc)[:300]}"

    def rust_status(self) -> dict[str, Any]:
        return {"status": "available" if self._rust_available else "unavailable", "available": self._rust_available, "operations": None, "last_error": self._rust_error}

    def register_listener(self, listener: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._listeners.add(listener)

    def unregister_listener(self, listener: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._listeners.discard(listener)

    async def notify(self, event_type: str, data: Any) -> None:
        message = {"type": event_type, "timestamp_ns": time.time_ns(), "data": data}
        for listener in tuple(self._listeners):
            try:
                await listener(message)
            except Exception:
                self._listeners.discard(listener)

    def record_activity(self, operation: str, **fields: Any) -> None:
        self.activity.appendleft({"timestamp_ns": time.time_ns(), "operation": operation, **fields})
        self.patterns.observe("api", operation)

    def record_alert(self, message: str, *, level: str = "error") -> None:
        self.alerts.appendleft({"timestamp_ns": time.time_ns(), "level": level, "message": message})

    def _after_knowledge_mutation(self, operation: str, **fields: Any) -> dict[str, Any]:
        self.query_cache.clear()
        self.persist()
        self.record_activity(operation, **fields)
        return {"store_version": self.store.version, "facts": self.store.stats()["facts"], "entities": self.store.stats()["entities"]}

    def add_entity(self, entity_id: str, properties: dict[str, Any]) -> Entity:
        with self._lock:
            entity = self.reasoner.add_entity(entity_id, properties)
            self._after_knowledge_mutation("entity.add", entity_id=entity_id)
            return entity

    def update_entity(self, entity_id: str, properties: dict[str, Any]) -> Entity:
        with self._lock:
            entity = self.reasoner.update_entity(entity_id, properties)
            self._after_knowledge_mutation("entity.update", entity_id=entity_id)
            return entity

    @staticmethod
    def provenance_from_input(value: Any) -> Provenance | None:
        if value is None:
            return None
        data = value if isinstance(value, dict) else value.model_dump()
        mapped = {
            "source": data["source"],
            "evidence_type": data.get("evidence_type"),
            "observed_at": data.get("timestamp_ns"),
            "evidence": data.get("detail"),
            "source_url": data.get("source_url"),
            "source_line": data.get("source_line"),
            "record_id": data.get("record_id"),
            "transformation": data.get("transformation"),
            "observed_at_iso": data.get("observed_at_iso"),
        }
        return Provenance(**mapped)

    def add_fact(self, payload: Any) -> Fact:
        with self._lock:
            data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
            fact, _ = self.reasoner.add_fact(
                data["subject"], data["predicate"], data["object"],
                provenance=self.provenance_from_input(data.get("provenance")),
                confidence=data.get("confidence"), properties=data.get("properties"),
            )
            self._after_knowledge_mutation("fact.add", fact_id=fact.fact_id)
            return fact

    def remove_fact(self, fact_id: int) -> Fact:
        with self._lock:
            fact = self.store.get_fact(fact_id)
            self.reasoner.remove_fact(fact_id)
            self._after_knowledge_mutation("fact.remove", fact_id=fact_id)
            return fact

    def replace_fact(self, fact_id: int, payload: Any) -> dict[str, Any]:
        with self._lock:
            old = self.store.get_fact(fact_id)
            data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
            new_subject = data.get("subject", old.subject)
            new_predicate = data.get("predicate", old.predicate)
            new_object = data["object"] if data.get("object_provided") else old.object
            new_properties = data.get("properties") if data.get("properties") is not None else old.property_map()
            new_confidence = data.get("confidence") if data.get("confidence") is not None else old.confidence
            new_provenance = self.provenance_from_input(data.get("provenance")) if data.get("provenance") is not None else old.provenance
            key_changed = (new_subject, new_predicate, scalar_identity(new_object)) != (old.subject, old.predicate, scalar_identity(old.object))
            if not key_changed and data.get("properties") is None and data.get("provenance") is None and data.get("confidence") is None:
                raise ValueError("patch contains no effective fact change")
            self.reasoner.remove_fact(fact_id)
            try:
                new_fact, _ = self.reasoner.add_fact(new_subject, new_predicate, new_object, provenance=new_provenance, confidence=new_confidence, properties=new_properties)
                # Carry all old evidence into a replacement key. The new evidence is
                # retained as the primary record and duplicate records are deduped by core.
                for evidence in old.evidence_records:
                    if evidence.provenance == new_provenance and evidence.confidence == new_confidence:
                        continue
                    new_fact, _ = self.reasoner.add_fact(new_subject, new_predicate, new_object, provenance=evidence.provenance, confidence=evidence.confidence, properties={})
            except Exception:
                # Restore the original fact through the same real store API if the
                # replacement was invalid; the outer request still reports the error.
                self.reasoner.add_fact(old.subject, old.predicate, old.object, provenance=old.provenance, confidence=old.confidence, properties=old.property_map())
                for evidence in old.evidence_records[1:]:
                    self.reasoner.add_fact(old.subject, old.predicate, old.object, provenance=evidence.provenance, confidence=evidence.confidence, properties={})
                raise
            self._after_knowledge_mutation("fact.replace", fact_id=new_fact.fact_id, replaced_fact_id=fact_id)
            result = _fact_dict(new_fact)
            result.update({"replaced_fact_id": fact_id, "new_fact_id": new_fact.fact_id, "key_changed": key_changed})
            return result

    def add_rule(self, payload: Any) -> Rule:
        with self._lock:
            data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
            def pattern(item):
                return Pattern(item["subject"], item["predicate"], item["object"])
            rule = Rule(data["rule_id"], tuple(pattern(item) for item in data["antecedents"]), pattern(data["consequent"]), data.get("revision") or 1, data.get("enabled", True))
            self.reasoner.add_rule(rule)
            self.controller.add_rule(rule)
            self.rules = list(self.reasoner.engine.rules)
            self.query_cache.clear()
            self._config_version += 1
            self._persist_rules()
            self.record_activity("rule.add", rule_id=rule.rule_id)
            return rule

    def remove_rule(self, rule_id: str) -> Rule:
        with self._lock:
            removed = self.reasoner.remove_rule(rule_id)
            self.controller.remove_rule(rule_id)
            self.rules = list(self.reasoner.engine.rules)
            self.query_cache.clear()
            self._config_version += 1
            self._persist_rules()
            self.record_activity("rule.remove", rule_id=rule_id)
            return removed

    def configure(self, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            proposed = dict(self.config)
            proposed.update({key: value for key, value in updates.items() if value is not None})
            self._validate_config(proposed)
            if proposed["rust_enabled"] and not self._rust_available:
                raise ValueError("rust_enabled cannot be true because Rust availability was not verified")
            old_persistence = self.config["persistence_enabled"]
            self.config = proposed
            self._config_version += 1
            self.query_cache.clear()
            if self.memory.max_bytes != proposed["memory_max_bytes"]:
                self.memory.max_bytes = proposed["memory_max_bytes"]
                try:
                    self.memory._evict_until_within_budget()
                except Exception:
                    self.config["memory_max_bytes"] = self.memory.max_bytes
                    raise
            if old_persistence != proposed["persistence_enabled"] and proposed["persistence_enabled"]:
                self.persist()
            else:
                self._persist_config()
            self.controller = self._new_controller()
            self.reasoner.join_planner = proposed["join_planner"]
            self.record_activity("config.update", fields=sorted(updates))
            return dict(self.config)

    def _cache_key(self, data: dict[str, Any]) -> str:
        encoded = {
            "store_version": self.store.version,
            "rules_version": self.reasoner.rules_version,
            "config_version": self._config_version,
            "input": data,
        }
        return hashlib.sha256(_canonical(encoded)).hexdigest()

    def _solution_dict(self, solution: QuerySolution) -> dict[str, Any]:
        return {
            "key": list(solution.fact_key),
            "object_type": _scalar_type(solution.fact_key[2]),
            "bindings": solution.binding_map(),
            "explicit": solution.explicit_fact_id is not None,
            "fact_id": solution.explicit_fact_id,
            "proofs": [_proof_dict(item) for item in solution.proofs],
            "explanation": [_explanation_dict(solution.explanation)],
        }

    def _derived_solution(self, key: tuple[str, str, Any], engine: InferenceEngine, inferred, *, fact_id: int | None = None) -> dict[str, Any]:
        derived = inferred.by_key(key)
        bindings = engine._match_pattern(key, Pattern(key[0], key[1], key[2]), {}) or {}
        explanation = engine.explain_all(inferred, key)
        return {
            "key": list(key),
            "object_type": _scalar_type(key[2]),
            "bindings": bindings,
            "explicit": fact_id is not None,
            "fact_id": fact_id,
            "proofs": [] if derived is None else [_proof_dict(item) for item in derived.proofs],
            "explanation": [_explanation_dict(item) for item in explanation],
        }

    def query(self, payload: Any) -> dict[str, Any]:
        data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        strategy = data.get("strategy") or self.config["default_strategy"]
        key_data = {
            "subject": _typed_input(data["subject"]), "predicate": data["predicate"], "object": _typed_input(data["object"]),
            "strategy": strategy, "offset": data.get("offset", 0), "limit": data.get("limit", 100),
        }
        cache_key = self._cache_key(key_data)
        with self._lock:
            cache_lookup_start = time.perf_counter_ns()
            cached = self.query_cache.get(cache_key)
            if cached is not None:
                result: dict[str, Any] = json.loads(cached)
                result["cache_hit"] = True
                result["cached_execution_ns"] = result.get("execution_ns")
                result["decision_ns"] = 0
                result["execution_ns"] = 0
                result["cache_lookup_ns"] = time.perf_counter_ns() - cache_lookup_start
                self.queries_executed += 1
                self.last_query_latency_ms = result["cache_lookup_ns"] / 1_000_000
                self.sample_metrics()
                return result
            start = time.perf_counter_ns()
            pattern = Pattern(data["subject"], data["predicate"], data["object"])
            if strategy in {"backward", "hybrid"} and not pattern.is_ground:
                raise ValueError(f"{strategy} strategy requires a ground query; use forward or adaptive for open bindings")
            decision_ns = 0
            rationale = None
            execution_start = time.perf_counter_ns()
            solutions: list[dict[str, Any]] = []
            complete = True
            stop_reason = None
            operations = 0
            facts_examined: int | None = None
            conclusions_produced: int | None = None
            next_offset = None
            actual_strategy = strategy
            if strategy == "forward":
                engine = InferenceEngine(self.store, self.rules, join_planner=self.config["join_planner"])
                query_result: QueryResult = engine.query(pattern, self._limits(), max_results=data["limit"], offset=data["offset"])
                solutions = [self._solution_dict(item) for item in query_result.solutions]
                complete, stop_reason, operations = query_result.complete, query_result.stop_reason, query_result.operations
                facts_examined, conclusions_produced, next_offset = query_result.facts_examined, query_result.conclusions_produced, query_result.next_offset
                rationale = "explicit_forward_query"
            elif strategy in {"backward", "hybrid"}:
                if strategy == "backward":
                    proof = BackwardInference(self.store, self.rules).prove((data["subject"], data["predicate"], data["object"]), BackwardLimits(self.config["max_depth"], self.config["max_operations"]))
                    proven, complete, operations, stop_reason = proof.proven, proof.complete, proof.operations, proof.stop_reason
                    rationale = "ground_backward_proof"
                else:
                    hybrid = HybridInference(self.store, self.rules, join_planner=self.config["join_planner"]).prove((data["subject"], data["predicate"], data["object"]), backward_limits=BackwardLimits(self.config["max_depth"], self.config["max_operations"]), forward_limits=self._limits())
                    proven, complete, operations, stop_reason = hybrid.proven, hybrid.complete, hybrid.operations, hybrid.stop_reason
                    rationale = hybrid.strategy
                engine = InferenceEngine(self.store, self.rules, join_planner=self.config["join_planner"])
                inferred = engine.infer(self._limits())
                direct = self.store.query(subject=data["subject"], predicate=data["predicate"], object=data["object"])
                if proven or direct:
                    if direct:
                        solutions.append(self._derived_solution(direct[0].key, engine, inferred, fact_id=direct[0].fact_id))
                    else:
                        derived = inferred.by_key((data["subject"], data["predicate"], data["object"]))
                        if derived is not None:
                            solutions.append(self._derived_solution(derived.key, engine, inferred))
                operations += inferred.operations
                facts_examined, conclusions_produced = inferred.facts_examined, len(inferred.conclusions)
                actual_strategy = strategy
            elif strategy == "adaptive":
                decision_start = time.perf_counter_ns()
                controller: ControllerResult = self.controller.prove((data["subject"], data["predicate"], data["object"]))
                decision_ns = controller.decision_ns
                actual_strategy = controller.strategy
                rationale = controller.rationale
                complete, stop_reason, operations = controller.complete, controller.stop_reason, controller.operations
                facts_examined, conclusions_produced = controller.facts_examined, controller.conclusions_produced
                if controller.solutions:
                    selected = controller.solutions[data["offset"]:data["offset"] + data["limit"]]
                    solutions = [self._solution_dict(item) for item in selected]
                    if data["offset"] + len(selected) < len(controller.solutions) or (len(selected) == data["limit"] and not complete):
                        next_offset = data["offset"] + len(selected)
                else:
                    engine = InferenceEngine(self.store, self.rules, join_planner=self.config["join_planner"])
                    inferred = engine.infer(self._limits())
                    direct = self.store.query(subject=data["subject"], predicate=data["predicate"], object=data["object"])
                    if controller.proven and direct:
                        solutions = [self._derived_solution(direct[0].key, engine, inferred, fact_id=direct[0].fact_id)]
                    elif controller.proven:
                        derived = inferred.by_key((data["subject"], data["predicate"], data["object"]))
                        if derived is not None:
                            solutions = [self._derived_solution(derived.key, engine, inferred)]
            else:
                raise ValueError("unknown query strategy")
            execution_ns = time.perf_counter_ns() - execution_start
            if decision_ns == 0:
                decision_ns = max(0, time.perf_counter_ns() - start - execution_ns)
            if strategy == "adaptive" and actual_strategy == "forward" and data["offset"] + len(solutions) >= data["limit"] and next_offset is None and not complete:
                next_offset = data["offset"] + len(solutions)
            proven = bool(solutions)
            response_payload = {
                "solutions": solutions,
                "proven": proven,
                "complete": bool(complete),
                "stop_reason": stop_reason,
                "next_offset": next_offset,
                "operations": int(operations),
                "facts_examined": facts_examined,
                "conclusions_produced": conclusions_produced,
                "strategy": actual_strategy,
                "decision_ns": int(decision_ns),
                "execution_ns": int(execution_ns),
                "rationale": rationale,
                "cache_hit": False,
                "cache_lookup_ns": time.perf_counter_ns() - cache_lookup_start,
            }
            self.query_cache.put(cache_key, _canonical(response_payload))
            self.queries_executed += 1
            self.last_query_latency_ms = (time.perf_counter_ns() - start) / 1_000_000
            self.strategy_samples.setdefault(actual_strategy, []).append(self.last_query_latency_ms)
            self.strategy_samples[actual_strategy] = self.strategy_samples[actual_strategy][-512:]
            self.record_activity("query", strategy=actual_strategy, proven=proven)
            self.sample_metrics()
            return response_payload

    def recompute(self) -> dict[str, Any]:
        with self._lock:
            state = self.reasoner.recompute(self._limits())
            self.query_cache.clear()
            self.persist()
            self.record_activity("inference.recompute", complete=state.complete_for_current_store)
            return {
                "complete": state.complete_for_current_store,
                "stop_reason": state.stale_reason,
                "conclusions": [self.conclusion_dict(item) for item in state.result.conclusions],
                "operations": state.result.operations,
                "facts_examined": state.result.facts_examined,
                "conclusions_produced": len(state.result.conclusions),
            }

    def conclusion_dict(self, item) -> dict[str, Any]:
        engine = InferenceEngine(self.store, self.rules, join_planner=self.config["join_planner"])
        return {
            "key": list(item.key),
            "rule_id": item.rule_id,
            "depth": item.depth,
            "supports": [_support_dict(support) for support in item.supports],
            "proofs": [_proof_dict(proof) for proof in item.proofs],
            "explanation": [_explanation_dict(node) for node in engine.explain_all(self.reasoner.state.result, item.key)] if self.reasoner.state is not None else [],
        }

    def explain(self, payload: Any) -> dict[str, Any]:
        data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        with self._lock:
            engine = InferenceEngine(self.store, self.rules, join_planner=self.config["join_planner"])
            inferred = engine.infer(self._limits())
            key = (data["subject"], data["predicate"], data["object"])
            nodes = engine.explain_all(inferred, key)
            return {"key": list(key), "proofs": [_proof_dict(proof) for node in nodes for proof in [branch.proof for branch in node.proofs]], "explanation": [_explanation_dict(node) for node in nodes], "complete": inferred.complete, "stop_reason": inferred.stop_reason}

    def memory_stats(self) -> dict[str, Any]:
        with self._lock:
            stats = self.memory.stats()
            stats["query_cache"] = self.query_cache.stats()
            stats["patterns"] = self.patterns.stats()
            return {**stats, "persistent": self.memory.cold_store is not None}

    def sample_metrics(self) -> dict[str, Any]:
        with self._lock:
            cpu = None
            try:
                import psutil
                if self._process_cpu is None:
                    self._process_cpu = psutil.Process()
                cpu = float(self._process_cpu.cpu_percent(interval=None))
            except Exception:
                cpu = None
            sample = {
                "timestamp_ns": time.time_ns(),
                "cpu_percent": cpu,
                "rss_bytes": current_rss_bytes(),
                "queries": self.queries_executed,
                "events": self.events_processed,
                "last_query_latency_ms": self.last_query_latency_ms,
                "throughput_queries_per_second": None,
                "rust_operations": None,
            }
            if len(self.metric_samples) >= 1:
                previous = self.metric_samples[-1]
                elapsed = (sample["timestamp_ns"] - previous["timestamp_ns"]) / 1_000_000_000
                if elapsed > 0:
                    sample["throughput_queries_per_second"] = max(0.0, (sample["queries"] - previous["queries"]) / elapsed)
            self.metric_samples.append(sample)
            return sample

    def metrics(self, period: int) -> dict[str, Any]:
        with self._lock:
            now = time.time_ns()
            cutoff = now - period * 1_000_000_000
            samples = [item for item in self.metric_samples if item["timestamp_ns"] >= cutoff]
            strategies = []
            for strategy, values in self.strategy_samples.items():
                if not values:
                    strategies.append({"strategy": strategy, "queries": 0, "p50_ms": None, "p95_ms": None, "decision_ns": None, "maintenance_ns": None})
                    continue
                ordered = sorted(values)
                strategies.append({
                    "strategy": strategy,
                    "queries": len(values),
                    "p50_ms": ordered[int((len(ordered) - 1) * 0.50)],
                    "p95_ms": ordered[int((len(ordered) - 1) * 0.95)],
                    "decision_ns": None,
                    "maintenance_ns": None,
                })
            return {"samples": samples, "strategies": strategies, "retention_limit": self.metric_samples.maxlen}

    def status(self) -> dict[str, Any]:
        with self._lock:
            self.sample_metrics()
            stats = self.store.stats()
            state = self.reasoner.state
            complete = bool(state is not None and state.complete_for_current_store)
            return {
                "core": {
                    "status": "ready" if complete else "incomplete",
                    "version": "0.1.0",
                    "entities": stats["entities"],
                    "facts": stats["facts"],
                    "conclusions": len(state.result.conclusions) if complete and state is not None else None,
                    "complete": complete,
                    "stale_reason": None if complete else (state.stale_reason if state is not None else "not_computed"),
                },
                "api": {"status": "ready", "version": "v1", "uptime_seconds": (time.time_ns() - self.started_ns) / 1_000_000_000},
                "rust": self.rust_status(),
                "queries_executed": self.queries_executed,
                "events_processed": self.events_processed,
                "last_query_latency_ms": self.last_query_latency_ms,
                "memory": self.memory_stats(),
                "cpu_percent": self.metric_samples[-1]["cpu_percent"] if self.metric_samples else None,
                "activity": list(self.activity),
                "alerts": list(self.alerts),
            }

    def close(self) -> None:
        with self._lock:
            try:
                self.persist()
            finally:
                self.events.close()
                self.memory.close()
