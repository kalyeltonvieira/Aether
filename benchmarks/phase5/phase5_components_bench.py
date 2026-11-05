#!/usr/bin/env python3
"""Measure weak-component detection on selected real SNAP graphs."""
from __future__ import annotations

from benchmarks._paths import phase5_manifest_path, repository_root

import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
from array import array
from collections import deque
from pathlib import Path

from aether.graph.components import weak_component_labels
from aether.graph.dynamic import DynamicGraph
from benchmarks.phase5.phase5_bench import current_rss_bytes, load_snap_graph, peak_rss_bytes, sha256_file


DATASETS = ("email-eu-core", "wiki-vote", "soc-epinions1", "web-google")
METHODS = ("python_sets", "python_compact")


def _same_partition(left, right):
    forward, reverse = {}, {}
    for first, second in zip(left, right):
        if first in forward and forward[first] != second:
            return False
        if second in reverse and reverse[second] != first:
            return False
        forward[first] = second
        reverse[second] = first
    return True


def _weak_oracle(n, edges):
    adjacency = [set() for _ in range(n)]
    for source, target in edges:
        adjacency[source].add(target)
        adjacency[target].add(source)
    labels = [-1] * n
    sizes = []
    for start in range(n):
        if labels[start] >= 0:
            continue
        component_id = len(sizes)
        labels[start] = component_id
        queue = deque([start])
        size = 0
        while queue:
            node = queue.popleft(); size += 1
            for neighbor in adjacency[node]:
                if labels[neighbor] < 0:
                    labels[neighbor] = component_id
                    queue.append(neighbor)
        sizes.append(size)
    return labels, sizes


def _worker(config):
    root = Path(config["repo_root"])
    manifest = json.loads(Path(config["manifest_path"]).read_text(encoding="utf-8"))
    entry = next(item for item in manifest["datasets"] if item["id"] == config["dataset_id"])
    archive = Path(config["archive_path"])
    parse_start = time.perf_counter_ns()
    n, edges, parse_stats = load_snap_graph(archive, entry)
    parse_ms = (time.perf_counter_ns() - parse_start) / 1e6
    rss_before = current_rss_bytes()
    build_start = time.perf_counter_ns()
    graph = DynamicGraph(n, config["method"] == "python_sets" and "sets" or "compact")
    for source, target in edges:
        graph.add_edge(source, target)
    build_ms = (time.perf_counter_ns() - build_start) / 1e6
    rss_after_build = current_rss_bytes()
    retained_graph_bytes = graph.memory_bytes()

    warm_labels, warm_count = weak_component_labels(DynamicGraph(3, "compact"))
    del warm_labels, warm_count
    times = []
    result_labels = None
    result_count = None
    for _ in range(config["repeats"]):
        start = time.perf_counter_ns()
        result_labels, result_count = weak_component_labels(graph)
        times.append((time.perf_counter_ns() - start) / 1e6)
    workspace_estimate = (
        sys.getsizeof(array("I", range(n)))
        + sys.getsizeof(bytearray(n))
        + sys.getsizeof(array("I", [0]) * n)
    )
    oracle_start = time.perf_counter_ns()
    oracle_labels, oracle_sizes = _weak_oracle(n, edges)
    oracle_ms = (time.perf_counter_ns() - oracle_start) / 1e6
    if not _same_partition(result_labels, oracle_labels) or result_count != len(oracle_sizes):
        raise AssertionError(f"weak-component partition mismatch: {config['dataset_id']} {config['method']}")
    rss_after = current_rss_bytes()
    largest_component = max(oracle_sizes, default=0)
    average_size = statistics.mean(oracle_sizes) if oracle_sizes else 0
    return {
        "dataset_id": config["dataset_id"],
        "method": config["method"],
        "n": n,
        "directed_arcs": parse_stats["normalized_directed_edges"],
        "weak_component_count": result_count,
        "largest_weak_component_nodes": largest_component,
        "average_weak_component_nodes": average_size,
        "input_sha256": sha256_file(archive),
        "accuracy_vs_independent_bfs": True,
        "parse_ms": parse_ms,
        "build_ms": build_ms,
        "component_p50_ms": statistics.median(times),
        "component_min_ms": min(times),
        "component_max_ms": max(times),
        "oracle_ms_excluded": oracle_ms,
        "rss_before_build_bytes": rss_before,
        "rss_after_build_bytes": rss_after_build,
        "rss_delta_after_build_bytes": rss_after_build - rss_before if rss_after_build is not None and rss_before is not None else None,
        "rss_after_oracle_bytes": rss_after,
        "process_peak_rss_bytes": peak_rss_bytes(),
        "retained_graph_bytes_estimate": retained_graph_bytes,
        "component_workspace_bytes_estimate": workspace_estimate,
        "repeats": config["repeats"],
    }


