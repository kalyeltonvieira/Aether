#!/usr/bin/env python3
"""Real paired end-to-end Python/Rust graph measurements; synthetic test fixtures."""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from aether.graph.dynamic import DynamicGraph, reachable_set
from aether.native.bindings import RustDynamicGraph, compile_native, _pack_pairs
from aether.metrics import current_rss_bytes, cpu_model, peak_rss_bytes


def timed(function):
    started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    value = function()
    return value, time.perf_counter_ns() - started, time.process_time_ns() - cpu_started


def oracle(n, edges, pairs):
    rows = [set() for _ in range(n)]
    for source, target in edges:
        rows[source].add(target)
    result = []
    for source, target in pairs:
        queue, seen = deque([source]), {source}
        while queue:
            current = queue.popleft()
            for neighbor in rows[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        result.append(target in seen)
    return result


def build_python(n, edges):
    graph = DynamicGraph(n, backend="compact")
    for source, target in edges:
        graph.add_edge(source, target)
    return graph


def run(family, seed, library):
    rng = random.Random(seed)
    n = 128
    density = 0.015 if family == "sparse_native" else 0.15
    edges = [(u, v) for u in range(n) for v in range(n) if u != v and rng.random() < density]
    pairs = [(rng.randrange(n), rng.randrange(n)) for _ in range(128)]
    expected = oracle(n, edges, pairs)
    updates = [(u, v) for u, v in edges[:20]]
    unchanged_edges = [pair for pair in edges if pair not in set(updates)]
    expected_after = oracle(n, unchanged_edges, pairs)
    raw = json.dumps({"n": n, "edges": unchanged_edges}, separators=(",", ":")).encode()
    _, conversion_ns, _ = timed(lambda: _pack_pairs(edges, n))
    result = {"family": family, "seed": seed, "split": "calibration" if seed % 1_000_000 < 20 else "holdout", "nodes": n, "edges": len(edges), "queries": len(pairs), "pair_conversion_probe_ns": conversion_ns, "dataset_sha256": hashlib.sha256(json.dumps(edges).encode()).hexdigest()}
    python_graph, py_build_ns, py_build_cpu = timed(lambda: build_python(n, edges))
    py_answers, py_queries_ns, py_queries_cpu = timed(lambda: [reachable_set(python_graph, *pair) for pair in pairs])
    _, py_update_ns, py_update_cpu = timed(lambda: [python_graph.remove_edge(*pair) for pair in updates])
    py_after, py_after_ns, py_after_cpu = timed(lambda: [reachable_set(python_graph, *pair) for pair in pairs])
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "graph.json"
        _, persistence_ns, _ = timed(lambda: path.write_bytes(raw))
        loaded, load_ns, _ = timed(lambda: json.loads(path.read_bytes()))
        recovered_python, py_recover_ns, _ = timed(lambda: build_python(loaded["n"], loaded["edges"]))
        graph, rust_build_ns, rust_build_cpu = timed(lambda: RustDynamicGraph(n, edges, library=library))
        try:
            rust_single, rust_single_ns, _ = timed(lambda: [graph.reachable(*pair) for pair in pairs])
            rust_answers, rust_queries_ns, rust_queries_cpu = timed(lambda: [bool(value) for value in graph.reachable_many(pairs)])
            _, rust_update_ns, rust_update_cpu = timed(lambda: graph.remove_edges(updates))
            rust_after, rust_after_ns, rust_after_cpu = timed(lambda: [bool(value) for value in graph.reachable_many(pairs)])
            native_capacity = graph.memory_bytes()
        finally:
            graph.close()
        recovered_rust, rust_recover_ns, _ = timed(lambda: RustDynamicGraph(loaded["n"], loaded["edges"], library=library))
        try:
            recovered_answers = [bool(value) for value in recovered_rust.reachable_many(pairs)]
        finally:
            recovered_rust.close()
    if not (py_answers == rust_single == rust_answers == expected and py_after == rust_after == recovered_answers == expected_after):
        raise AssertionError(f"native semantic mismatch {family}/{seed}")
    if [reachable_set(recovered_python, *pair) for pair in pairs] != expected_after:
        raise AssertionError("Python recovery mismatch")
    result.update({
        "python": {"build_ns": py_build_ns, "queries_ns": py_queries_ns, "update_ns": py_update_ns, "queries_after_update_ns": py_after_ns, "recover_build_ns": py_recover_ns, "adjacency_heap_estimate_bytes": python_graph.memory_bytes(), "end_to_end_ns": py_build_ns + py_queries_ns + py_update_ns + py_after_ns + persistence_ns + load_ns + py_recover_ns, "cpu_ns": py_build_cpu + py_queries_cpu + py_update_cpu + py_after_cpu},
        "rust": {"build_including_conversion_ffi_ns": rust_build_ns, "queries_batch_including_conversion_ffi_ns": rust_queries_ns, "queries_single_including_ffi_ns": rust_single_ns, "update_including_conversion_ffi_ns": rust_update_ns, "queries_after_update_ns": rust_after_ns, "recover_build_including_conversion_ffi_ns": rust_recover_ns, "native_capacity_estimate_bytes": native_capacity, "end_to_end_ns": rust_build_ns + rust_queries_ns + rust_update_ns + rust_after_ns + persistence_ns + load_ns + rust_recover_ns, "cpu_ns": rust_build_cpu + rust_queries_cpu + rust_update_cpu + rust_after_cpu},
        "persistence_write_ns": persistence_ns, "persistence_load_ns": load_ns, "rss_bytes": current_rss_bytes(), "equivalent": True,
    })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/evolution/phase9_native.json")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new path to preserve measurements")
    library, compile_ns, _ = timed(compile_native)
    records = []
    for family_index, family in enumerate(("sparse_native", "dense_native")):
        for index in range(30):
            records.append(run(family, family_index * 1_000_000 + index, library))
            print(f"{family} {index + 1}/30", flush=True)
    summary = {}
    for family in ("sparse_native", "dense_native"):
        summary[family] = {}
        for split in ("calibration", "holdout"):
            rows = [row for row in records if row["family"] == family and row["split"] == split]
            ratios = [row["python"]["end_to_end_ns"] / row["rust"]["end_to_end_ns"] for row in rows]
            summary[family][split] = {"seeds": len(rows), "median_python_over_rust_end_to_end_ratio": statistics.median(ratios), "rust_end_to_end_wins": sum(ratio > 1 for ratio in ratios), "median_python_total_ns": statistics.median(row["python"]["end_to_end_ns"] for row in rows), "median_rust_total_ns": statistics.median(row["rust"]["end_to_end_ns"] for row in rows), "median_rust_batch_ns": statistics.median(row["rust"]["queries_batch_including_conversion_ffi_ns"] for row in rows), "median_rust_single_ns": statistics.median(row["rust"]["queries_single_including_ffi_ns"] for row in rows)}
    report = {"benchmark": "phase9_native", "fixture_type": "synthetic benchmark graphs; not production data", "environment": {"platform": platform.platform(), "python": sys.version, "cpu_model": cpu_model(), "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(), "peak_rss_bytes_whole_process": peak_rss_bytes()}, "compile_once_ns": compile_ns, "scope": "graph build+128 queries+20 removals+128 queries+JSON save/load+graph recovery; Python compact/DFS vs Rust batch DFS; all wrapper costs included, compilation separate, capacity estimates not whole-heap equality", "sources_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("src/aether/native/bindings.py", "src/aether/native/rust/aether_native.rs", "src/aether/graph/dynamic.py")}, "mismatches": 0, "summary": summary, "runs": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
