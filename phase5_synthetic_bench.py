#!/usr/bin/env python3
"""Seeded synthetic scale benchmarks; kept separate from real-SNAP results."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import statistics
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

from array import array
from aether_dynamic import DynamicGraph, reachable_epoch, reachable_set
from aether_native import RustDynamicGraph, compile_native
from phase5_bench import CsrGraph, current_rss_bytes, peak_rss_bytes, percentile_ms


SCENARIOS = {
    "sparse-static-1k": {"n": 1_000, "m": 4_000, "dynamic": False, "family": "sparse_random"},
    "dense-disconnected-1k": {"n": 1_000, "m": 20_000, "dynamic": False, "family": "dense_blocks"},
    "disconnected-dynamic-10k": {"n": 10_000, "m": 30_000, "dynamic": True, "family": "sparse_blocks"},
    "sparse-static-100k": {"n": 100_000, "m": 300_000, "dynamic": False, "family": "sparse_random"},
}
METHODS = {
    "sparse-static-1k": ("python_sets", "python_compact", "python_csr", "rust_ffi_single", "rust_ffi_batch"),
    "dense-disconnected-1k": ("python_sets", "python_compact", "python_csr", "rust_ffi_single", "rust_ffi_batch"),
    "disconnected-dynamic-10k": ("python_sets", "python_compact", "rust_ffi_single", "rust_ffi_batch"),
    "sparse-static-100k": ("python_compact", "rust_ffi_batch"),
}
BATCH_SIZE = 16


def _group(node: int, n: int, groups: int = 10) -> int:
    return min(groups - 1, node * groups // n)


def generate_edges(scenario: str, seed: int):
    config = SCENARIOS[scenario]
    n, wanted = config["n"], config["m"]
    rng = random.Random(seed)
    edges = set()
    family = config["family"]
    while len(edges) < wanted:
        u = rng.randrange(n)
        if family == "dense_blocks":
            lo = (u * 10 // n) * (n // 10)
            hi = ((u * 10 // n) + 1) * (n // 10)
            v = rng.randrange(lo, hi)
        elif family == "sparse_blocks":
            block = u * 10 // n
            lo = block * (n // 10)
            hi = (block + 1) * (n // 10)
            v = rng.randrange(lo, hi)
        else:
            v = rng.randrange(n)
        if u != v:
            edges.add((u, v))
    return n, sorted(edges)


def _make_adjacency(n, edges):
    adjacency = [set() for _ in range(n)]
    for source, target in edges:
        adjacency[source].add(target)
    return adjacency


def _positive_pair(adjacency, rng):
    sources = [node for node, row in enumerate(adjacency) if row]
    source = rng.choice(sources)
    node = source
    for _ in range(rng.randint(1, 8)):
        row = adjacency[node]
        if not row:
            break
        node = rng.choice(tuple(row))
    return source, node


def _negative_pair(adjacency, rng, n, scenario):
    config = SCENARIOS[scenario]
    if config["family"] in ("dense_blocks", "sparse_blocks"):
        source = rng.randrange(n)
        source_group = _group(source, n)
        offset = rng.randrange(1, 10)
        target_group = (source_group + offset) % 10
        group_start = target_group * (n // 10)
        target = rng.randrange(group_start, group_start + n // 10)
        return source, target
    sinks = [node for node, row in enumerate(adjacency) if not row]
    if sinks:
        source = rng.choice(sinks)
        target = rng.randrange(n - 1)
        if target >= source:
            target += 1
        return source, target
    # Sparse random families at the configured densities ordinarily have sinks.
    # Retain an exact, guaranteed negative fallback when a seed does not.
    for _ in range(10_000):
        source, target = rng.randrange(n), rng.randrange(n)
        if source != target and target not in adjacency[source]:
            return source, target
    raise RuntimeError("could not construct a negative-query pair")


def _query_pairs(adjacency, rng, n, scenario, count):
    half = count // 2
    pairs = [_positive_pair(adjacency, rng) for _ in range(half)]
    pairs.extend(_negative_pair(adjacency, rng, n, scenario) for _ in range(count - half))
    rng.shuffle(pairs)
    return pairs


def make_actions(n, edges, scenario: str, seed: int, query_count: int):
    rng = random.Random(seed ^ 0x9E3779B9)
    adjacency = _make_adjacency(n, edges)
    active = set(edges)
    if not SCENARIOS[scenario]["dynamic"]:
        return [{"kind": "query", "phase": "static", "pairs": _query_pairs(adjacency, rng, n, scenario, query_count)}]

    first_n = query_count // 3
    middle_n = query_count // 3
    last_n = query_count - first_n - middle_n
    actions = [{"kind": "query", "phase": "before", "pairs": _query_pairs(adjacency, rng, n, scenario, first_n)}]
    to_add = []
    while len(to_add) < 20:
        source = rng.randrange(n)
        block = _group(source, n)
        lo, hi = block * (n // 10), (block + 1) * (n // 10)
        target = rng.randrange(lo, hi)
        if source != target and (source, target) not in active and (source, target) not in to_add:
            to_add.append((source, target))
    actions.append({"kind": "add", "phase": "update_add", "edges": to_add})
    for source, target in to_add:
        active.add((source, target)); adjacency[source].add(target)
    actions.append({"kind": "query", "phase": "after_add", "pairs": _query_pairs(adjacency, rng, n, scenario, middle_n)})
    to_remove = rng.sample(sorted(active), 20)
    actions.append({"kind": "remove", "phase": "update_remove", "edges": to_remove})
    for source, target in to_remove:
        active.remove((source, target)); adjacency[source].remove(target)
    actions.append({"kind": "query", "phase": "after_remove", "pairs": _query_pairs(adjacency, rng, n, scenario, last_n)})
    return actions


def bfs(adjacency, source, target):
    if source == target:
        return True
    seen = {source}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for neighbor in adjacency[node]:
            if neighbor == target:
                return True
            if neighbor not in seen:
                seen.add(neighbor); queue.append(neighbor)
    return False


def oracle(n, edges, actions):
    adjacency = _make_adjacency(n, edges)
    answers = []
    for action in actions:
        if action["kind"] == "add":
            for source, target in action["edges"]:
                adjacency[source].add(target)
        elif action["kind"] == "remove":
            for source, target in action["edges"]:
                adjacency[source].discard(target)
        else:
            answers.extend(bfs(adjacency, source, target) for source, target in action["pairs"])
    return answers


def _worker(config):
    scenario = config["scenario"]
    method = config["method"]
    n = config["n"]
    parse_start = time.perf_counter_ns()
    edges = []
    with Path(config["edges_path"]).open(encoding="ascii") as stream:
        for line in stream:
            if line and not line.startswith("#"):
                source, target = map(int, line.split())
                edges.append((source, target))
    parse_ms = (time.perf_counter_ns() - parse_start) / 1e6
    rss_before = current_rss_bytes()
    workload_start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()
    build_start = time.perf_counter_ns()
    if method == "python_sets":
        graph = DynamicGraph(n, "sets")
        for edge in edges: graph.add_edge(*edge)
    elif method == "python_compact":
        graph = DynamicGraph(n, "compact")
        for edge in edges: graph.add_edge(*edge)
    elif method == "python_csr":
        graph = CsrGraph(n, edges)
    elif method.startswith("rust_ffi"):
        graph = RustDynamicGraph(n, edges)
    else:
        raise ValueError(method)
    build_ms = (time.perf_counter_ns() - build_start) / 1e6
    rss_after_build = current_rss_bytes()
    del edges

    marks = array("I", [0]) * n if method in ("python_compact", "python_csr") else None
    epoch = 1
    answers, query_latencies, batch_latencies = [], [], []
    batch_output = bytearray(BATCH_SIZE) if method == "rust_ffi_batch" else None
    query_ns = update_ns = 0
    for action in config["actions"]:
        if action["kind"] in ("add", "remove"):
            pairs = action["edges"]
            start = time.perf_counter_ns()
            if method == "rust_ffi_batch":
                changed = graph.add_edges(pairs) if action["kind"] == "add" else graph.remove_edges(pairs)
                if changed != len(pairs):
                    raise AssertionError(f"batch update changed {changed}/{len(pairs)} edges")
            else:
                for source, target in pairs:
                    changed = graph.add_edge(source, target) if action["kind"] == "add" else graph.remove_edge(source, target)
                    if not changed:
                        raise AssertionError("scheduled synthetic update was not applied")
            update_ns += time.perf_counter_ns() - start
            continue

        pairs = action["pairs"]
        if method == "rust_ffi_batch":
            for offset in range(0, len(pairs), BATCH_SIZE):
                batch = pairs[offset:offset + BATCH_SIZE]
                start = time.perf_counter_ns()
                result = graph.reachable_many(batch, batch_output)
                elapsed = time.perf_counter_ns() - start
                batch_latencies.append(elapsed)
                query_ns += elapsed
                answers.extend(bool(value) for value in result)
        else:
            for source, target in pairs:
                start = time.perf_counter_ns()
                if method == "python_sets":
                    answer = reachable_set(graph, source, target)
                elif method in ("python_compact", "python_csr"):
                    answer = reachable_epoch(graph, source, target, marks, epoch)
                    epoch += 1
                else:
                    answer = graph.reachable(source, target)
                elapsed = time.perf_counter_ns() - start
                query_latencies.append(elapsed)
                query_ns += elapsed
                answers.append(bool(answer))
    workload_ns = time.perf_counter_ns() - workload_start
    cpu_ms = (time.process_time_ns() - cpu_start) / 1e6
    try:
        retained_bytes = graph.memory_bytes()
        if marks is not None:
            retained_bytes += sys.getsizeof(marks)
        if batch_output is not None:
            retained_bytes += sys.getsizeof(batch_output)
    except (AttributeError, NotImplementedError):
        retained_bytes = None
    if isinstance(graph, RustDynamicGraph):
        graph.close()
    return {
        "scenario": scenario,
        "seed": config["seed"],
        "method": method,
        "n": n,
        "initial_edges": config["initial_edges"],
        "updates": config["updates"],
        "queries": config["queries"],
        "parse_ms": parse_ms,
        "build_ms": build_ms,
        "update_ms": update_ns / 1e6,
        "query_ms": query_ns / 1e6,
        "workload_execution_wall_ms": workload_ns / 1e6,
        "process_cpu_ms": cpu_ms,
        "query_latency_p50_ms": percentile_ms(query_latencies, .50),
        "query_latency_p95_ms": percentile_ms(query_latencies, .95),
        "query_latency_p99_ms": percentile_ms(query_latencies, .99),
        "batch_call_p50_ms": percentile_ms(batch_latencies, .50),
        "batch_call_p95_ms": percentile_ms(batch_latencies, .95),
        "batch_calls": len(batch_latencies),
        "rss_before_build_bytes": rss_before,
        "rss_after_build_bytes": rss_after_build,
        "rss_delta_build_bytes": rss_after_build - rss_before if rss_before is not None and rss_after_build is not None else None,
        "process_peak_rss_bytes": peak_rss_bytes(),
        "retained_graph_bytes_estimate": retained_bytes,
        "workload_sha256": config["workload_sha256"],
        "graph_sha256": config["graph_sha256"],
        "answers": answers,
    }


def worker_main():
    config = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    print(json.dumps(_worker(config), separators=(",", ":")))


def _write_edges(path, edges, seed, scenario):
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(f"# generated scenario={scenario} seed={seed}; directed; not a SNAP dataset\n")
        for source, target in edges:
            stream.write(f"{source} {target}\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _summarize(rows):
    groups = {}
    for row in rows:
        groups.setdefault(f"{row['scenario']}|{row['method']}", []).append(row)
    metrics = (
        "parse_ms", "build_ms", "update_ms", "query_ms", "workload_execution_wall_ms",
        "process_cpu_ms", "query_latency_p50_ms", "query_latency_p95_ms",
        "query_latency_p99_ms", "rss_delta_build_bytes", "process_peak_rss_bytes",
        "retained_graph_bytes_estimate",
    )
    result = {}
    for key, records in groups.items():
        item = {metric: statistics.median([r[metric] for r in records if r.get(metric) is not None])
                if any(r.get(metric) is not None for r in records) else None for metric in metrics}
        item.update({
            "n": records[0]["n"],
            "seed_count": len({r["seed"] for r in records}),
            "all_answers_exact": all(r["accuracy_exact"] for r in records),
            "graph_sha256_count": len({r["graph_sha256"] for r in records}),
            "workload_sha256_count": len({r["workload_sha256"] for r in records}),
        })
        result[key] = item
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="results/phase5/synthetic_30seeds")
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--smoke", action="store_true", help="use two seeds and only the 1k sparse scenario")
    args = parser.parse_args()
    if args.seeds < 1 or args.queries < 20 or args.queries % 2:
        parser.error("seeds must be >=1 and queries must be an even integer >=20")
    scenarios = [value.strip() for value in args.scenarios.split(",") if value.strip()]
    if args.smoke:
        scenarios, seed_count = ["sparse-static-1k"], 2
    else:
        seed_count = args.seeds
    unknown = sorted(set(scenarios) - set(SCENARIOS))
    if not scenarios or unknown:
        parser.error(f"unknown/empty scenarios: {unknown}")
    output_dir = Path(args.out)
    if not output_dir.is_absolute():
        output_dir = Path(__file__).resolve().parent / output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite existing results in {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    compile_native()

    rows = []
    with __import__("tempfile").TemporaryDirectory(prefix="aether-phase5-synthetic-") as temp:
        temp_dir = Path(temp)
        for scenario in scenarios:
            for seed in range(seed_count):
                n, edges = generate_edges(scenario, seed)
                edge_path = temp_dir / f"{scenario}-{seed}.txt"
                graph_sha = _write_edges(edge_path, edges, seed, scenario)
                actions = make_actions(n, edges, scenario, seed, args.queries)
                answers_expected = oracle(n, edges, actions)
                workload_sha = hashlib.sha256(json.dumps(actions, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                update_count = sum(len(action["edges"]) for action in actions if action["kind"] in ("add", "remove"))
                query_total = sum(len(action["pairs"]) for action in actions if action["kind"] == "query")
                method_list = METHODS[scenario]
                method_shift = seed % len(method_list)
                method_order = method_list[method_shift:] + method_list[:method_shift]
                for method_order_index, method in enumerate(method_order):
                    config = {
                        "scenario": scenario,
                        "seed": seed,
                        "method": method,
                        "n": n,
                        "initial_edges": len(edges),
                        "updates": update_count,
                        "queries": query_total,
                        "edges_path": str(edge_path),
                        "actions": actions,
                        "workload_sha256": workload_sha,
                        "graph_sha256": graph_sha,
                    }
                    start = time.perf_counter_ns()
                    proc = subprocess.run(
                        [sys.executable, str(Path(__file__).resolve()), "--worker"],
                        input=json.dumps(config, separators=(",", ":")).encode("utf-8"),
                        capture_output=True,
                        check=True,
                    )
                    startup_ms = (time.perf_counter_ns() - start) / 1e6
                    row = json.loads(proc.stdout)
                    stderr = proc.stderr.decode("utf-8", errors="replace")
                    if row.pop("answers") != answers_expected:
                        raise AssertionError(f"{scenario} seed={seed} method={method} differs from independent BFS\n{stderr[-2000:]}")
                    row["accuracy_exact"] = True
                    row["method_order_index"] = method_order_index
                    row["parent_wall_including_startup_ms"] = startup_ms
                    rows.append(row)
                    print(f"{scenario} seed={seed:02d} method={method} exact=true", flush=True)
                del edges, actions, answers_expected
                edge_path.unlink(missing_ok=True)

    raw_path = output_dir / "runs.csv"
    with raw_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    summary = {
        "title": "AETHER Phase 5 — seeded synthetic performance benchmarks",
        "synthetic_only": True,
        "warning": "Synthetic results isolate graph structure and are not evidence about real-world graph distributions; see SNAP results separately.",
        "seed_count_per_scenario": seed_count,
        "independent_graphs_per_scenario": seed_count,
        "queries_per_seed": args.queries,
        "query_streams_shared_across_methods": True,
        "updates_per_dynamic_seed": 40,
        "batch_size": BATCH_SIZE,
        "scenario_definitions": SCENARIOS,
        "methods_by_scenario": METHODS,
        "results": _summarize(rows),
        "raw_csv": str(raw_path),
        "accuracy_exact_for_all_runs": all(row["accuracy_exact"] for row in rows),
        "total_process_runs": len(rows),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_dir), "runs": len(rows), "seeds_per_scenario": seed_count,
                      "all_exact": summary["accuracy_exact_for_all_runs"]}, indent=2))


if __name__ == "__main__":
    if "--worker" in sys.argv:
        worker_main()
    else:
        main()
