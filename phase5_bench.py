#!/usr/bin/env python3
"""Phase 5 benchmarks for SNAP graphs and Aether reachability.

The harness uses official local SNAP archives, deterministic query/update streams,
isolated worker processes, an independent BFS oracle and alternating method order.
It writes only into a new output directory and refuses to overwrite old results.
"""
from __future__ import annotations

import argparse
from array import array
import csv
import ctypes
import gzip
import gc
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import time
import urllib.request
from collections import deque
from pathlib import Path

from aether_dynamic import (
    DynamicGraph,
    neighbors_within_hops,
    reachable_epoch,
    reachable_set,
    shortest_path,
)
from aether_native import RustDynamicGraph, compile_native
from aether_metrics import current_rss_bytes, peak_rss_bytes, total_physical_memory_bytes

STATIC_METHODS = (
    "python_sets",
    "python_compact",
    "python_csr",
    "rust_ffi_single",
    "rust_ffi_batch",
    "feature_policy",
    "online_controller",
)
DYNAMIC_METHODS = tuple(m for m in STATIC_METHODS if m != "python_csr")
FIXED_METHODS = (
    "python_sets",
    "python_compact",
    "python_csr",
    "rust_ffi_single",
    "rust_ffi_batch",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_dataset(entry: dict, data_dir: Path) -> Path:
    """Download only the URL recorded in the manifest, preserving the archive."""
    url = entry["download_url"]
    if not url.startswith("https://snap.stanford.edu/data/"):
        raise ValueError(f"download URL is not an official SNAP data URL: {url}")
    filename = entry.get("filename") or url.rsplit("/", 1)[-1]
    destination = data_dir / entry["id"] / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "AETHER-phase5-reproducible-benchmark/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def load_snap_graph(path: Path, entry: dict) -> tuple[int, list[tuple[int, int]], dict]:
    """Read an edge list and record remapping, duplicates and direction changes."""
    raw_edges: list[tuple[int, int]] = []
    external_nodes: set[int] = set()
    self_loops = 0
    comment_lines = 0
    malformed_lines = []
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="strict") as stream:
        for line_number, line in enumerate(stream, 1):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("#", "%", "//")):
                comment_lines += 1
                continue
            fields = stripped.split()
            if len(fields) < 2:
                malformed_lines.append(line_number)
                continue
            try:
                u, v = int(fields[0]), int(fields[1])
            except ValueError:
                # Preserve visibility of an undocumented header rather than
                # silently interpreting it as a relation.
                malformed_lines.append(line_number)
                continue
            if u < 0 or v < 0:
                raise ValueError(f"negative node id at {path}:{line_number}")
            raw_edges.append((u, v))
            external_nodes.update((u, v))
            self_loops += u == v
    if malformed_lines:
        preview = malformed_lines[:10]
        raise ValueError(f"non-comment rows are not integer edge pairs at lines {preview} in {path}")
    if not raw_edges:
        raise ValueError(f"no edge records found in {path}")

    original_unique = set(raw_edges)
    duplicates_removed = len(raw_edges) - len(original_unique)
    declared_nodes = entry.get("nodes")
    declared_nodes = int(declared_nodes) if declared_nodes is not None else None
    identity_ids = (
        declared_nodes is not None
        and all(0 <= node < declared_nodes for node in external_nodes)
    )
    if identity_ids:
        node_count = declared_nodes
        relabelled = False
        internal_edges = set(original_unique)
        unlisted_isolates = max(0, declared_nodes - len(external_nodes))
    else:
        ordered_external = sorted(external_nodes)
        mapping = {node: index for index, node in enumerate(ordered_external)}
        node_count = max(len(ordered_external), declared_nodes or 0)
        internal_edges = {(mapping[u], mapping[v]) for u, v in original_unique}
        relabelled = True
        unlisted_isolates = max(0, node_count - len(ordered_external))

    directed = bool(entry.get("directed", True))
    if not directed:
        directed_edges = set(internal_edges)
        directed_edges.update((v, u) for u, v in internal_edges if u != v)
        internal_edges = directed_edges
        direction_transform = "cada aresta não dirigida foi representada nos dois sentidos; autoarestas foram mantidas uma vez"
    else:
        direction_transform = "nenhuma; as arestas dirigidas originais foram mantidas"

    edges = sorted(internal_edges)
    stats = {
        "raw_edge_records": len(raw_edges),
        "unique_original_edges": len(original_unique),
        "normalized_directed_edges": len(edges),
        "external_node_ids_in_edge_file": len(external_nodes),
        "declared_nodes": declared_nodes,
        "internal_nodes": node_count,
        "unlisted_isolates_preserved_as_internal_nodes": unlisted_isolates,
        "duplicate_records_removed": duplicates_removed,
        "self_loop_records": self_loops,
        "comment_lines_skipped": comment_lines,
        "ids_relabelled_to_dense_range": relabelled,
        "directedness_transform": direction_transform,
        "official_nodes_match": declared_nodes is None or node_count == declared_nodes,
        "official_edge_count": entry.get("edges"),
        "official_edge_count_matches_original_unique": entry.get("edges") is None or int(entry["edges"]) == len(original_unique),
    }
    return node_count, edges, stats


def percentile_ms(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)] / 1e6


class CsrGraph:
    """Immutable CSR snapshot used only for static comparisons."""
    def __init__(self, n: int, edges: list[tuple[int, int]]):
        if array("Q").itemsize != 8 or array("I").itemsize != 4:
            raise RuntimeError("CSR requires 64-bit offsets and 32-bit node IDs")
        self.n = n
        counts = array("Q", [0]) * n
        for u, _ in edges:
            counts[u] += 1
        self.offsets = array("Q", [0]) * (n + 1)
        for node, count in enumerate(counts):
            self.offsets[node + 1] = self.offsets[node] + count
        cursor = array("Q", self.offsets[:-1])
        self.edges = array("I", [0]) * len(edges)
        for u, v in edges:
            position = cursor[u]
            self.edges[position] = v
            cursor[u] += 1
        self._edge_view = memoryview(self.edges)

    def neighbors(self, node):
        return self._edge_view[self.offsets[node]:self.offsets[node + 1]]

    def memory_bytes(self):
        return sys.getsizeof(self.offsets) + sys.getsizeof(self.edges)


