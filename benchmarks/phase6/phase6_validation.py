#!/usr/bin/env python3
"""Final quantitative validation harness for AETHER phase 6.

This script adds no runtime feature. It measures the already committed phase 6
subsystems on deterministic holdout workloads derived from the local official
SNAP archives, writes raw CSVs/JSON, and renders comparison plots.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

from aether.memory.adaptive_controller import EmpiricalAdaptiveController, WorkloadSignature
from aether.memory.adaptive_storage import MemoryPolicyComparison
from aether.temporal.checkpoints import SelectiveCheckpointHistory
from aether.graph.components import weak_component_labels
from aether.graph.dynamic import DynamicGraph, reachable_epoch, reachable_set
from aether.graph.incremental_components import IncrementalWeakComponents
from aether.graph.parallel import parallel_reachability
from benchmarks.phase5.phase5_bench import sha256_file

from benchmarks._paths import phase5_manifest_path, repository_root

ROOT = repository_root()
MANIFEST = phase5_manifest_path()
HOLDOUT_SEEDS = tuple(range(100, 130))
CALIBRATION_SEEDS = tuple(range(10))
SAMPLE_EDGES = 900
MAX_EVENTS = 500


def now_ns():
    return time.perf_counter_ns()


def ms(start_ns):
    return (now_ns() - start_ns) / 1_000_000


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def dense_sample(path: Path, entry: dict, limit: int = SAMPLE_EDGES) -> tuple[int, list[tuple[int, int]], dict]:
    """Read a bounded deterministic prefix while preserving official provenance."""
    raw = []
    temporal = bool(entry.get("temporal"))
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="strict") as stream:
        for line_number, line in enumerate(stream, 1):
            if len(raw) >= limit:
                break
            fields = line.strip().split()
            if not fields or fields[0].startswith(("#", "%", "//")) or len(fields) < 2:
                continue
            try:
                u, v = int(fields[0]), int(fields[1])
            except ValueError:
                continue
            raw.append((u, v, int(fields[2]) if temporal and len(fields) >= 3 else line_number))
    if not raw:
        raise ValueError(f"no usable edges in {path}")
    nodes = sorted({node for u, v, _ in raw for node in (u, v)})
    mapping = {node: index for index, node in enumerate(nodes)}
    edges = {(mapping[u], mapping[v]) for u, v, _ in raw}
    if not entry.get("directed", True):
        edges.update((v, u) for u, v in list(edges) if u != v)
    normalized = sorted(edges)
    return len(nodes), normalized, {
        "archive_sha256": sha256_file(path),
        "archive_size_bytes": path.stat().st_size,
        "sample_raw_records": len(raw),
        "sample_unique_directed_edges": len(normalized),
        "sample_nodes": len(nodes),
        "sample_limit": limit,
        "sampling": "deterministic prefix of official local archive, dense remapping, undirected expansion where manifest requires",
        "temporal_fields_read": temporal,
    }


def load_inputs() -> tuple[dict[str, tuple[int, list[tuple[int, int]], dict]], list[dict]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    result = {}
    provenance = []
    for entry in manifest["datasets"]:
        path = ROOT / "data" / "phase5_snap" / entry["id"] / entry["filename"]
        if not path.exists():
            continue
        n, edges, stats = dense_sample(path, entry)
        result[entry["id"]] = (n, edges, stats)
        provenance.append({
            "id": entry["id"], "name": entry["name"], "snap_page": entry["snap_page"],
            "download_url": entry["download_url"], "manifest_sha256": entry.get("sha256"),
            "observed_sha256": stats["archive_sha256"], "manifest_license_or_terms": entry.get("license_or_terms"),
            "local_path": str(path.relative_to(ROOT)), "sample": stats,
        })
    if not result:
        raise RuntimeError("no local SNAP archive is available")
    return result, provenance


def query_stream(n: int, edges: list[tuple[int, int]], seed: int, count: int = 80) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    if not edges:
        return [(0, 0)] * count
    pairs = []
    for index in range(count):
        u, v = edges[rng.randrange(len(edges))]
        if index % 2:
            pairs.append((v, u))
        else:
            pairs.append((u, v))
    return pairs


def benchmark_memory(inputs, out: Path) -> list[dict]:
    rows = []
    for dataset, (n, edges, _) in inputs.items():
        for seed in HOLDOUT_SEEDS:
            rng = random.Random(seed ^ 0x6A09E667)
            operations = []
            for index in range(180):
                u, v = edges[rng.randrange(len(edges))]
                key = f"{u}:{v}"
                payload = f"{dataset}|{u}|{v}|{index}".encode().ljust(256, b"x")
                operations.append((key, payload))
            for policy in MemoryPolicyComparison.names():
                with tempfile.TemporaryDirectory(prefix="aether-phase6-memory-") as folder:
                    memory = MemoryPolicyComparison.build(policy, 2 * 1024, Path(folder) / "cold.jsonl")
                    started = now_ns()
                    policy_rng = random.Random(seed ^ 0x6A09E667)
                    for key, payload in operations:
                        memory.put(key, payload)
                        memory.get(key)
                        if policy_rng.random() < 0.35:
                            memory.get(key)
                    elapsed = ms(started)
                    stats = memory.stats()
                rows.append({"dataset": dataset, "seed": seed, "policy": policy, "operations": len(operations),
                             "elapsed_ms": elapsed, "maintenance_ms": elapsed,
                             "hits": stats["hits"], "misses": stats["misses"], "evictions": stats["evictions"],
                             "persist_writes": stats["persist_writes"], "deduplicated_puts": stats["deduplicated_puts"],
                             "resident_bytes": stats["resident_bytes"], "cold_entries": stats["cold_entries"]})
    write_csv(out / "memory_policies.csv", rows)
    return rows


def benchmark_checkpoints(inputs, out: Path) -> list[dict]:
    rows = []
    for dataset, (n, edges, _) in inputs.items():
        events = [(index, "add", u, v) for index, (u, v) in enumerate(edges[:MAX_EVENTS], 1)]
        for seed in HOLDOUT_SEEDS:
            rng = random.Random(seed)
            counts = sorted({rng.randint(0, len(events)) for _ in range(12)})
            if len(events) not in counts:
                counts.append(len(events))
            for strategy in SelectiveCheckpointHistory.STRATEGIES:
                history = SelectiveCheckpointHistory(n, strategy=strategy, interval=32, target_recovery_ms=0.01)
                started = now_ns()
                for event in events:
                    history.append(*event)
                build_ms = ms(started)
                recovery_ms = 0.0
                exact = True
                for count in counts:
                    recovery_started = now_ns()
                    graph = history.state_at_event_count(count)
                    recovery_ms += ms(recovery_started)
                    expected = set((source, target) for _, _, source, target in events[:count])
                    observed = {
                        (source, target)
                        for source in range(n)
                        for target in graph.neighbors(source)
                    }
                    exact = exact and observed == expected
                stats = history.stats()
                rows.append({"dataset": dataset, "seed": seed, "strategy": strategy, "events": len(events),
                             "recovery_points": len(counts), "build_ms": build_ms, "recovery_ms": recovery_ms,
                             "total_ms": build_ms + recovery_ms, "checkpoint_bytes": stats["checkpoint_bytes"],
                             "checkpoint_count": stats["checkpoint_count"], "replayed_events": stats["replayed_events"],
                             "exact_structure": exact})
    write_csv(out / "checkpoint_policies.csv", rows)
    return rows


def partition_signature(graph: DynamicGraph) -> set[frozenset[int]]:
    labels, _ = weak_component_labels(graph)
    groups = {}
    for node, label in enumerate(labels):
        groups.setdefault(int(label), set()).add(node)
    return {frozenset(nodes) for nodes in groups.values()}


def benchmark_components(inputs, out: Path) -> list[dict]:
    rows = []
    for dataset, (n, edges, _) in inputs.items():
        sample = edges[: min(260, len(edges))]
        for seed in HOLDOUT_SEEDS:
            rng = random.Random(seed)
            initial = sample[: len(sample) // 2]
            updates = sample[len(sample) // 2 :]
            incremental = IncrementalWeakComponents(n)
            baseline = DynamicGraph(n, "compact")
            for edge in initial:
                incremental.add_edge(*edge); baseline.add_edge(*edge)
            for index, edge in enumerate(updates[:80]):
                operation = "add" if index % 2 == 0 else "remove"
                if operation == "remove" and not baseline.has_edge(*edge):
                    baseline.add_edge(*edge); incremental.add_edge(*edge)
                started_inc = now_ns()
                (incremental.add_edge if operation == "add" else incremental.remove_edge)(*edge)
                inc_ms = ms(started_inc)
                started_full = now_ns()
                if operation == "add": baseline.add_edge(*edge)
                else: baseline.remove_edge(*edge)
                full_partition = partition_signature(baseline)
                full_ms = ms(started_full)
                exact = actual = {incremental.component_nodes(node) for node in range(n)}
                exact = actual == full_partition
                rows.append({"dataset": dataset, "seed": seed, "step": index, "operation": operation,
                             "incremental_ms": inc_ms, "full_recompute_ms": full_ms,
                             "incremental_scanned": incremental.stats()["affected_nodes_scanned"],
                             "splits": incremental.stats()["splits"], "merges": incremental.stats()["merges"],
                             "exact": exact})
    write_csv(out / "components_incremental.csv", rows)
    return rows


def run_reachability(method: str, n: int, edges, pairs):
    graph = DynamicGraph(n, "sets" if method == "sets" else "compact")
    for edge in edges:
        graph.add_edge(*edge)
    started = now_ns()
    marks = [0] * n
    if method == "sets":
        values = [reachable_set(graph, u, v) for u, v in pairs]
    else:
        values = [bool(reachable_epoch(graph, u, v, marks, index + 1)) for index, (u, v) in enumerate(pairs)]
    return values, ms(started)


def benchmark_controller(inputs, out: Path) -> list[dict]:
    rows = []
    controller = EmpiricalAdaptiveController(("sets", "epoch"), fallback="sets", min_observations=2, switch_margin=0.05)
    for dataset, (n, edges, _) in inputs.items():
        signature = WorkloadSignature(n, len(edges), 0, 80, 1, 32 * 1024 * 1024)
        for seed in CALIBRATION_SEEDS:
            pairs = query_stream(n, edges, seed)
            for method in ("sets", "epoch"):
                _, elapsed = run_reachability(method, n, edges, pairs)
                controller.record(signature, method, elapsed)
        for seed in HOLDOUT_SEEDS:
            pairs = query_stream(n, edges, seed)
            selected, detail = controller.choose(signature)
            _, selected_ms = run_reachability(selected, n, edges, pairs)
            fixed = {}
            for method in ("sets", "epoch"):
                values, elapsed = run_reachability(method, n, edges, pairs)
                fixed[method] = elapsed
            best_method = min(fixed, key=fixed.get)
            rows.append({"dataset": dataset, "seed": seed, "selected": selected,
                         "selected_ms": selected_ms, "best_fixed": best_method,
                         "best_fixed_ms": fixed[best_method], "sets_ms": fixed["sets"],
                         "epoch_ms": fixed["epoch"], "decision_ns": detail["decision_ns"],
                         "decision_reason": detail["reason"],
                         "selected_is_best": selected == best_method})
    write_csv(out / "controller_holdout.csv", rows)
    return rows


def benchmark_parallel(inputs, out: Path) -> list[dict]:
    rows = []
    def factory(size, initial):
        graph = DynamicGraph(size, "compact")
        for source, target in initial:
            graph.add_edge(source, target)
        return graph

    for dataset, (n, edges, _) in inputs.items():
        for seed in HOLDOUT_SEEDS:
            pairs = query_stream(n, edges, seed, 96)
            started = now_ns()
            graph = DynamicGraph(n, "compact")
            for edge in edges:
                graph.add_edge(*edge)
            marks = [0] * n
            sequential = [bool(reachable_epoch(graph, u, v, marks, index + 1)) for index, (u, v) in enumerate(pairs)]
            sequential_ms = ms(started)
            parallel, stats = parallel_reachability(
                factory, n, edges, pairs, workers=4
            )
            rows.append({"dataset": dataset, "seed": seed, "sequential_ms": sequential_ms,
                         "parallel_query_ms": stats["query_ms"], "parallel_build_ms": stats["build_ms"],
                         "parallel_total_ms": stats["total_ms"], "speedup_end_to_end": sequential_ms / stats["total_ms"] if stats["total_ms"] else None,
                         "exact": sequential == parallel, "handles": stats["isolated_handles"]})
    write_csv(out / "parallel_sequential.csv", rows)
    return rows


def summarize(rows_by_name: dict[str, list[dict]]) -> dict:
    summary = {}
    for name, rows in rows_by_name.items():
        summary[name] = {"rows": len(rows)}
        numeric = sorted({key for row in rows for key, value in row.items() if isinstance(value, (int, float)) and not isinstance(value, bool)})
        for key in numeric:
            values = [float(row[key]) for row in rows if row.get(key) is not None]
            if values:
                summary[name][key] = {"median": statistics.median(values), "mean": statistics.mean(values), "max": max(values)}
        exact_fields = [key for key in rows[0] if key in ("exact", "exact_structure", "selected_is_best")]
        for key in exact_fields:
            values = [row[key] for row in rows if key in row]
            if values and isinstance(values[0], bool):
                summary[name][key + "_rate"] = sum(values) / len(values)
    return summary


def render_plots(out: Path, rows_by_name: dict[str, list[dict]]) -> list[str]:
    import matplotlib.pyplot as plt
    plots = []
    mem = rows_by_name["memory"]
    policies = sorted({row["policy"] for row in mem})
    fig, ax = plt.subplots(figsize=(9, 5))
    for policy in policies:
        values = [row["elapsed_ms"] for row in mem if row["policy"] == policy]
        ax.boxplot(values, positions=[policies.index(policy) + 1], widths=0.5, tick_labels=[policy])
    ax.set_ylabel("Tempo total (ms)"); ax.set_title("Fase 6 — políticas de memória no holdout SNAP"); ax.grid(axis="y", alpha=.25)
    path = out / "memory_policies.png"; fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig); plots.append(str(path))

    checkpoints = rows_by_name["checkpoints"]
    strategies = sorted({row["strategy"] for row in checkpoints})
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.boxplot([[row["total_ms"] for row in checkpoints if row["strategy"] == strategy] for strategy in strategies], tick_labels=strategies)
    ax.set_ylabel("Construção + recuperação (ms)"); ax.set_title("Fase 6 — políticas de checkpoints"); ax.grid(axis="y", alpha=.25)
    path = out / "checkpoint_policies.png"; fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig); plots.append(str(path))

    comp = rows_by_name["components"]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.boxplot([[row["incremental_ms"] for row in comp], [row["full_recompute_ms"] for row in comp]], tick_labels=["incremental", "full_recompute"])
    ax.set_ylabel("Atualização + validação (ms)"); ax.set_title("Fase 6 — componentes fracos"); ax.grid(axis="y", alpha=.25)
    path = out / "components_incremental.png"; fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig); plots.append(str(path))

    ctrl = rows_by_name["controller"]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.boxplot([[row["selected_ms"] + row["decision_ns"] / 1_000_000 for row in ctrl], [row["best_fixed_ms"] for row in ctrl]], tick_labels=["controller+decision", "best_fixed"])
    ax.set_ylabel("Latência (ms)"); ax.set_title("Fase 6 — controlador contra melhor fixa no holdout"); ax.grid(axis="y", alpha=.25)
    path = out / "controller_holdout.png"; fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig); plots.append(str(path))

    par = rows_by_name["parallel"]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.boxplot([[row["sequential_ms"] for row in par], [row["parallel_total_ms"] for row in par]], tick_labels=["sequential", "parallel+build"])
    ax.set_ylabel("Latência (ms)"); ax.set_title("Fase 6 — sequencial contra concorrente"); ax.grid(axis="y", alpha=.25)
    path = out / "parallel_sequential.png"; fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig); plots.append(str(path))
    return plots


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "phase6" / "final_holdout")
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise SystemExit(f"output directory is not empty: {args.out}")
    args.out.mkdir(parents=True, exist_ok=True)
    inputs, provenance = load_inputs()
    rows_by_name = {
        "memory": benchmark_memory(inputs, args.out),
        "checkpoints": benchmark_checkpoints(inputs, args.out),
        "components": benchmark_components(inputs, args.out),
        "controller": benchmark_controller(inputs, args.out),
        "parallel": benchmark_parallel(inputs, args.out),
    }
    plots = render_plots(args.out, rows_by_name)
    summary = {
        "phase": 6,
        "holdout_seeds": list(HOLDOUT_SEEDS),
        "calibration_seeds": list(CALIBRATION_SEEDS),
        "datasets": sorted(inputs),
        "provenance": provenance,
        "summary": summarize(rows_by_name),
        "plots": plots,
        "python": sys.version,
        "rustc_expected_to_be_validated_by_tests": True,
        "limitations": [
            "SNAP validation uses deterministic bounded prefixes with dense remapping; raw archives and hashes are preserved in provenance.",
            "The phase 6 adaptive memory stores opaque bytes and measures operational access, not semantic relevance.",
            "Parallel validation uses isolated Python handles; native Rust parallel execution remains gated by the native test suite.",
        ],
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out / "provenance.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "datasets": sorted(inputs), "rows": {key: len(value) for key, value in rows_by_name.items()}, "plots": plots}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
