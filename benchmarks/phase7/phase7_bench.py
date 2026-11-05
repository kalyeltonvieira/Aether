"""Reproducible synthetic benchmark for the structured-knowledge prototype.

Synthetic data here is a controlled software workload, not a claim about real
knowledge or training data. Calibration and holdout seeds are reported apart.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import time
from pathlib import Path

from aether.reasoning.dependencies import DependencyTracker
from aether.reasoning.backward import BackwardInference
from aether.reasoning.hybrid import HybridInference
from aether.reasoning.inference import InferenceEngine, InferenceLimits, Pattern, Rule
from aether.reasoning.incremental import IncrementalInference
from aether.core.knowledge.store import KnowledgeStore, Provenance


RULE = Rule(
    "transitive-link",
    (Pattern("?x", "link", "?y"), Pattern("?y", "link", "?z")),
    Pattern("?x", "link", "?z"),
)


def build_store(seed: int, nodes: int, extra_edges: int) -> KnowledgeStore:
    rng = random.Random(seed)
    store = KnowledgeStore()
    for node in range(nodes):
        store.add_entity(f"e{node}", {"kind": "synthetic"})
    provenance = Provenance("phase7-synthetic-fixture", f"seed={seed}")
    for node in range(nodes - 1):
        store.add_fact(f"e{node}", "link", f"e{node + 1}", provenance=provenance)
    candidates = [(a, b) for a in range(nodes) for b in range(a + 2, nodes)]
    rng.shuffle(candidates)
    for a, b in candidates[:extra_edges]:
        store.add_fact(f"e{a}", "link", f"e{b}", provenance=provenance)
    return store


def measure(seed: int, scenario: str, nodes: int, extra_edges: int, repeats: int = 25):
    store = build_store(seed, nodes, extra_edges)
    engine = InferenceEngine(store, (RULE,))
    limits = InferenceLimits(max_depth=nodes, max_operations=250000, max_conclusions=250000)
    rows = []

    start = time.perf_counter()
    result = engine.infer(limits)
    infer_ms = (time.perf_counter() - start) * 1000
    rows.append({"seed": seed, "split": "calibration" if seed < 15 else "holdout", "scenario": scenario, "method": "full_inference", "latency_ms": infer_ms, "facts_examined": result.facts_examined, "operations": result.operations, "conclusions": len(result.conclusions), "complete": int(result.complete), "explanation_ms": 0.0, "invalidated": 0})

    target = ("e0", "link", f"e{nodes - 1}")
    start = time.perf_counter()
    backward = BackwardInference(store, (RULE,)).prove(target)
    backward_ms = (time.perf_counter() - start) * 1000
    rows.append({"seed": seed, "split": "calibration" if seed < 15 else "holdout", "scenario": scenario, "method": "backward_chain", "latency_ms": backward_ms, "facts_examined": backward.operations, "operations": backward.operations, "conclusions": int(backward.proven), "complete": int(backward.complete), "explanation_ms": 0.0, "invalidated": 0})

    start = time.perf_counter()
    hybrid = HybridInference(store, (RULE,)).prove(target, forward_limits=limits)
    hybrid_ms = (time.perf_counter() - start) * 1000
    rows.append({"seed": seed, "split": "calibration" if seed < 15 else "holdout", "scenario": scenario, "method": "hybrid_chain", "latency_ms": hybrid_ms, "facts_examined": hybrid.operations, "operations": hybrid.operations, "conclusions": int(hybrid.proven), "complete": int(hybrid.complete), "explanation_ms": 0.0, "invalidated": 0})

    start = time.perf_counter()
    for _ in range(repeats):
        hit = next((fact for fact in result.conclusions if fact.key == target), None)
    cached_ms = (time.perf_counter() - start) * 1000
    rows.append({"seed": seed, "split": "calibration" if seed < 15 else "holdout", "scenario": scenario, "method": "cached_conclusion_lookup", "latency_ms": cached_ms, "facts_examined": 0, "operations": repeats, "conclusions": int(hit is not None), "complete": int(result.complete), "explanation_ms": 0.0, "invalidated": 0})

    if result.conclusions:
        tracker = DependencyTracker(result)
        first = next(iter(store.query(predicate="link")))
        start = time.perf_counter()
        invalidation = tracker.invalidate({first.fact_id})
        store.remove_fact(first.fact_id)
        invalidation_ms = (time.perf_counter() - start) * 1000
        rows.append({"seed": seed, "split": "calibration" if seed < 15 else "holdout", "scenario": scenario, "method": "localized_invalidation", "latency_ms": invalidation_ms, "facts_examined": invalidation.conclusions_visited, "operations": invalidation.conclusions_visited, "conclusions": invalidation.remaining_conclusions, "complete": 0, "explanation_ms": 0.0, "invalidated": invalidation.conclusions_invalidated})

    incremental_store = build_store(seed, nodes, extra_edges)
    incremental = IncrementalInference(incremental_store, (RULE,))
    incremental.initialize(limits)
    absent = next((
        (f"e{a}", f"e{b}")
        for a in range(nodes)
        for b in range(nodes)
        if a != b and not incremental_store.query(subject=f"e{a}", predicate="link", object=f"e{b}")
    ), None)
    if absent is not None:
        start = time.perf_counter()
        _, update = incremental.add_fact(absent[0], "link", absent[1], provenance=Provenance("phase7-benchmark"))
        incremental_ms = (time.perf_counter() - start) * 1000
        rows.append({"seed": seed, "split": "calibration" if seed < 15 else "holdout", "scenario": scenario, "method": "incremental_insertion", "latency_ms": incremental_ms, "facts_examined": update.facts_examined, "operations": update.operations, "conclusions": len(update.new_conclusions), "complete": int(update.complete), "explanation_ms": 0.0, "invalidated": 0})

    start = time.perf_counter()
    target_fact = result.by_key(target)
    explanation = () if target_fact is None else InferenceEngine.explain(result, target)
    explanation_ms = (time.perf_counter() - start) * 1000
    rows.append({"seed": seed, "split": "calibration" if seed < 15 else "holdout", "scenario": scenario, "method": "explanation_lookup", "latency_ms": explanation_ms, "facts_examined": len(explanation), "operations": len(explanation), "conclusions": len(explanation), "complete": int(result.complete), "explanation_ms": explanation_ms, "invalidated": 0})
    return rows


def summarize(rows):
    summary = {}
    for split in ("calibration", "holdout"):
        summary[split] = {}
        for method in sorted({row["method"] for row in rows}):
            values = [float(row["latency_ms"]) for row in rows if row["split"] == split and row["method"] == method]
            if not values:
                continue
            summary[split][method] = {
                "n": len(values),
                "median_latency_ms": statistics.median(values),
                "p95_latency_ms": sorted(values)[max(0, int(len(values) * 0.95) - 1)],
                "median_facts_examined": statistics.median(float(row["facts_examined"]) for row in rows if row["split"] == split and row["method"] == method),
                "median_invalidated": statistics.median(float(row["invalidated"]) for row in rows if row["split"] == split and row["method"] == method),
            }
    return summary


def plot(rows, out: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    methods = sorted({row["method"] for row in rows})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for split, marker in (("calibration", "o"), ("holdout", "s")):
        medians = [statistics.median(float(row["latency_ms"]) for row in rows if row["split"] == split and row["method"] == method) for method in methods]
        axes[0].plot(methods, medians, marker=marker, label=split)
        work = [statistics.median(float(row["facts_examined"]) for row in rows if row["split"] == split and row["method"] == method) for method in methods]
        axes[1].plot(methods, work, marker=marker, label=split)
    axes[0].set_ylabel("latência mediana (ms)")
    axes[1].set_ylabel("fatos/conclusões examinados (mediana)")
    for axis in axes:
        axis.tick_params(axis="x", rotation=35)
        axis.grid(alpha=0.25)
        axis.legend()
    fig.suptitle("AETHER Fase 7 — conhecimento estruturado")
    fig.tight_layout()
    fig.savefig(out / "phase7_knowledge_benchmark.png", dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="results/phase7/knowledge_benchmark")
    parser.add_argument("--seeds", type=int, default=30)
    args = parser.parse_args()
    if args.seeds < 30:
        raise SystemExit("the main benchmark requires at least 30 seeds")
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty directory: {out}")
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in range(args.seeds):
        rows.extend(measure(seed, "chain_sparse", 28, 8))
        rows.extend(measure(seed, "chain_dense", 42, 35))
    fieldnames = list(rows[0])
    with (out / "runs.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    metadata = {"seeds": args.seeds, "calibration_seeds": list(range(min(15, args.seeds))), "holdout_seeds": list(range(15, args.seeds)), "synthetic": True, "not_training_data": True, "rules": [RULE.rule_id], "scenarios": ["chain_sparse", "chain_dense"]}
    (out / "summary.json").write_text(json.dumps({"metadata": metadata, "summary": summarize(rows)}, indent=2) + "\n")
    (out / "provenance.json").write_text(json.dumps({"source": "local deterministic generator", "license": "not applicable; generated fixture", "seed_policy": "independent random.Random seeds", "transformations": ["explicit entity creation", "directed link facts", "no external data"]}, indent=2) + "\n")
    plot(rows, out)
    print(json.dumps({"rows": len(rows), "out": str(out), "summary": summarize(rows)}, indent=2))


if __name__ == "__main__":
    main()