def _bfs_reachable(adjacency, source, target):
    """Independent set-based oracle; not shared with the tested traversal code."""
    if source == target:
        return True
    seen = {source}
    queue = deque([source])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if neighbor == target:
                return True
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return False


def _positive_pair(adjacency, sources, rng, max_walk):
    if not sources:
        raise ValueError("graph has no outgoing edges; cannot sample positive path queries")
    source = rng.choice(sources)
    current = source
    first = None
    steps = rng.randint(1, max_walk)
    for _ in range(steps):
        row = adjacency[current]
        if not row:
            break
        nxt = rng.choice(sorted(row))
        if first is None:
            first = nxt
        current = nxt
    target = current if current != source else first
    if target is None:
        raise AssertionError("positive query generation failed despite outgoing edges")
    return source, target


def _negative_pair(adjacency, sinks, n, rng):
    if n < 2:
        raise ValueError("at least two nodes are needed for a negative reachability query")
    if sinks:
        source = rng.choice(sinks)
        target = rng.randrange(n - 1)
        if target >= source:
            target += 1
        return source, target
    # Fallback for graphs without sinks. Validate each candidate with the
    # independent BFS oracle and stop rather than fabricate a negative answer.
    for _ in range(256):
        source = rng.randrange(n)
        target = rng.randrange(n - 1)
        if target >= source:
            target += 1
        if not _bfs_reachable(adjacency, source, target):
            return source, target
    raise ValueError("could not sample a confirmed negative query from this graph")