def _worker_main():
    config = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    print(json.dumps(_worker(config), separators=(",", ":")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(phase5_manifest_path()))
    parser.add_argument("--data-dir", default="data/phase5_snap")
    parser.add_argument("--out", default="results/phase5/components")
    parser.add_argument("--datasets", default=",".join(DATASETS))
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    root = repository_root()
    manifest_path = Path(args.manifest); manifest_path = manifest_path if manifest_path.is_absolute() else root / manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {item["id"]: item for item in manifest["datasets"]}
    ids = [value.strip() for value in args.datasets.split(",") if value.strip()]
    if args.repeats < 1 or not ids or len(ids) != len(set(ids)):
        parser.error("repeats must be positive and dataset IDs unique/nonempty")
    unknown = sorted(set(ids) - set(entries))
    if unknown:
        parser.error(f"unknown dataset IDs: {unknown}")
    data_dir = Path(args.data_dir); data_dir = data_dir if data_dir.is_absolute() else root / data_dir
    out_dir = Path(args.out); out_dir = out_dir if out_dir.is_absolute() else root / out_dir
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for dataset_id in ids:
        entry = entries[dataset_id]
        archive = data_dir / dataset_id / entry["filename"]
        if not archive.exists():
            raise FileNotFoundError(archive)
        if entry.get("sha256") and sha256_file(archive) != entry["sha256"]:
            raise ValueError(f"archive SHA-256 mismatch for {dataset_id}")
        for method in METHODS:
            config = {
                "repo_root": str(root),
                "manifest_path": str(manifest_path),
                "archive_path": str(archive),
                "dataset_id": dataset_id,
                "method": method,
                "repeats": args.repeats,
            }
            start = time.perf_counter_ns()
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker"],
                input=json.dumps(config).encode("utf-8"), capture_output=True, check=True,
            )
            row = json.loads(proc.stdout)
            row["worker_parent_wall_ms"] = (time.perf_counter_ns() - start) / 1e6
            rows.append(row)
            print(f"{dataset_id} {method} exact=true components={row['weak_component_count']}", flush=True)
    csv_path = out_dir / "components.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    summary = {
        "title": "AETHER Phase 5 — weakly connected component capability",
        "definition": "Each directed arc is treated as an undirected connection; this computes weak components, not strongly connected components.",
        "algorithm": "Union-find with path compression and union by rank over existing outgoing adjacency; O(V) auxiliary arrays and O(E α(V)) edge processing.",
        "datasets": ids,
        "methods": list(METHODS),
        "repeats_per_run": args.repeats,
        "accuracy_exact_for_all_runs": all(row["accuracy_vs_independent_bfs"] for row in rows),
        "results": rows,
        "raw_csv": str(csv_path),
        "limitations": [
            "Component labels are recomputed from scratch after graph changes; incremental affected-component maintenance is not implemented.",
            "Independent oracle materializes an undirected adjacency for validation; oracle time and memory are excluded from the component operation estimate.",
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(out_dir), "runs": len(rows), "all_exact": summary["accuracy_exact_for_all_runs"]}, indent=2))


if __name__ == "__main__":
    if "--worker" in sys.argv:
        _worker_main()
    else:
        main()
