#!/usr/bin/env python3
"""Reproducible Phase 8 workloads, independent oracle and paired baselines.

Default run: 10 synthetic workload families x 30 seeds, one controller session
per seed, three calibration queries followed by five holdout queries. Holdout
does not update cost/completion estimates, while the query-history counter still
advances as an observed feature. Rust timings cover conversion and native
construction only; no end-to-end speed claim is made from kernel timings.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from aether.reasoning.backward import BackwardInference, BackwardLimits
from aether.reasoning.consistency import ConsistencyValidator, IncompatibilityRule
from aether.reasoning.hybrid import HybridInference
from aether.reasoning.inference import InferenceEngine, InferenceLimits, Pattern, Rule
from aether.reasoning.incremental import IncrementalInference
from aether.core.knowledge.store import (
    KnowledgeStore,
    Provenance,
    fact_key_identity,
    scalar_equal,
    scalar_identity,
)
from aether.graph.indexing.rust_knowledge import RustKnowledgeIndex
from aether.metrics import cpu_model, current_rss_bytes, peak_rss_bytes, total_physical_memory_bytes
from aether.reasoning.controller import AdaptiveReasoningController

FAMILIES = (
    "sparse_graphs",
    "dense_graphs",
    "dependency_chains",
    "multiple_relations",
    "multiple_proofs",
    "contradictions",
    "open_variable_queries",
    "frequent_insertions",
    "frequent_removals",
    "rule_changes",
)
CALIBRATION_QUERIES = 3
HOLDOUT_QUERIES = 5
TOTAL_QUERIES = CALIBRATION_QUERIES + HOLDOUT_QUERIES
PROVENANCE = Provenance("aether-phase8-synthetic", evidence_type="generated_fixture")
FORWARD_LIMITS = InferenceLimits(max_depth=16, max_operations=200_000, max_conclusions=50_000)
BACKWARD_LIMITS = BackwardLimits(max_depth=16, max_operations=200_000)


def _add_entities(store: KnowledgeStore, count: int = 10, seed: int = 0) -> list[str]:
    ids = [f"n{i}" for i in range(count)]
    for item in ids:
        store.add_entity(item, {"fixture": "phase8", "node": int(item[1:]), "seed": seed})
    return ids


def _add_edge(store: KnowledgeStore, source: str, target: str, predicate: str = "edge"):
    return store.add_fact(source, predicate, target, provenance=PROVENANCE)[0]


def _reach_rules(predicate: str = "edge", target: str = "reach") -> list[Rule]:
    return [
        Rule("direct-reach", (Pattern("?x", predicate, "?y"),), Pattern("?x", target, "?y")),
        Rule(
            "transitive-reach",
            (Pattern("?x", target, "?y"), Pattern("?y", predicate, "?z")),
            Pattern("?x", target, "?z"),
        ),
    ]


def _pattern_match(key, pattern: Pattern, bindings: dict):
    if key[1] != pattern.predicate:
        return None
    updated = dict(bindings)
    for value, expected in ((key[0], pattern.subject), (key[2], pattern.object)):
        if isinstance(expected, str) and expected.startswith("?"):
            if expected in updated:
                if not scalar_equal(updated[expected], value):
                    return None
            else:
                updated[expected] = value
        elif not scalar_equal(value, expected):
            return None
    return updated


def oracle_closure(store: KnowledgeStore, rules: tuple[Rule, ...] | list[Rule]):
    """Independent exhaustive fixed-point evaluator (does not call AETHER joins)."""
    known = {fact_key_identity(fact.key): fact.key for fact in store.query()}
    for _round in range(64):
        changed = False
        snapshot = tuple(known.values())
        for rule in rules:
            if not rule.enabled:
                continue
            partials = [({}, ())]
            for antecedent in rule.antecedents:
                next_partials = []
                for bindings, supports in partials:
                    for candidate in snapshot:
                        matched = _pattern_match(candidate, antecedent, bindings)
                        if matched is not None:
                            next_partials.append((matched, supports + (candidate,)))
                partials = next_partials
                if not partials:
                    break
            for bindings, _supports in partials:
                def resolve(value):
                    if isinstance(value, str) and value.startswith("?"):
                        return bindings[value]
                    return value
                derived_key = (resolve(rule.consequent.subject), rule.consequent.predicate, resolve(rule.consequent.object))
                identity = fact_key_identity(derived_key)
                if identity not in known:
                    known[identity] = derived_key
                    changed = True
        if not changed:
            return tuple(known.values())
    raise RuntimeError("independent oracle did not reach a fixed point within 64 rounds")


def oracle_bindings(keys, pattern: Pattern):
    result = {}
    for key in keys:
        bindings = _pattern_match(key, pattern, {})
        if bindings is None:
            continue
        identity = tuple((name, scalar_identity(value)) for name, value in sorted(bindings.items()))
        result[identity] = tuple(sorted(bindings.items()))
    return tuple(result[key] for key in sorted(result))


def snapshot_hash(store: KnowledgeStore, rules) -> str:
    payload = {
        "entities": [
            (entity.entity_id, [(name, value) for name, value in entity.properties])
            for entity in store.entities()
        ],
        "facts": [
            (fact.subject, fact.predicate, fact.object, fact.fact_id)
            for fact in store.query()
        ],
        "rules": [
            {
                "id": rule.rule_id,
                "revision": rule.revision,
                "enabled": rule.enabled,
                "antecedents": [(p.subject, p.predicate, p.object) for p in rule.antecedents],
                "consequent": (rule.consequent.subject, rule.consequent.predicate, rule.consequent.object),
            }
            for rule in rules
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass
class Workload:
    family: str
    seed: int
    store: KnowledgeStore
    rules: list[Rule]
    goals: list[tuple[str, str, object]]
    actions: dict[int, tuple]
    metadata: dict
    incompatibilities: tuple[IncompatibilityRule, ...] = ()
    removal_fact_ids: tuple[int, ...] = ()


def _sample_ground_goals(store: KnowledgeStore, rules, predicate: str, rng: random.Random, count: int):
    known = oracle_closure(store, rules)
    positive = [key for key in known if key[1] == predicate]
    if not positive:
        positive = [fact.key for fact in store.query(predicate=predicate)]
    entities = [entity.entity_id for entity in store.entities()]
    objects = sorted({key[2] for key in positive if isinstance(key[2], str)})
    negative = [
        (subject, predicate, obj)
        for subject in entities for obj in objects
        if fact_key_identity((subject, predicate, obj)) not in {fact_key_identity(key) for key in known}
    ]
    choices = positive + negative
    if not choices:
        choices = [(entities[0], predicate, entities[-1])]
    return [rng.choice(choices) for _ in range(count)]


def make_workload(family: str, seed: int) -> Workload:
    rng = random.Random(seed)
    store = KnowledgeStore()
    nodes = _add_entities(store, seed=seed)
    rules: list[Rule] = []
    goals: list[tuple[str, str, object]] = []
    actions: dict[int, tuple] = {}
    metadata: dict = {"nodes": len(nodes), "seed": seed}
    incompatibilities: tuple[IncompatibilityRule, ...] = ()
    removal_ids: tuple[int, ...] = ()

    if family == "sparse_graphs":
        for source in nodes:
            for target in nodes:
                if source != target and rng.random() < 0.12:
                    _add_edge(store, source, target)
        rules = _reach_rules()
        goals = _sample_ground_goals(store, rules, "reach", rng, TOTAL_QUERIES)
    elif family == "dense_graphs":
        for source in nodes:
            for target in nodes:
                if source != target and rng.random() < 0.42:
                    _add_edge(store, source, target)
        rules = _reach_rules()
        goals = _sample_ground_goals(store, rules, "reach", rng, TOTAL_QUERIES)
    elif family == "dependency_chains":
        path = rng.sample(nodes, len(nodes))
        for source, target in zip(path[:-1], path[1:]):
            _add_edge(store, source, target)
        rules = _reach_rules()
        goals = _sample_ground_goals(store, rules, "reach", rng, TOTAL_QUERIES)
    elif family == "multiple_relations":
        for source in nodes:
            for target in nodes:
                if source != target and rng.random() < 0.17:
                    _add_edge(store, source, target, "edge")
                if source != target and rng.random() < 0.10:
                    _add_edge(store, source, target, "follows")
        rules = [
            Rule("edge-related", (Pattern("?x", "edge", "?y"),), Pattern("?x", "related", "?y")),
            Rule("follows-related", (Pattern("?x", "follows", "?y"),), Pattern("?x", "related", "?y")),
            Rule("related-via-edge", (Pattern("?x", "related", "?y"), Pattern("?y", "edge", "?z")), Pattern("?x", "related", "?z")),
        ]
        goals = _sample_ground_goals(store, rules, "related", rng, TOTAL_QUERIES)
    elif family == "multiple_proofs":
        target_node, left_subject, left_object, right_subject, right_object = rng.sample(nodes, 5)
        _add_edge(store, "n5", "n6")
        _add_edge(store, left_subject, left_object, "left_support")
        _add_edge(store, right_subject, right_object, "right_support")
        rules = [
            Rule("proof-left", (Pattern(left_subject, "left_support", left_object),), Pattern(target_node, "ready", True)),
            Rule("proof-right", (Pattern(right_subject, "right_support", right_object),), Pattern(target_node, "ready", True)),
        ]
        goals = [(target_node, "ready", True)] * TOTAL_QUERIES
    elif family == "contradictions":
        _add_edge(store, "n8", "n9")
        conflict_subject = rng.choice(nodes)
        store.add_fact(conflict_subject, "alive", True, provenance=PROVENANCE)
        store.add_fact(conflict_subject, "dead", True, provenance=Provenance("independent-synthetic-source", evidence_type="generated_fixture"))
        incompatibilities = (IncompatibilityRule("alive", "dead", ((True, True),)),)
        consistency = ConsistencyValidator(store)
        assessment = consistency.assess((conflict_subject, "alive", True), incompatibilities=incompatibilities)
        metadata["contradiction_status"] = assessment.status.value
        metadata["conflicting_fact_ids"] = list(assessment.conflicting_fact_ids)
        goals = [
            (conflict_subject, "alive", True), (conflict_subject, "dead", True), (conflict_subject, "unknown", True),
            (conflict_subject, "alive", True), (conflict_subject, "dead", True), (conflict_subject, "unknown", True),
            (conflict_subject, "alive", True), (conflict_subject, "dead", True),
        ][:TOTAL_QUERIES]
    elif family == "open_variable_queries":
        for source in nodes:
            for target in nodes:
                if source != target and rng.random() < 0.22:
                    _add_edge(store, source, target)
        rules = _reach_rules()
        goals = [("?x", "reach", "?y")] * TOTAL_QUERIES
    elif family == "frequent_insertions":
        path = rng.sample(nodes, len(nodes))
        _add_edge(store, path[0], path[1])
        rules = _reach_rules()
        for target_index in range(2, 2 + TOTAL_QUERIES):
            goals.append((path[0], "reach", path[target_index]))
            actions[len(goals) - 1] = ("insert", path[target_index - 1], path[target_index])
    elif family == "frequent_removals":
        path = rng.sample(nodes, len(nodes))
        facts = [_add_edge(store, source, target) for source, target in zip(path[:-1], path[1:])]
        rules = _reach_rules()
        removal_ids = tuple(fact.fact_id for fact in facts)
        for index, fact_id in enumerate(removal_ids[:TOTAL_QUERIES]):
            actions[index] = ("remove", fact_id)
            if index < CALIBRATION_QUERIES:
                goals.append((path[index + 1], "reach", path[-1]))
            else:
                goals.append((path[0], "reach", path[-1]))
    elif family == "rule_changes":
        subject = nodes[seed % len(nodes)]
        target = nodes[(seed + 3) % len(nodes)]
        _add_edge(store, subject, target)
        rules = [Rule("projection", (Pattern("?x", "edge", "?y"),), Pattern("?x", "reach", "?y"))]
        goals = [(subject, "connected", target)] * TOTAL_QUERIES
        metadata["warmup_goal"] = (subject, "reach", target)
        metadata["replacement_rule"] = Rule(
            "projection", (Pattern("?x", "edge", "?y"),), Pattern("?x", "connected", "?y")
        )
    else:
        raise ValueError(f"unknown workload family: {family}")

    if len(goals) != TOTAL_QUERIES:
        raise AssertionError(f"{family} generated {len(goals)} goals, expected {TOTAL_QUERIES}")
    return Workload(family, seed, store, rules, goals, actions, metadata, incompatibilities, removal_ids)


def percentile95(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    return values[max(0, math.ceil(0.95 * len(values)) - 1)]


def median(values):
    usable = [value for value in values if value is not None]
    return statistics.median(usable) if usable else None


def _result_for(strategy, controller, goal):
    started = time.perf_counter_ns()
    proven, complete, operations, stop_reason, solutions, facts_examined, conclusions = controller._run(strategy, goal)
    elapsed = time.perf_counter_ns() - started
    return {
        "strategy": strategy,
        "proven": bool(proven),
        "complete": bool(complete),
        "operations": operations,
        "facts_examined": facts_examined,
        "conclusions_produced": conclusions,
        "stop_reason": stop_reason,
        "execution_ns": elapsed,
        "solutions": solutions,
    }


def _apply_action(workload: Workload, index: int, controller, incremental, rust_index):
    action = workload.actions.get(index)
    if action is None:
        return 0, 0, 0, None
    started = time.perf_counter_ns()
    if action[0] == "insert":
        _, inserted = incremental.add_fact(action[1], "edge", action[2], provenance=PROVENANCE)
        if not inserted.inserted:
            raise AssertionError("insertion workload unexpectedly produced duplicate fact")
        maintenance_ns = time.perf_counter_ns() - started
        new_fact = workload.store.query(subject=action[1], predicate="edge", object=action[2])[0]
        started_recompute = time.perf_counter_ns()
        full = InferenceEngine(workload.store, controller.rules).infer(FORWARD_LIMITS)
        recompute_ns = time.perf_counter_ns() - started_recompute
        incremental_result = incremental.result()
        incremental_keys = {fact.identity for fact in incremental_result.conclusions}
        full_keys = {fact.identity for fact in full.conclusions}
        incremental_parity = int(incremental_result.complete and full.complete and incremental_keys == full_keys)
        if rust_index is not None:
            rust_start = time.perf_counter_ns()
            rust_index.refresh()
            rust_refresh_ns = time.perf_counter_ns() - rust_start
        else:
            rust_refresh_ns = None
        return maintenance_ns, recompute_ns, rust_refresh_ns, incremental_parity
    if action[0] == "remove":
        workload.store.remove_fact(action[1])
        maintenance_ns = time.perf_counter_ns() - started
        started_recompute = time.perf_counter_ns()
        InferenceEngine(workload.store, controller.rules).infer(FORWARD_LIMITS)
        recompute_ns = time.perf_counter_ns() - started_recompute
        if rust_index is not None:
            rust_start = time.perf_counter_ns()
            rust_index.refresh()
            rust_refresh_ns = time.perf_counter_ns() - rust_start
        else:
            rust_refresh_ns = None
        return maintenance_ns, recompute_ns, rust_refresh_ns, None
    raise ValueError(f"unsupported action: {action[0]}")


def _session(family: str, seed: int):
    workload = make_workload(family, seed)
    memory_start = current_rss_bytes()
    controller = AdaptiveReasoningController(
        workload.store,
        workload.rules,
        backward_limits=BACKWARD_LIMITS,
        forward_limits=FORWARD_LIMITS,
        max_query_results=50_000,
    )
    initial_hash = snapshot_hash(workload.store, workload.rules)
    rust_index = None
    rust_build = {}
    try:
        rust_index = RustKnowledgeIndex(workload.store, "edge")
        rust_build = {
            "available": True,
            "conversion_ns": rust_index.conversion_ns,
            "native_build_ns": rust_index.rust_build_ns,
            "snapshot_version": rust_index.store_version,
            "edge_count": rust_index.build.facts,
        }
        controller.index_build_ns = rust_index.conversion_ns + rust_index.rust_build_ns
    except Exception as exc:  # unavailable native toolchain is reported, never hidden
        rust_build = {"available": False, "error": f"{type(exc).__name__}: {exc}"}

    rule_change_ns = None
    if family == "rule_changes":
        warm_goal = tuple(workload.metadata["warmup_goal"])
        for _ in range(3):
            controller.prove(warm_goal, learn=True)
        started = time.perf_counter_ns()
        replacement_rule = workload.metadata["replacement_rule"]
        controller.replace_rule("projection", replacement_rule)
        rule_change_ns = time.perf_counter_ns() - started
        controller.observe_maintenance(rule_change_ns)
        workload.rules = list(controller.rules)

    incremental = IncrementalInference(workload.store, controller.rules)
    incremental.initialize(FORWARD_LIMITS)
    rows = []
    parity_checks = parity_failures = oracle_mismatches = 0
    for index, goal in enumerate(workload.goals):
        split = "calibration" if index < CALIBRATION_QUERIES else "holdout"
        maintenance_ns, action_recompute_ns, rust_refresh_ns, incremental_parity = _apply_action(
            workload, index, controller, incremental, rust_index
        )
        if maintenance_ns and split == "calibration":
            controller.observe_maintenance(maintenance_ns + (rust_refresh_ns or 0))
        if incremental_parity is not None:
            parity_checks += 1
            parity_failures += 1 - incremental_parity

        current_hash = snapshot_hash(workload.store, controller.rules)
        oracle = oracle_closure(workload.store, controller.rules)
        full_started = time.perf_counter_ns()
        full_result = InferenceEngine(workload.store, controller.rules).infer(FORWARD_LIMITS)
        recompute_ns = time.perf_counter_ns() - full_started
        oracle_ids = {fact_key_identity(key) for key in oracle}
        engine_ids = {fact.identity for fact in full_result.conclusions}
        explicit_ids = {fact_key_identity(fact.key) for fact in workload.store.query()}
        engine_semantics = engine_ids | explicit_ids
        oracle_match = full_result.complete and engine_semantics == oracle_ids
        if not oracle_match:
            oracle_mismatches += 1

        pattern = Pattern(*goal)
        expected_bindings = oracle_bindings(oracle, pattern) if not pattern.is_ground else ()
        expected_proven = fact_key_identity(goal) in oracle_ids if pattern.is_ground else bool(expected_bindings)
        rss_before = current_rss_bytes()
        controller_result = controller.prove(goal, learn=(split == "calibration"))
        rss_after = current_rss_bytes()
        if pattern.is_ground:
            controller_matches_oracle = controller_result.proven == expected_proven if controller_result.complete else None
            returned_bindings = ()
        else:
            returned_bindings = tuple(solution.bindings for solution in controller_result.solutions)
            binding_ids = {
                tuple((name, scalar_identity(value)) for name, value in bindings)
                for bindings in returned_bindings
            }
            expected_ids = {
                tuple((name, scalar_identity(value)) for name, value in bindings)
                for bindings in expected_bindings
            }
            controller_matches_oracle = binding_ids == expected_ids if controller_result.complete else None
        if controller_matches_oracle is False:
            oracle_mismatches += 1

        baselines = {}
        comparable_baselines = {}
        selected_fastest = None
        suboptimal = None
        if split == "holdout":
            strategies = ("forward",) if not pattern.is_ground else ("backward", "hybrid", "forward")
            order = list(strategies)
            random.Random(seed * 101 + index).shuffle(order)
            for strategy in order:
                baseline = _result_for(strategy, controller, goal)
                if pattern.is_ground:
                    baseline_matches = baseline["proven"] == expected_proven
                else:
                    baseline_ids = {
                        tuple((name, scalar_identity(value)) for name, value in solution.bindings)
                        for solution in baseline["solutions"]
                    }
                    expected_ids = {
                        tuple((name, scalar_identity(value)) for name, value in bindings)
                        for bindings in expected_bindings
                    }
                    baseline_matches = baseline_ids == expected_ids
                baseline["semantic_match"] = bool(baseline["complete"] and baseline_matches)
                if baseline["complete"] and not baseline_matches:
                    oracle_mismatches += 1
                baselines[strategy] = baseline
                if baseline["semantic_match"]:
                    comparable_baselines[strategy] = baseline
            if comparable_baselines and controller_result.complete and controller_matches_oracle:
                selected_fastest = min(
                    comparable_baselines,
                    key=lambda name: (comparable_baselines[name]["execution_ns"], name),
                )
                suboptimal = int(controller_result.strategy != selected_fastest)

        rows.append({
            "family": family,
            "seed": seed,
            "session_id": f"{family}:{seed}",
            "step": index,
            "split": split,
            "goal": json.dumps(goal, ensure_ascii=False, separators=(",", ":")),
            "rule_version": controller.rules_version,
            "dataset_sha256": current_hash,
            "initial_dataset_sha256": initial_hash,
            "oracle_expected_proven": int(expected_proven),
            "oracle_solution_count": len(expected_bindings) if not pattern.is_ground else int(expected_proven),
            "oracle_full_result_match": int(oracle_match),
            "controller_strategy": controller_result.strategy,
            "controller_proven": int(controller_result.proven),
            "controller_complete": int(controller_result.complete),
            "controller_matches_oracle": "" if controller_matches_oracle is None else int(controller_matches_oracle),
            "controller_operations": controller_result.operations,
            "controller_facts_examined": controller_result.facts_examined,
            "controller_conclusions_produced": controller_result.conclusions_produced,
            "controller_decision_ns": controller_result.decision_ns,
            "controller_execution_ns": controller_result.execution_ns,
            "controller_total_ns": controller_result.total_ns,
            "controller_stop_reason": controller_result.stop_reason or "",
            "controller_rationale": controller_result.rationale,
            "features": json.dumps(controller_result.features.__dict__ if controller_result.features else {}, sort_keys=True),
            "controller_solution_count": len(controller_result.solutions),
            "returned_bindings": json.dumps(returned_bindings, ensure_ascii=False),
            "holdout_selected_fastest_fixed": selected_fastest or "",
            "holdout_suboptimal_choice": "" if suboptimal is None else suboptimal,
            "holdout_comparable_strategy_count": len(comparable_baselines),
            "baseline_execution_ns": json.dumps({name: item["execution_ns"] for name, item in comparable_baselines.items()}, sort_keys=True),
            "baseline_results": json.dumps({name: {key: value for key, value in item.items() if key != "solutions"} for name, item in baselines.items()}, sort_keys=True),
            "maintenance_ns": maintenance_ns,
            "recomputation_ns": action_recompute_ns if action_recompute_ns else recompute_ns,
            "recomputation_complete": int(full_result.complete),
            "incremental_parity": "" if incremental_parity is None else incremental_parity,
            "rss_before_bytes": rss_before,
            "rss_after_bytes": rss_after,
            "rss_delta_bytes": None if rss_before is None or rss_after is None else rss_after - rss_before,
            "peak_rss_bytes": peak_rss_bytes(),
            "rust_conversion_ns": rust_build.get("conversion_ns"),
            "rust_native_build_ns": rust_build.get("native_build_ns"),
            "rust_refresh_ns": rust_refresh_ns,
            "rust_available": int(rust_build.get("available", False)),
        })

    if rust_index is not None:
        rust_index.close()
    summary = {
        "family": family,
        "seed": seed,
        "initial_dataset_sha256": initial_hash,
        "final_dataset_sha256": snapshot_hash(workload.store, controller.rules),
        "metadata": {
            key: value for key, value in workload.metadata.items()
            if key != "replacement_rule"
        } | ({
            "replacement_rule": {
                "rule_id": replacement_rule.rule_id,
                "revision": replacement_rule.revision,
                "consequent": (replacement_rule.consequent.subject, replacement_rule.consequent.predicate, replacement_rule.consequent.object),
            }
        } if family == "rule_changes" else {}),
        "rust_build": rust_build,
        "rule_change_ns": rule_change_ns,
        "memory_start_bytes": memory_start,
        "memory_end_bytes": current_rss_bytes(),
        "peak_rss_bytes": peak_rss_bytes(),
        "parity_checks": parity_checks,
        "parity_failures": parity_failures,
        "oracle_mismatches": oracle_mismatches,
        "holdout_strategy_sequence": [row["controller_strategy"] for row in rows if row["split"] == "holdout"],
        "rows": rows,
    }
    return summary


def _aggregate(rows):
    holdout = [row for row in rows if row["split"] == "holdout"]
    adaptive_total = [row["controller_total_ns"] for row in holdout]
    adaptive_decision = [row["controller_decision_ns"] for row in holdout]
    adaptive_execution = [row["controller_execution_ns"] for row in holdout]
    strategy_values = {name: [] for name in ("backward", "hybrid", "forward")}
    for row in holdout:
        for name, value in json.loads(row["baseline_execution_ns"]).items():
            strategy_values[name].append(value)
    comparisons = {}
    for name, values in strategy_values.items():
        paired_rows = [
            row for row in holdout
            if name in json.loads(row["baseline_execution_ns"])
        ]
        fixed_values = [json.loads(row["baseline_execution_ns"])[name] for row in paired_rows]
        paired_adaptive = [row["controller_total_ns"] for row in paired_rows]
        deltas = [adaptive - fixed for adaptive, fixed in zip(paired_adaptive, fixed_values)]
        adaptive_median = median(paired_adaptive)
        fixed_median = median(fixed_values)
        median_delta = median(deltas)
        comparisons[name] = {
            "n_comparable": len(paired_rows),
            "median_fixed_execution_ns": fixed_median,
            "p95_fixed_execution_ns": percentile95(fixed_values),
            "median_adaptive_total_ns": adaptive_median,
            "median_paired_delta_ns": median_delta,
            "adaptive_faster_fraction": None if not deltas else sum(delta < 0 for delta in deltas) / len(deltas),
            "adaptive_outcome": "not_comparable" if median_delta is None else (
                "better" if median_delta < 0 else "worse" if median_delta > 0 else "equal"
            ),
        }
    valid_choice_rows = [row for row in holdout if row["holdout_suboptimal_choice"] != ""]
    strategy_changes = sum(
        left != right for left, right in zip(
            [row["controller_strategy"] for row in holdout],
            [row["controller_strategy"] for row in holdout][1:],
        )
    )
    return {
        "holdout_queries": len(holdout),
        "controller_all_complete": all(row["controller_complete"] for row in holdout),
        "controller_oracle_mismatches": sum(row["controller_matches_oracle"] == 0 for row in holdout),
        "median_controller_total_ns": median(adaptive_total),
        "p95_controller_total_ns": percentile95(adaptive_total),
        "median_controller_decision_ns": median(adaptive_decision),
        "median_controller_execution_ns": median(adaptive_execution),
        "median_operations": median([row["controller_operations"] for row in holdout]),
        "median_facts_examined": median([row["controller_facts_examined"] for row in holdout]),
        "median_conclusions_produced": median([row["controller_conclusions_produced"] for row in holdout]),
        "selected_fastest_fixed_fraction": None if not valid_choice_rows else 1.0 - sum(int(row["holdout_suboptimal_choice"]) for row in valid_choice_rows) / len(valid_choice_rows),
        "suboptimal_choice_count": sum(int(row["holdout_suboptimal_choice"]) for row in valid_choice_rows),
        "suboptimal_choice_denominator": len(valid_choice_rows),
        "strategy_changes": strategy_changes,
        "strategy_change_rate": None if len(holdout) < 2 else strategy_changes / (len(holdout) - 1),
        "fixed_baseline_comparisons": comparisons,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="results/phase8")
    parser.add_argument("--seeds", type=int, default=30, help="seeds per workload family; acceptance target is 30")
    parser.add_argument("--families", nargs="*", choices=FAMILIES, default=list(FAMILIES))
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error("--seeds must be at least 1")
    if len(args.families) != len(set(args.families)):
        parser.error("--families cannot contain duplicates")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    all_rows = []
    sessions = []
    session_count = 0
    for family_index, family in enumerate(args.families):
        for seed_index in range(args.seeds):
            seed = family_index * 1_000_000 + seed_index
            session = _session(family, seed)
            session_count += 1
            all_rows.extend(session["rows"])
            sessions.append({key: value for key, value in session.items() if key != "rows"})
            print(f"completed {family} seed={seed_index + 1}/{args.seeds} oracle_mismatches={session['oracle_mismatches']}", flush=True)

    fields = list(all_rows[0]) if all_rows else []
    with (out / "runs.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)

    family_summaries = {}
    for family in args.families:
        family_rows = [row for row in all_rows if row["family"] == family]
        family_sessions = [session for session in sessions if session["family"] == family]
        family_summaries[family] = {
            "seed_count": args.seeds,
            "calibration_queries": sum(row["split"] == "calibration" for row in family_rows),
            "holdout_queries": sum(row["split"] == "holdout" for row in family_rows),
            "unique_dataset_hashes": len({session["initial_dataset_sha256"] for session in family_sessions}),
            "oracle_mismatches": sum(session["oracle_mismatches"] for session in family_sessions),
            "incremental_parity_checks": sum(session["parity_checks"] for session in family_sessions),
            "incremental_parity_failures": sum(session["parity_failures"] for session in family_sessions),
            "median_rust_conversion_ns": median([session["rust_build"].get("conversion_ns") for session in family_sessions]),
            "median_rust_native_build_ns": median([session["rust_build"].get("native_build_ns") for session in family_sessions]),
            "median_rule_change_ns": median([session["rule_change_ns"] for session in family_sessions]),
            "median_session_memory_end_bytes": median([session["memory_end_bytes"] for session in family_sessions]),
            "holdout": _aggregate(family_rows),
        }

    metadata = {
        "project": "AETHER Phase 8",
        "benchmark": "phase8_bench.py",
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_model": cpu_model(),
        "total_physical_memory_bytes": total_physical_memory_bytes(),
        "seeds_per_family": args.seeds,
        "acceptance_seed_target": 30,
        "meets_seed_target": args.seeds >= 30,
        "families": list(args.families),
        "calibration_queries_per_session": CALIBRATION_QUERIES,
        "holdout_queries_per_session": HOLDOUT_QUERIES,
        "holdout_learning_enabled": False,
        "sessions": session_count,
        "synthetic_data_only": True,
        "oracles": "independent exhaustive fixed-point evaluator plus full InferenceEngine recomputation",
        "rust_measurement_scope": "conversion and native graph construction/refresh only; no end-to-end superiority claim",
        "note": "No external benchmark data or confidence probabilities are fabricated; unavailable metrics remain null.",
    }
    summary = {
        "metadata": metadata,
        "totals": {
            "rows": len(all_rows),
            "oracle_mismatches": sum(session["oracle_mismatches"] for session in sessions),
            "incremental_parity_checks": sum(session["parity_checks"] for session in sessions),
            "incremental_parity_failures": sum(session["parity_failures"] for session in sessions),
            "holdout_controller_incomplete": sum(
                row["split"] == "holdout" and not row["controller_complete"] for row in all_rows
            ),
        },
        "families": family_summaries,
        "sessions": sessions,
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary["totals"], indent=2, sort_keys=True))
    print(f"wrote {out / 'runs.csv'} and {out / 'summary.json'}")


if __name__ == "__main__":
    main()