def make_query_group(adjacency, rng, count, max_walk, phase):
    n = len(adjacency)
    sources = [node for node, row in enumerate(adjacency) if row]
    sinks = [node for node, row in enumerate(adjacency) if not row]
    pairs = []
    for _ in range(count // 2):
        pairs.append(_positive_pair(adjacency, sources, rng, max_walk))
    for _ in range(count - len(pairs)):
        pairs.append(_negative_pair(adjacency, sinks, n, rng))
    rng.shuffle(pairs)
    return {"kind": "query", "phase": phase, "pairs": pairs}


def make_actions(n, edges, mode, seed, queries, rounds, updates_per_round):
    rng = random.Random(seed ^ 0xA37E5)
    adjacency = [set() for _ in range(n)]
    for u, v in edges:
        adjacency[u].add(v)
    actions = []
    if mode == "static":
        train_count = max(2, queries // 2)
        holdout_count = max(2, queries - train_count)
        actions.append(make_query_group(adjacency, rng, train_count, 2, "calibration"))
        actions.append(make_query_group(adjacency, rng, holdout_count, 6, "holdout_unknown_query_mix"))
        return actions

    active = set(edges)
    edge_list = list(edges)
    if n < 2 or not edge_list:
        raise ValueError("dynamic real-graph workload needs at least two nodes and one edge")
    query_count = max(20, queries // 2)
    actions.append(make_query_group(adjacency, rng, query_count, 2, "before_updates_calibration"))
    for phase in range(rounds):
        additions = []
        attempts = 0
        target_additions = min(updates_per_round, max(1, n))
        while len(additions) < target_additions and attempts < target_additions * 200:
            attempts += 1
            u, v = rng.randrange(n), rng.randrange(n)
            if u == v or (u, v) in active:
                continue
            active.add((u, v)); adjacency[u].add(v); additions.append((u, v))
        if len(additions) != target_additions:
            raise ValueError("could not create enough deterministic non-duplicate insertions")
        actions.append({"kind": "add", "phase": f"insert_{phase}", "edges": additions})
        actions.append(make_query_group(adjacency, rng, query_count, 2 + phase, f"after_insert_{phase}"))

        removals = []
        candidate_budget = min(len(edge_list), max(updates_per_round * 8, updates_per_round))
        candidates = rng.sample(edge_list, candidate_budget)
        for edge in candidates:
            if edge in active:
                active.remove(edge); adjacency[edge[0]].remove(edge[1]); removals.append(edge)
                if len(removals) == target_additions:
                    break
        if len(removals) != target_additions:
            # Added edges are also valid removal candidates.
            candidates = list(active)
            for edge in rng.sample(candidates, min(len(candidates), target_additions)):
                active.remove(edge); adjacency[edge[0]].remove(edge[1]); removals.append(edge)
                if len(removals) == target_additions:
                    break
        if len(removals) != target_additions:
            raise ValueError("could not create enough deterministic removals")
        actions.append({"kind": "remove", "phase": f"remove_{phase}", "edges": removals})
        actions.append(make_query_group(adjacency, rng, query_count, 6, f"after_remove_{phase}"))
    return actions


def build_feature_policy(n, edge_count, mode, query_count, update_count, memory_budget_bytes):
    """Pre-run rule; its thresholds are fixed before this public-data run."""
    m = edge_count
    density = (m / (n * (n - 1))) if n > 1 else 0.0
    set_estimate = 72 * n + 156 * m
    compact_estimate = 64 * n + 32 * m
    csr_estimate = 8 * (n + 1) + 4 * m
    if mode == "static" and set_estimate > memory_budget_bytes and csr_estimate <= memory_budget_bytes:
        selected = "python_csr"
    elif set_estimate > memory_budget_bytes and compact_estimate <= memory_budget_bytes:
        selected = "python_compact"
    elif n >= 20_000 or m >= 100_000 or update_count > query_count:
        selected = "rust_ffi_batch"
    elif density > 0.02:
        selected = "python_compact"
    else:
        selected = "python_sets"
    return selected, {
        "n": n,
        "m": m,
        "density": density,
        "expected_query_groups": query_count,
        "expected_updates": update_count,
        "estimated_sets_bytes": set_estimate,
        "estimated_compact_bytes": compact_estimate,
        "estimated_csr_bytes": csr_estimate,
        "memory_budget_bytes": memory_budget_bytes,
    }


def warmup(method, library):
    if method.startswith("rust_ffi"):
        with RustDynamicGraph(12, ((i, i + 1) for i in range(11)), library=library) as graph:
            graph.reachable(0, 11)
            graph.reachable_many([(0, 11), (11, 0)], bytearray(2))
            graph.add_edges([(0, 2)]); graph.remove_edges([(0, 2)])
    else:
        graph = DynamicGraph(12, "sets" if method == "python_sets" else "compact")
        for node in range(11):
            graph.add_edge(node, node + 1)
        marks = array("I", [0]) * 12
        reachable_set(graph, 0, 11)
        reachable_epoch(graph, 0, 11, marks, 1)


def _new_backend(method, n, edges, library):
    if method == "python_sets":
        graph = DynamicGraph(n, "sets")
        for u, v in edges:
            graph.add_edge(u, v)
        return graph
    if method in ("python_compact", "online_controller"):
        graph = DynamicGraph(n, "compact")
        for u, v in edges:
            graph.add_edge(u, v)
        return graph
    if method == "python_csr":
        return CsrGraph(n, edges)
    if method.startswith("rust_ffi"):
        return RustDynamicGraph(n, edges, library=library)
    raise ValueError(f"unknown benchmark backend {method}")


def measure_ffi_decomposition(graph, actions, max_pairs=1024):
    fields = {
        "ffi_sample_pairs": 0,
        "ffi_pair_pack_ms": None,
        "ffi_output_buffer_setup_ms": None,
        "ffi_pointer_setup_ms": None,
        "ffi_batch_real_call_ms": None,
        "ffi_batch_zero_hop_call_ms": None,
        "ffi_batch_compute_increment_estimate_ms": None,
        "ffi_output_view_create_ms": None,
        "ffi_result_copy_to_bytes_ms": None,
        "ffi_single_call_sample_ms": None,
        "ffi_diagnostic_exact": None,
        "ffi_result_view_is_zero_copy": None,
    }
    if not isinstance(graph, RustDynamicGraph):
        return fields

    from aether_native import _pack_pairs, _raise_status, _u32_pointer
    pairs = [tuple(pair) for action in actions if action["kind"] == "query"
             for pair in action["pairs"][:max_pairs]][:max_pairs]
    if not pairs:
        return fields
    count = len(pairs)

    start = time.perf_counter_ns()
    packed = _pack_pairs(pairs, graph.n)
    pack_ms = (time.perf_counter_ns() - start) / 1e6

    start = time.perf_counter_ns()
    output = bytearray(count)
    output_view = memoryview(output).cast("B")
    output_storage = (ctypes.c_uint8 * count).from_buffer(output_view)
    output_pointer = ctypes.cast(ctypes.addressof(output_storage), ctypes.POINTER(ctypes.c_uint8))
    output_setup_ms = (time.perf_counter_ns() - start) / 1e6

    start = time.perf_counter_ns()
    input_pointer = _u32_pointer(packed)
    pointer_setup_ms = (time.perf_counter_ns() - start) / 1e6

    start = time.perf_counter_ns()
    status = int(graph._lib.aether_graph_reachable_many(
        graph._handle, input_pointer, output_pointer, count
    ))
    real_call_ms = (time.perf_counter_ns() - start) / 1e6
    _raise_status(status, "ffi_diagnostic_real_batch")

    view_start = time.perf_counter_ns()
    result_view = output_view[:count]
    view_ms = (time.perf_counter_ns() - view_start) / 1e6
    copy_start = time.perf_counter_ns()
    result_bytes = bytes(result_view)
    copy_ms = (time.perf_counter_ns() - copy_start) / 1e6

    self_pairs = [(source, source) for source, _ in pairs]
    self_packed = _pack_pairs(self_pairs, graph.n)
    self_output = bytearray(count)
    self_view = memoryview(self_output).cast("B")
    self_storage = (ctypes.c_uint8 * count).from_buffer(self_view)
    self_pointer = ctypes.cast(ctypes.addressof(self_storage), ctypes.POINTER(ctypes.c_uint8))
    start = time.perf_counter_ns()
    noop_status = int(graph._lib.aether_graph_reachable_many(
        graph._handle, _u32_pointer(self_packed), self_pointer, count
    ))
    zero_hop_call_ms = (time.perf_counter_ns() - start) / 1e6
    _raise_status(noop_status, "ffi_diagnostic_zero_hop_batch")
    if bytes(self_view) != b"\x01" * count:
        raise AssertionError("zero-hop Rust batch did not return all true results")

    start = time.perf_counter_ns()
    single_results = bytes(graph.reachable(source, target) for source, target in pairs)
    single_call_ms = (time.perf_counter_ns() - start) / 1e6
    exact = result_bytes == single_results
    if not exact:
        raise AssertionError("raw batched FFI results differ from individual Rust calls")
    fields.update({
        "ffi_sample_pairs": count,
        "ffi_pair_pack_ms": pack_ms,
        "ffi_output_buffer_setup_ms": output_setup_ms,
        "ffi_pointer_setup_ms": pointer_setup_ms,
        "ffi_batch_real_call_ms": real_call_ms,
        "ffi_batch_zero_hop_call_ms": zero_hop_call_ms,
        "ffi_batch_compute_increment_estimate_ms": real_call_ms - zero_hop_call_ms,
        "ffi_output_view_create_ms": view_ms,
        "ffi_result_copy_to_bytes_ms": copy_ms,
        "ffi_single_call_sample_ms": single_call_ms,
        "ffi_diagnostic_exact": exact,
        "ffi_result_view_is_zero_copy": result_view.obj is output,
    })
    return fields


def _independent_validation(path, entry, mode, actions):
    n, edges, _ = load_snap_graph(path, entry)
    adjacency = [set() for _ in range(n)]
    for u, v in edges:
        adjacency[u].add(v)
    answers = []
    for action in actions:
        if action["kind"] == "add":
            for u, v in action["edges"]:
                adjacency[u].add(v)
        elif action["kind"] == "remove":
            for u, v in action["edges"]:
                adjacency[u].discard(v)
        else:
            answers.extend(_bfs_reachable(adjacency, u, v) for u, v in action["pairs"])
    final_edge_count = sum(len(row) for row in adjacency)
    return answers, adjacency, final_edge_count


def _shortest_distance_oracle(adjacency, source, target):
    if source == target:
        return 0
    distance = {source: 0}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        next_distance = distance[node] + 1
        for neighbor in adjacency[node]:
            if neighbor == target:
                return next_distance
            if neighbor not in distance:
                distance[neighbor] = next_distance
                queue.append(neighbor)
    return None


def _neighborhood_oracle(adjacency, source, max_hops):
    distances = {source: 0}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        if distances[node] >= max_hops:
            continue
        for neighbor in adjacency[node]:
            if neighbor not in distances:
                distances[neighbor] = distances[node] + 1
                queue.append(neighbor)
    return set(distances).difference((source,))


def run_worker(cfg):
    wall_begin = time.perf_counter_ns()
    path = Path(cfg["dataset_path"])
    entry = cfg["entry"]
    parse_start = time.perf_counter_ns()
    n, edges, parse_stats = load_snap_graph(path, entry)
    parse_ms = (time.perf_counter_ns() - parse_start) / 1e6
    mode, seed = cfg["mode"], cfg["seed"]
    prepare_start = time.perf_counter_ns()
    actions = make_actions(
        n, edges, mode, seed, cfg["queries"], cfg["rounds"], cfg["updates_per_round"]
    )
    action_json = json.dumps(actions, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    workload_sha256 = hashlib.sha256(action_json).hexdigest()
    query_count = sum(len(action.get("pairs", ())) for action in actions)
    update_count = sum(len(action.get("edges", ())) for action in actions if action["kind"] in ("add", "remove"))
    prepare_ms = (time.perf_counter_ns() - prepare_start) / 1e6
    del action_json

    requested_method = cfg["method"]
    policy_decision_ms = 0.0
    policy_decision_cpu_ms = 0.0
    policy_features = {}
    if requested_method == "feature_policy":
        decision_start = time.perf_counter_ns()
        decision_cpu_start = time.process_time_ns()
        effective_method, policy_features = build_feature_policy(
            n, len(edges), mode, query_count, update_count, cfg["memory_budget_bytes"]
        )
        policy_decision_ms = (time.perf_counter_ns() - decision_start) / 1e6
        policy_decision_cpu_ms = (time.process_time_ns() - decision_cpu_start) / 1e6
    else:
        effective_method = requested_method

    if mode == "dynamic" and effective_method == "python_csr":
        raise ValueError("CSR is immutable and cannot participate in dynamic updates")
    warmup(effective_method, cfg.get("library"))
    gc.collect()
    rss_before = current_rss_bytes()
    cpu_start = time.process_time_ns()
    workload_start = time.perf_counter_ns()
    build_start = time.perf_counter_ns()
    graph = _new_backend(effective_method, n, edges, cfg.get("library"))
    build_ns = time.perf_counter_ns() - build_start
    rss_after_build_with_input = current_rss_bytes()
    del edges
    gc.collect()
    rss_after_build = current_rss_bytes()

    marks = array("I", [0]) * n if effective_method in (
        "python_compact", "python_csr", "online_controller"
    ) else None
    stack = []
    controller = None
    if effective_method == "online_controller":
        from phase3_bench import OnlineCostController
        controller = OnlineCostController(probe_every=10**9)
    update_ns = 0
    query_ns = 0
    query_latencies = []
    batch_latencies = []
    phase_query_ns = {}
    observed_answers = []
    epoch = 1
    batch_output = bytearray()

    for action in actions:
        kind = action["kind"]
        phase = action["phase"]
        if kind in ("add", "remove"):
            pairs = action["edges"]
            start = time.perf_counter_ns()
            if effective_method == "rust_ffi_batch":
                changed = graph.add_edges(pairs) if kind == "add" else graph.remove_edges(pairs)
                if changed != len(pairs):
                    raise AssertionError(f"batch update changed {changed}/{len(pairs)} edges")
            else:
                for u, v in pairs:
                    changed = graph.add_edge(u, v) if kind == "add" else graph.remove_edge(u, v)
                    if not changed:
                        raise AssertionError(f"scheduled update failed: {kind} {(u, v)}")
            elapsed = time.perf_counter_ns() - start
            update_ns += elapsed
            if controller:
                controller.notify_graph_change()
            continue

        pairs = action["pairs"]
        phase_start = time.perf_counter_ns()
        if effective_method == "rust_ffi_batch":
            batch_size = cfg.get("batch_size", 16)
            for offset in range(0, len(pairs), batch_size):
                batch = pairs[offset:offset + batch_size]
                if len(batch_output) < len(batch):
                    batch_output = bytearray(len(batch))
                start = time.perf_counter_ns()
                values = graph.reachable_many(batch, batch_output)
                elapsed = time.perf_counter_ns() - start
                batch_latencies.append(elapsed)
                query_ns += elapsed
                observed_answers.extend(bool(value) for value in values)
        else:
            for source, target in pairs:
                start = time.perf_counter_ns()
                if controller:
                    result = controller.query(graph, source, target, marks, epoch, phase)
                elif effective_method == "python_sets":
                    result = reachable_set(graph, source, target)
                elif effective_method in ("python_compact", "python_csr"):
                    result = reachable_epoch(graph, source, target, marks, epoch)
                elif effective_method == "rust_ffi_single":
                    result = graph.reachable(source, target)
                else:
                    raise AssertionError(effective_method)
                elapsed = time.perf_counter_ns() - start
                query_latencies.append(elapsed)
                query_ns += elapsed
                observed_answers.append(bool(result))
                epoch += 1
                if epoch >= 0xFFFFFFFF:
                    if marks is not None:
                        marks = array("I", [0]) * n
                    epoch = 1
        phase_query_ns[phase] = phase_query_ns.get(phase, 0) + time.perf_counter_ns() - phase_start

    workload_ns = time.perf_counter_ns() - workload_start
    process_cpu_ms = (time.process_time_ns() - cpu_start) / 1e6 + policy_decision_cpu_ms
    rss_after_workload = current_rss_bytes()
    peak_rss = peak_rss_bytes()
    retained = graph.memory_bytes()
    if marks is not None:
        retained += sys.getsizeof(marks) + sys.getsizeof(stack)
    if controller:
        controller_decision_us = controller.decision_ns / 1000
    else:
        controller_decision_us = 0.0
    ffi_decomposition = measure_ffi_decomposition(graph, actions)

    last_query_action = next(action for action in reversed(actions) if action["kind"] == "query")
    from aether_cache import VersionedReachabilityCache
    cache_pairs = list(dict.fromkeys(map(tuple, last_query_action["pairs"])))[:64]
    cache_marks = array("I", [0]) * n if effective_method in (
        "python_compact", "python_csr", "online_controller"
    ) else None
    cache_epoch = [1]

    def cache_base_query(source, target):
        if effective_method == "python_sets":
            return reachable_set(graph, source, target)
        if effective_method in ("python_compact", "python_csr", "online_controller"):
            result = reachable_epoch(graph, source, target, cache_marks, cache_epoch[0])
            cache_epoch[0] += 1
            return result
        return graph.reachable(source, target)

    cache_uncached_start = time.perf_counter_ns()
    uncached_first_answers = [cache_base_query(u, v) for u, v in cache_pairs]
    uncached_second_answers = [cache_base_query(u, v) for u, v in cache_pairs]
    uncached_answers = uncached_first_answers + uncached_second_answers
    cache_uncached_two_pass_ms = (time.perf_counter_ns() - cache_uncached_start) / 1e6
    result_cache = VersionedReachabilityCache(
        graph, cache_base_query, max_entries=max(1, len(cache_pairs))
    )
    cache_first_start = time.perf_counter_ns()
    cache_first_answers = [result_cache.reachable(u, v) for u, v in cache_pairs]
    cache_first_pass_ms = (time.perf_counter_ns() - cache_first_start) / 1e6
    cache_hit_start = time.perf_counter_ns()
    cache_second_answers = [result_cache.reachable(u, v) for u, v in cache_pairs]
    cache_second_pass_ms = (time.perf_counter_ns() - cache_hit_start) / 1e6
    cache_exact = (
        cache_first_answers == uncached_first_answers
        and cache_second_answers == uncached_second_answers
    )
    if not cache_exact:
        raise AssertionError("cached repeated-query results differ from uncached calls")
    cache_before_mutation = result_cache.stats()
    cache_invalidation_supported = hasattr(graph, "add_edge") and hasattr(graph, "remove_edge")
    cache_invalidation_passed = False
    cache_invalidation_ms = 0.0
    if cache_invalidation_supported:
        mutation_pair = next(
            ((u, v) for u, v in cache_pairs if not cache_base_query(u, v)), None
        )
        if mutation_pair is not None:
            u, v = mutation_pair
            before = result_cache.reachable(u, v)
            mutation_start = time.perf_counter_ns()
            inserted = result_cache.add_edge(u, v)
            after_insert = result_cache.reachable(u, v)
            removed = result_cache.remove_edge(u, v)
            after_remove = result_cache.reachable(u, v)
            cache_invalidation_ms = (time.perf_counter_ns() - mutation_start) / 1e6
            cache_invalidation_passed = (
                before is False and inserted and after_insert is True
                and removed and after_remove is False and not graph.has_edge(u, v)
            )
            if not cache_invalidation_passed:
                raise AssertionError("cache failed to invalidate after a real insertion/removal")
    cache_final_stats = result_cache.stats()
    cache_memory_bytes = cache_before_mutation["estimated_bytes"]

    path_queries = last_query_action["pairs"][:8]
    path_start = time.perf_counter_ns()
    path_lengths = []
    for source, target in path_queries:
        found_path = shortest_path(graph, source, target)
        path_lengths.append(None if found_path is None else len(found_path) - 1)
    shortest_path_ms = (time.perf_counter_ns() - path_start) / 1e6
    neighborhood_source = path_queries[0][0] if path_queries else 0
    neighborhood_start = time.perf_counter_ns()
    neighborhood = neighbors_within_hops(graph, neighborhood_source, 2)
    neighborhood_ms = (time.perf_counter_ns() - neighborhood_start) / 1e6
    neighborhood_digest = hashlib.sha256(
        ",".join(str(node) for node in sorted(neighborhood)).encode("ascii")
    ).hexdigest()
    neighborhood_count = len(neighborhood)

    if isinstance(graph, RustDynamicGraph):
        graph.close()
    del graph
    gc.collect()

    oracle_start = time.perf_counter_ns()
    oracle_answers, oracle_adjacency, final_edges = _independent_validation(
        path, entry, mode, actions
    )
    if observed_answers != oracle_answers:
        raise AssertionError(
            f"reachability differs from independent BFS: {requested_method}/{effective_method}"
        )
    path_oracle = [
        _shortest_distance_oracle(oracle_adjacency, source, target)
        for source, target in path_queries
    ]
    if path_lengths != path_oracle:
        raise AssertionError("shortest-path distances differ from independent BFS")
    expected_neighborhood = _neighborhood_oracle(oracle_adjacency, neighborhood_source, 2)
    expected_neighborhood_digest = hashlib.sha256(
        ",".join(str(node) for node in sorted(expected_neighborhood)).encode("ascii")
    ).hexdigest()
    if neighborhood_digest != expected_neighborhood_digest:
        raise AssertionError("two-hop neighborhood differs from independent traversal")
    oracle_ms = (time.perf_counter_ns() - oracle_start) / 1e6
    del oracle_adjacency

    positives = sum(oracle_answers)
    negatives = len(oracle_answers) - positives
    if not positives or not negatives:
        raise AssertionError("benchmark query stream must contain positive and negative answers")
    answer_digest = hashlib.sha256(bytes(oracle_answers)).hexdigest()
    phase_query_ms = {key: value / 1e6 for key, value in phase_query_ns.items()}
    return {
        "dataset_id": entry["id"],
        "dataset_sha256": cfg["dataset_sha256"],
        "mode": mode,
        "seed": seed,
        "repeat": cfg["repeat"],
        "method": requested_method,
        "effective_method": effective_method,
        "n": n,
        "initial_edges": parse_stats["normalized_directed_edges"],
        "final_edges": final_edges,
        "updates": update_count,
        "queries": query_count,
        "positive_answers": positives,
        "negative_answers": negatives,
        "build_ms": build_ns / 1e6,
        "update_ms": update_ns / 1e6,
        "query_ms": query_ns / 1e6,
        "workload_execution_wall_ms": workload_ns / 1e6,
        "workload_wall_ms": workload_ns / 1e6 + policy_decision_ms,
        "process_cpu_ms": process_cpu_ms,
        "query_latency_p50_ms": percentile_ms(query_latencies, 0.50),
        "query_latency_p95_ms": percentile_ms(query_latencies, 0.95),
        "query_latency_p99_ms": percentile_ms(query_latencies, 0.99),
        "batch_call_p50_ms": percentile_ms(batch_latencies, 0.50),
        "batch_call_p95_ms": percentile_ms(batch_latencies, 0.95),
        "batch_call_p99_ms": percentile_ms(batch_latencies, 0.99),
        "batch_calls": len(batch_latencies),
        "batch_mean_ms_per_pair": (query_ns / 1e6 / query_count) if query_count else None,
        "rss_before_build_bytes": rss_before,
        "rss_after_build_with_input_buffer_bytes": rss_after_build_with_input,
        "rss_delta_with_input_buffer_bytes": (
            rss_after_build_with_input - rss_before
            if rss_after_build_with_input is not None and rss_before is not None else None
        ),
        "rss_after_build_bytes": rss_after_build,
        "rss_delta_after_build_bytes": (
            rss_after_build - rss_before
            if rss_after_build is not None and rss_before is not None else None
        ),
        "rss_after_workload_bytes": rss_after_workload,
        "process_peak_rss_bytes": peak_rss,
        "retained_graph_bytes_estimate": retained,
        "policy_decision_ms": policy_decision_ms,
        "policy_decision_cpu_ms": policy_decision_cpu_ms,
        "policy_features": policy_features,
        "controller_decision_us": controller_decision_us,
        "controller_route_counts": controller.route_counts if controller else {},
        "controller_route_switches": controller.route_switches if controller else 0,
        **ffi_decomposition,
        "cache_unique_queries": len(cache_pairs),
        "cache_uncached_two_pass_ms": cache_uncached_two_pass_ms,
        "cache_first_pass_ms": cache_first_pass_ms,
        "cache_second_pass_ms": cache_second_pass_ms,
        "cache_cached_two_pass_ms": cache_first_pass_ms + cache_second_pass_ms,
        "cache_two_pass_benefit_pct": (
            100 * (1 - (cache_first_pass_ms + cache_second_pass_ms) / cache_uncached_two_pass_ms)
            if cache_uncached_two_pass_ms else None
        ),
        "cache_hits_before_mutation": cache_before_mutation["hits"],
        "cache_misses_before_mutation": cache_before_mutation["misses"],
        "cache_hit_ratio_before_mutation": (
            cache_before_mutation["hits"] /
            max(1, cache_before_mutation["hits"] + cache_before_mutation["misses"])
        ),
        "cache_memory_bytes_estimate": cache_memory_bytes,
        "cache_invalidation_supported": cache_invalidation_supported,
        "cache_invalidation_passed": cache_invalidation_passed,
        "cache_invalidation_ms": cache_invalidation_ms,
        "cache_invalidation_count": cache_final_stats["invalidations"],
        "cache_results_exact": cache_exact,
        "phase_query_ms": phase_query_ms,
        "shortest_path_queries": len(path_queries),
        "shortest_path_ms": shortest_path_ms,
        "shortest_path_distance_sum": sum(value for value in path_lengths if value is not None),
        "shortest_path_unreachable": sum(value is None for value in path_lengths),
        "neighborhood_source": neighborhood_source,
        "neighborhood_hops": 2,
        "neighborhood_nodes": neighborhood_count,
        "neighborhood_ms": neighborhood_ms,
        "accuracy_vs_independent_bfs": True,
        "shortest_path_matches_oracle": True,
        "neighborhood_matches_oracle": True,
        "workload_sha256": workload_sha256,
        "answer_sha256": answer_digest,
        "oracle_validation_ms_excluded": oracle_ms,
        "parse_ms": parse_ms,
        "workload_preparation_ms": prepare_ms,
        "worker_wall_ms": (time.perf_counter_ns() - wall_begin) / 1e6,
        "parse_stats": parse_stats,
        "answers": oracle_answers,
    }


def run_isolated(cfg):
    payload = json.dumps(cfg, separators=(",", ":")).encode("utf-8")
    start = time.perf_counter_ns()
    try:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            input=payload,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace")[-5000:]
        raise RuntimeError(
            f"worker failed for {cfg['dataset_id']} {cfg['mode']} {cfg['method']} seed={cfg['seed']}:\n{detail}"
        ) from exc
    parent_wall_ms = (time.perf_counter_ns() - start) / 1e6
    row = json.loads(proc.stdout)
    row["e2e_wall_ms_including_worker_startup_excluding_oracle"] = max(
        0.0, parent_wall_ms - row["oracle_validation_ms_excluded"]
    )
    row["process_wall_ms_including_oracle"] = parent_wall_ms
    row["build_order_index"] = cfg["build_order_index"]
    return row


def _numeric_median(rows, field):
    values = [row[field] for row in rows if isinstance(row.get(field), (int, float)) and row[field] is not None]
    return statistics.median(values) if values else None


def summarize(rows):
    groups = {}
    for row in rows:
        key = f"{row['dataset_id']}|{row['mode']}|{row['method']}"
        groups.setdefault(key, []).append(row)
    summary = {}
    metrics = (
        "build_ms", "update_ms", "query_ms", "workload_execution_wall_ms", "workload_wall_ms", "e2e_wall_ms_including_worker_startup_excluding_oracle",
        "process_cpu_ms", "query_latency_p50_ms", "query_latency_p95_ms", "query_latency_p99_ms",
        "batch_call_p50_ms", "batch_call_p95_ms", "batch_call_p99_ms", "batch_mean_ms_per_pair",
        "rss_delta_with_input_buffer_bytes", "rss_delta_after_build_bytes", "process_peak_rss_bytes", "retained_graph_bytes_estimate",
        "policy_decision_ms", "policy_decision_cpu_ms", "controller_decision_us", "shortest_path_ms", "neighborhood_ms",
        "cache_uncached_two_pass_ms", "cache_cached_two_pass_ms", "cache_second_pass_ms",
        "cache_two_pass_benefit_pct", "cache_hit_ratio_before_mutation", "cache_memory_bytes_estimate",
        "cache_invalidation_ms",
        "ffi_pair_pack_ms", "ffi_output_buffer_setup_ms", "ffi_pointer_setup_ms",
        "ffi_batch_real_call_ms", "ffi_batch_zero_hop_call_ms",
        "ffi_batch_compute_increment_estimate_ms", "ffi_output_view_create_ms",
        "ffi_result_copy_to_bytes_ms", "ffi_single_call_sample_ms",
    )
    for key, records in groups.items():
        method_summary = {metric: _numeric_median(records, metric) for metric in metrics}
        method_summary.update({
            "runs": len(records),
            "all_reachability_exact": all(r["accuracy_vs_independent_bfs"] for r in records),
            "all_shortest_paths_exact": all(r["shortest_path_matches_oracle"] for r in records),
            "all_neighborhoods_exact": all(r["neighborhood_matches_oracle"] for r in records),
            "all_cache_results_exact": all(r["cache_results_exact"] for r in records),
            "all_ffi_diagnostics_exact": all(r["ffi_diagnostic_exact"] is not False for r in records),
            "cache_invalidation_supported_runs": sum(r["cache_invalidation_supported"] for r in records),
            "cache_invalidation_exact_runs": sum(r["cache_invalidation_passed"] for r in records),
            "effective_methods": sorted({r["effective_method"] for r in records}),
            "queries_median": _numeric_median(records, "queries"),
            "updates_median": _numeric_median(records, "updates"),
        })
        phase_names = sorted({name for r in records for name in r["phase_query_ms"]})
        method_summary["phase_query_wall_ms_median"] = {
            name: statistics.median(r["phase_query_ms"][name] for r in records if name in r["phase_query_ms"])
            for name in phase_names
        }
        summary[key] = method_summary

    selections = {}
    datasets_modes = sorted({(r["dataset_id"], r["mode"]) for r in rows})
    for dataset_id, mode in datasets_modes:
        candidates = []
        for method in FIXED_METHODS:
            key = f"{dataset_id}|{mode}|{method}"
            if key in summary:
                candidates.append((summary[key]["workload_wall_ms"], method))
        if candidates:
            best_time, best_method = min(candidates)
            feature_key = f"{dataset_id}|{mode}|feature_policy"
            controller_key = f"{dataset_id}|{mode}|online_controller"
            selections[f"{dataset_id}|{mode}"] = {
                "best_fixed_by_observed_workload_median": best_method,
                "best_fixed_workload_wall_ms": best_time,
                "feature_policy_method": summary[feature_key]["effective_methods"] if feature_key in summary else [],
                "feature_policy_regret_vs_best_fixed_pct": (
                    100 * (summary[feature_key]["workload_wall_ms"] / best_time - 1)
                    if feature_key in summary and best_time else None
                ),
                "online_controller_regret_vs_best_fixed_pct": (
                    100 * (summary[controller_key]["workload_wall_ms"] / best_time - 1)
                    if controller_key in summary and best_time else None
                ),
            }
    return summary, selections


def total_memory_visible_bytes():
    return total_physical_memory_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="phase5_datasets.json")
    parser.add_argument("--data-dir", default="data/phase5_snap")
    parser.add_argument("--out", default="results/phase5/real_data")
    parser.add_argument("--datasets", default="email-eu-core,wiki-vote,soc-epinions1,web-google")
    parser.add_argument("--dynamic-datasets", default="email-eu-core,wiki-vote")
    parser.add_argument("--download", action="store_true", help="baixar apenas os arquivos SNAP listados no manifesto")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--queries", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--updates-per-round", type=int, default=8)
    parser.add_argument("--memory-budget-mib", type=int, default=256)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        cfg = json.load(sys.stdin)
        print(json.dumps(run_worker(cfg), separators=(",", ":")))
        return
    if min(args.seeds, args.repeats, args.rounds, args.updates_per_round, args.batch_size) < 1 or args.queries < 4:
        parser.error("seeds, repeats, rounds, updates-per-round e batch-size devem ser positivos; queries deve ser >= 4")

    root = Path(__file__).resolve().parent
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {item["id"]: item for item in manifest["datasets"]}
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    output_dir = Path(args.out)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite prior results in {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_ids = [item.strip() for item in args.datasets.split(",") if item.strip()]
    dynamic_ids = {item.strip() for item in args.dynamic_datasets.split(",") if item.strip()}
    unknown = sorted((set(selected_ids) | dynamic_ids) - set(entries))
    if unknown:
        parser.error(f"datasets missing from manifest: {unknown}")

    selected_entries = {}
    dataset_provenance = {}
    for dataset_id in selected_ids:
        entry = dict(entries[dataset_id])
        path = data_dir / dataset_id / (entry.get("filename") or entry["download_url"].rsplit("/", 1)[-1])
        if not path.exists() and args.download:
            path = download_dataset(entry, data_dir)
        if not path.exists():
            raise FileNotFoundError(f"dataset archive missing: {path}; use --download after reviewing its SNAP conditions")
        actual_hash = sha256_file(path)
        declared_hash = entry.get("sha256")
        if declared_hash and actual_hash.lower() != declared_hash.lower():
            raise ValueError(f"SHA-256 mismatch for {dataset_id}: expected {declared_hash}, got {actual_hash}")
        n, edges, parsed = load_snap_graph(path, entry)
        entry["path"] = str(path.resolve())
        entry["sha256"] = actual_hash
        entry["file_size_bytes"] = path.stat().st_size
        entry["parsed"] = parsed
        selected_entries[dataset_id] = entry
        dataset_provenance[dataset_id] = {
            "name": entry.get("name", dataset_id),
            "snap_page": entry["snap_page"],
            "download_url": entry["download_url"],
            "license_or_terms": entry.get("license_or_terms", "not stated in manifest"),
            "official_nodes": entry.get("nodes"),
            "official_edges": entry.get("edges"),
            "directed": entry.get("directed", True),
            "original_format": entry.get("original_format", "not stated"),
            "sha256_archive": actual_hash,
            "archive_bytes": path.stat().st_size,
            "parsed_counts": parsed,
        }
        print(f"verified dataset={dataset_id} nodes={n} directed_edges={len(edges)} sha256={actual_hash}", flush=True)
        del edges

    rust_compile_ms = None
    has_rust = True
    try:
        compile_start = time.perf_counter_ns()
        library = str(compile_native())
        rust_compile_ms = (time.perf_counter_ns() - compile_start) / 1e6
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        has_rust = False
        library = None
        print(f"Rust backend unavailable: {exc}", flush=True)

    rows = []
    memory_budget_bytes = args.memory_budget_mib * 1024 * 1024
    for dataset_index, dataset_id in enumerate(selected_ids):
        entry = selected_entries[dataset_id]
        path = entry["path"]
        modes = ["static"]
        if dataset_id in dynamic_ids:
            modes.append("dynamic")
        for mode in modes:
            methods = list(STATIC_METHODS if mode == "static" else DYNAMIC_METHODS)
            if not has_rust:
                methods = [m for m in methods if m not in ("rust_ffi_single", "rust_ffi_batch")]
            if not methods:
                raise RuntimeError("no benchmark methods remain")
            for seed_index in range(args.seeds):
                seed = 57000 + dataset_index * 1000 + seed_index
                for repeat in range(args.repeats):
                    shift = (seed_index + repeat + (1 if mode == "dynamic" else 0)) % len(methods)
                    order = methods[shift:] + methods[:shift]
                    for order_index, method in enumerate(order):
                        cfg = {
                            "dataset_id": dataset_id,
                            "dataset_path": path,
                            "dataset_sha256": entry["sha256"],
                            "entry": {key: value for key, value in entry.items() if key not in ("path", "parsed", "sha256", "file_size_bytes")},
                            "mode": mode,
                            "seed": seed,
                            "repeat": repeat,
                            "queries": args.queries,
                            "batch_size": args.batch_size,
                            "rounds": args.rounds,
                            "updates_per_round": args.updates_per_round,
                            "memory_budget_bytes": memory_budget_bytes,
                            "library": library,
                            "method": method,
                            "build_order_index": order_index,
                        }
                        result = run_isolated(cfg)
                        rows.append(result)
                        current = [r for r in rows if r["dataset_id"] == dataset_id and r["mode"] == mode and r["seed"] == seed and r["repeat"] == repeat]
                        if len(current) > 1:
                            reference = current[0]
                            if result["workload_sha256"] != reference["workload_sha256"]:
                                raise AssertionError("methods received different query/update streams")
                            if result["answer_sha256"] != reference["answer_sha256"]:
                                raise AssertionError("method outputs differ from the common BFS oracle")
                        print(
                            f"dataset={dataset_id} mode={mode} seed={seed} repeat={repeat} "
                            f"method={method} effective={result['effective_method']} "
                            f"total_ms={result['workload_wall_ms']:.3f} exact=1",
                            flush=True,
                        )

    out_csv = output_dir / "runs.csv"
    flat_rows = []
    for row in rows:
        flat_rows.append({
            key: json.dumps(value, sort_keys=True, separators=(",", ":"))
            if isinstance(value, (dict, list)) else value
            for key, value in row.items() if key != "answers"
        })
    fields = list(dict.fromkeys(key for row in flat_rows for key in row))
    with out_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(flat_rows)

    summary, selections = summarize(rows)
    payload = {
        "title": "AETHER Phase 5 — SNAP real-graph benchmark",
        "benchmark_version": 1,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "logical_cpus": os.cpu_count(),
            "rustc": subprocess.run(["rustc", "--version"], capture_output=True, text=True).stdout.strip() if has_rust else None,
            "total_memory_visible_bytes": total_memory_visible_bytes(),
        },
        "protocol": {
            "each_backend_runs_in_an_isolated_worker_process": True,
            "method_order": "rotated deterministically by seed and repeat",
            "warmup": "small graph and query/update calls before each measured construction",
            "same_workload": "identical SHA-256 of deterministic event/query stream per dataset, mode, seed and repeat; answers checked against a separate set-based BFS replay",
            "queries": "balanced positive/negative sampling; positives are generated by following existing directed edges, negatives originate from sink nodes when available and are verified by independent BFS",
            "dynamic_workload": "two rounds of deterministic absent-edge insertions and present-edge removals, with query windows before and after changes",
            "timing": "construction, update, query, total workload, process CPU, worker startup end-to-end excluding oracle, and parsing/preparation are separate",
            "percentiles": "per-query p50/p95/p99 for single-call methods; batch-call p50/p95/p99 and mean time per pair for FFI batch; these distributions are not interchangeable",
            "ffi_cost_decomposition": "diagnostic after the main workload: Python pair packing, output-buffer and pointer setup, raw Rust batch call, zero-hop batch floor, memoryview creation, and bytes materialization are reported separately. The zero-hop call still scans and validates pairs; real-minus-zero-hop is only an estimate of added graph processing, not pure transfer time.",
            "rss": "RSS sampled around graph construction; process peak is platform-dependent and null where no trustworthy standard-library measure is available",
            "memory": "retained graph value is an implementation-specific estimate; it is not interchangeable with RSS",
            "new_capabilities": "shortest-path reconstruction and two-hop neighborhood are timed separately and verified against independent BFS on the final state",
        },
        "methods": {
            "python_sets": "Python set adjacency with DFS and per-query visited set",
            "python_compact": "Python array('I') adjacency with reusable epoch marks",
            "python_csr": "immutable Python CSR snapshot; static workloads only",
            "rust_ffi_single": "Rust mutable rows with one FFI call per query/update",
            "rust_ffi_batch": "same Rust mutable rows with one FFI call per query/update group and caller-reused output buffer",
            "feature_policy": "pre-run rule uses node/edge counts, density, estimated memory, expected update/query ratio and budget; it does not learn these evaluation graphs",
            "online_controller": "existing EMA controller selects between exact Python set-visited and epoch-mark DFS based on observed query timings; its decision cost is included",
            "best_fixed": "reported as the lowest observed median among applicable fixed methods, not as an additional implementation",
        },
        "parameters": {
            "datasets": selected_ids,
            "dynamic_datasets": sorted(dynamic_ids & set(selected_ids)),
            "seeds_per_dataset_mode": args.seeds,
            "repeats_per_seed_method": args.repeats,
            "static_query_count_per_seed": args.queries,
            "ffi_batch_size_pairs": args.batch_size,
            "dynamic_rounds": args.rounds,
            "updates_per_round_and_direction": args.updates_per_round,
            "memory_budget_mib_for_feature_policy": args.memory_budget_mib,
            "rust_compile_ms_separately_measured": rust_compile_ms,
        },
        "datasets": dataset_provenance,
        "runs": len(rows),
        "summary": summary,
        "selection_comparison": selections,
        "limitations": [
            "Different query seeds over one public graph do not constitute independent datasets.",
            "SNAP pages consulted do not state dataset-specific licenses for the selected datasets; the unknown status is recorded and the software SNAP BSD license is not attributed to the data.",
            "BFS-based query generation intentionally balances positive and negative answers; it is not an application production trace.",
            "The feature policy is a simple fixed heuristic, not a trained predictor; its results do not establish generalization beyond the evaluated graphs.",
            "The online controller calibrates on a training query window and is measured on a later window, but graph-family diversity remains limited.",
            "No joules or FLOPs are reported; CPU time is not converted to energy.",
            "Windows is not available in the execution environment; no Windows result is claimed.",
        ],
        "output_csv": str(out_csv),
    }
    (output_dir / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"runs": len(rows), "output": str(output_dir), "summary_groups": len(summary)}, indent=2))


if __name__ == "__main__":
    main()
