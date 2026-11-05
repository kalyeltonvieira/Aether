#!/usr/bin/env python3
"""Paired join-planner benchmark with independent equivalence checks.

Runs 30 seeds for selective and balanced three-way joins, reports calibration
and holdout separately, and keeps execution time separate from examined facts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

try:
    import resource
except ImportError:  # Windows does not expose the POSIX resource module.
    resource = None

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aether.core.knowledge.store import KnowledgeStore
from aether.reasoning.inference import InferenceEngine, InferenceLimits, Pattern, Rule

FAMILIES = ("selective_join", "balanced_join")
REPEATS = 3
SEEDS_PER_FAMILY = 30
LIMITS = InferenceLimits(max_depth=8, max_operations=500_000, max_conclusions=50_000)


def make_workload(family: str, seed: int):
    rng = random.Random(seed)
    store = KnowledgeStore()
    if family == "selective_join":
        n = 300 + rng.randrange(201)
        entities = [f"source-{seed}-{index}" for index in range(n)] + [f"person-{seed}", f"key-{seed}"]
        for entity in entities:
            store.add_entity(entity)
        order = list(range(n))
        rng.shuffle(order)
        for index in order:
            store.add_fact(f"source-{seed}-{index}", "broad", f"sink-{index}")
        store.add_fact(f"person-{seed}", "broad", f"target-{seed}")
        store.add_fact(f"person-{seed}", "narrow", f"key-{seed}")
        store.add_fact(f"key-{seed}", "target", f"target-{seed}")
        rule = Rule(
            "three-way-selective",
            (
                Pattern("?x", "broad", "?y"),
                Pattern("?x", "narrow", "?z"),
                Pattern("?z", "target", "?y"),
            ),
            Pattern("?x", "reachable", "?y"),
        )
        metadata = {"broad_facts": n + 1, "narrow_facts": 1, "target_facts": 1}
    elif family == "balanced_join":
        n = 60 + rng.randrange(31)
        names = []
        for index in range(n):
            names.extend((f"x-{seed}-{index}", f"y-{seed}-{index}", f"z-{seed}-{index}"))
        for entity in names:
            store.add_entity(entity)
        rows = list(range(n))
        rng.shuffle(rows)
        for index in rows:
            x, y, z, w = (
                f"x-{seed}-{index}", f"y-{seed}-{index}",
                f"z-{seed}-{index}", f"w-{seed}-{index}",
            )
            store.add_fact(x, "p1", y)
            store.add_fact(y, "p2", z)
            store.add_fact(z, "p3", w)
        rule = Rule(
            "three-way-balanced",
            (
                Pattern("?x", "p1", "?y"),
                Pattern("?y", "p2", "?z"),
                Pattern("?z", "p3", "?w"),
            ),
            Pattern("?x", "path_end", "?w"),
        )
        metadata = {"p1_facts": n, "p2_facts": n, "p3_facts": n}
    else:
        raise ValueError(f"unknown family: {family}")
    return store, rule, metadata


def _proof_signature(result):
    return tuple(
        (
            fact.key,
            tuple(
                (proof.rule_id, proof.rule_revision, proof.depth, proof.supports)
                for proof in fact.proofs
            ),
        )
        for fact in result.conclusions
    )


def run_once(store, rule, planner):
    engine = InferenceEngine(store, [rule], join_planner=planner)
    started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    result = engine.infer(LIMITS)
    cpu_ns = time.process_time_ns() - cpu_started
    elapsed_ns = time.perf_counter_ns() - started
    return {
        "elapsed_ns": elapsed_ns,
        "cpu_ns": cpu_ns,
        "facts_examined": result.facts_examined,
        "operations": result.operations,
        "conclusions": len(result.conclusions),
        "complete": result.complete,
        "stop_reason": result.stop_reason,
        "signature": _proof_signature(result),
        "plan_order": () if engine.last_join_plan is None else engine.last_join_plan.order,
        "plan_estimates": () if engine.last_join_plan is None else engine.last_join_plan.candidate_estimates,
    }


def _percentile(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def summarize(records):
    output = {}
    for family in FAMILIES:
        rows = [record for record in records if record["family"] == family]
        output[family] = {}
        for planner in ("input", "selective"):
            values = [record[planner] for record in rows]
            times = [item["median_elapsed_ns"] for item in values]
            examined = [item["facts_examined"] for item in values]
            output[family][planner] = {
                "runs": len(values),
                "p50_elapsed_ns": int(statistics.median(times)),
                "p95_elapsed_ns_observed": int(_percentile(times, 0.95)),
                "queries_per_second_at_p50": 1_000_000_000 / max(1, int(statistics.median(times))),
                "p50_cpu_ns": int(statistics.median(item["median_cpu_ns"] for item in values)),
                "p50_facts_examined": int(statistics.median(examined)),
                "p95_facts_examined_observed": int(_percentile(examined, 0.95)),
            }
        by_seed = {record["seed_index"]: record for record in rows}
        for segment, indices in (
            ("calibration", set(range(20))),
            ("holdout", set(range(20, 30))),
        ):
            paired = [by_seed[index] for index in sorted(indices) if index in by_seed]
            ratios = [item["input"]["median_elapsed_ns"] / max(1, item["selective"]["median_elapsed_ns"]) for item in paired]
            cpu_ratios = [
                item["input"]["median_cpu_ns"] / max(1, item["selective"]["median_cpu_ns"])
                for item in paired
            ]
            reductions = [
                1 - item["selective"]["facts_examined"] / max(1, item["input"]["facts_examined"])
                for item in paired
            ]
            wins = sum(item["selective"]["median_elapsed_ns"] < item["input"]["median_elapsed_ns"] for item in paired)
            output[family][segment] = {
                "seeds": len(paired),
                "median_input_over_selective_speedup": statistics.median(ratios) if ratios else None,
                "median_input_over_selective_cpu_speedup": statistics.median(cpu_ratios) if cpu_ratios else None,
                "median_examined_reduction_fraction": statistics.median(reductions) if reductions else None,
                "selective_latency_wins": wins,
                "selective_latency_win_rate": wins / len(paired) if paired else None,
            }
    return output


def _git_head():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, check=True,
        ).stdout.strip()
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "results" / "evolution" / "phase9_join_planner.json",
    )
    parser.add_argument("--repeats", type=int, default=REPEATS)
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 15:
        parser.error("--repeats must be between 1 and 15")

    records = []
    for family in FAMILIES:
        for seed_index in range(SEEDS_PER_FAMILY):
            seed = 91000 + seed_index
            store, rule, workload_metadata = make_workload(family, seed)
            for planner in ("input", "selective"):
                warmup = run_once(store, rule, planner)
                if not warmup["complete"]:
                    raise RuntimeError(f"incomplete warmup: {family}/{seed}/{planner}")
            modes = ["input", "selective"]
            if seed_index % 2:
                modes.reverse()
            per_mode = {mode: [] for mode in modes}
            for repeat in range(args.repeats):
                execution_order = modes if repeat % 2 == 0 else list(reversed(modes))
                measured = {}
                for planner in execution_order:
                    measured[planner] = run_once(store, rule, planner)
                if measured["input"]["signature"] != measured["selective"]["signature"]:
                    raise AssertionError(f"planner semantic mismatch: {family}/{seed}")
                if not measured["input"]["complete"] or not measured["selective"]["complete"]:
                    raise AssertionError(f"incomplete result: {family}/{seed}")
                for planner in modes:
                    per_mode[planner].append(measured[planner])
            summary = {}
            for planner in ("input", "selective"):
                samples_for_planner = per_mode[planner]
                summary[planner] = {
                    "median_elapsed_ns": int(statistics.median(item["elapsed_ns"] for item in samples_for_planner)),
                    "median_cpu_ns": int(statistics.median(item["cpu_ns"] for item in samples_for_planner)),
                    "facts_examined": samples_for_planner[0]["facts_examined"],
                    "operations": samples_for_planner[0]["operations"],
                    "conclusions": samples_for_planner[0]["conclusions"],
                    "complete": samples_for_planner[0]["complete"],
                    "plan_order": samples_for_planner[0]["plan_order"],
                    "plan_estimates": samples_for_planner[0]["plan_estimates"],
                }
            records.append({
                "family": family,
                "seed_index": seed_index,
                "seed": seed,
                "calibration_or_holdout": "calibration" if seed_index < 20 else "holdout",
                "workload": workload_metadata,
                **summary,
            })
            print(f"{family}: seed {seed_index + 1}/{SEEDS_PER_FAMILY}", flush=True)

    source = ROOT / "src" / "aether" / "reasoning" / "inference.py"
    report = {
        "benchmark": "phase9_join_planner",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_head": _git_head(),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "process_peak_rss_bytes": (
                None
                if resource is None
                else int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                * (1 if sys.platform == "darwin" else 1024)
            ),
            "process_peak_rss_scope": "whole benchmark process; not attributed per planner",
        },
        "configuration": {
            "families": list(FAMILIES),
            "seeds_per_family": SEEDS_PER_FAMILY,
            "calibration_seeds_per_family": 20,
            "holdout_seeds_per_family": 10,
            "repeats_per_strategy": args.repeats,
            "inference_limits": {
                "max_depth": LIMITS.max_depth,
                "max_operations": LIMITS.max_operations,
                "max_conclusions": LIMITS.max_conclusions,
            },
        },
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "summary": summarize(records),
        "runs": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output}")
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
