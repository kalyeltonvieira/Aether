#!/usr/bin/env python3
"""Aether minimal prototype: exact incremental reachability on an evolving graph.

Standard library only. Synthetic deterministic workload; see README for scope.
"""
from __future__ import annotations
import argparse
import json
import os
import platform
import random
import statistics
import sys
import time
import tracemalloc
from pathlib import Path


def make_workload(n: int, initial_edges: int, updates: int, queries: int, seed: int):
    rng = random.Random(seed)
    # A sparse random directed graph. Self-loops and duplicate edges are excluded.
    all_pairs = [(u, v) for u in range(n) for v in range(n) if u != v]
    rng.shuffle(all_pairs)
    total = min(initial_edges + updates, len(all_pairs))
    edges = all_pairs[:total]
    initial = edges[:min(initial_edges, total)]
    added = edges[len(initial):]
    query_pairs = [(rng.randrange(n), rng.randrange(n)) for _ in range(queries)]
    # Queries are issued at evenly spaced checkpoints as updates arrive.
    checkpoints = [min(updates, (i * updates) // max(1, queries)) for i in range(queries)]
    return initial, added, list(zip(checkpoints, query_pairs))


def bfs(n, adj, source, target, counter):
    if source == target:
        return True
    seen = {source}
    stack = [source]
    while stack:
        u = stack.pop()
        for v in adj[u]:
            counter[0] += 1
            if v == target:
                return True
            if v not in seen:
                seen.add(v)
                stack.append(v)
    return False


class IncrementalClosure:
    """Bitset transitive closure; insert edge in O(predecessors * word ops)."""
    def __init__(self, n):
        self.n = n
        self.rows = [1 << i for i in range(n)]  # reflexive closure simplifies updates
        self.cols = [1 << i for i in range(n)]
        self.work = 0
        self.edges = set()

    def add(self, u, v):
        if (u, v) in self.edges:
            return 0
        self.edges.add((u, v))
        succ = self.rows[v]
        pred_bits = self.cols[u]
        changed = 0
        x = pred_bits
        while x:
            low = x & -x
            p = low.bit_length() - 1
            old = self.rows[p]
            new = old | succ
            self.work += 1
            if new != old:
                delta = new ^ old
                self.rows[p] = new
                changed += delta.bit_count()
                y = delta
                while y:
                    bit = y & -y
                    q = bit.bit_length() - 1
                    self.cols[q] |= 1 << p
                    y ^= bit
            x ^= low
        return changed

    def query(self, u, v):
        self.work += 1
        return bool((self.rows[u] >> v) & 1)


def run_bfs(n, initial, added, scheduled):
    adj = [set() for _ in range(n)]
    for u, v in initial:
        adj[u].add(v)
    counter = [0]
    output = []
    start = time.perf_counter_ns()
    cursor = 0
    for checkpoint, (u, v) in scheduled:
        while cursor < checkpoint and cursor < len(added):
            a, b = added[cursor]
            adj[a].add(b)
            cursor += 1
        output.append(bfs(n, adj, u, v, counter))
    # Apply remaining updates so learned-item cost reflects full stream.
    while cursor < len(added):
        a, b = added[cursor]
        adj[a].add(b)
        cursor += 1
    elapsed = time.perf_counter_ns() - start
    return output, elapsed, counter[0], adj


def run_incremental(n, initial, added, scheduled):
    model = IncrementalClosure(n)
    start = time.perf_counter_ns()
    for u, v in initial:
        model.add(u, v)
    # Group queries by update checkpoint to preserve event order.
    by_checkpoint = {}
    for i, (cp, pair) in enumerate(scheduled):
        by_checkpoint.setdefault(cp, []).append((i, pair))
    output = [None] * len(scheduled)
    cursor = 0
    for checkpoint in sorted(by_checkpoint):
        while cursor < checkpoint and cursor < len(added):
            model.add(*added[cursor]); cursor += 1
        for i, (u, v) in by_checkpoint[checkpoint]:
            output[i] = model.query(u, v)
    while cursor < len(added):
        model.add(*added[cursor]); cursor += 1
    elapsed = time.perf_counter_ns() - start
    return output, elapsed, model.work, model


def estimate_bytes(obj):
    # Serialized logical payload size, not process RSS / allocator overhead.
    import pickle
    return len(pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL))


def one_run(n, initial_edges, updates, queries, seed):
    initial, added, scheduled = make_workload(n, initial_edges, updates, queries, seed)
    tracemalloc.start()
    bres, bt, bops, badj = run_bfs(n, initial, added, scheduled)
    _, bpeak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    tracemalloc.start()
    ires, it, iops, closure = run_incremental(n, initial, added, scheduled)
    _, ipeak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    if bres != ires:
        raise AssertionError('Aether disagrees with BFS oracle')
    # Persistent representation after full stream: graph adjacency vs closure rows.
    bbytes = estimate_bytes([sorted(s) for s in badj])
    ibytes = estimate_bytes(closure.rows)
    return {
        'n_nodes': n, 'initial_edges': len(initial), 'updates': len(added), 'queries': queries,
        'seed': seed, 'accuracy_vs_oracle': 1.0,
        'bfs_latency_ms': bt / 1e6, 'aether_latency_ms': it / 1e6,
        'bfs_edge_visits': bops, 'aether_bitset_row_updates_and_queries': iops,
        'bfs_peak_tracemalloc_bytes': bpeak, 'aether_peak_tracemalloc_bytes': ipeak,
        'bfs_serialized_state_bytes': bbytes, 'aether_serialized_closure_bytes': ibytes,
        'energy_joules': None, 'flops': None,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--nodes', type=int, default=120)
    p.add_argument('--initial-edges', type=int, default=360)
    p.add_argument('--updates', type=int, default=240)
    p.add_argument('--queries', type=int, default=500)
    p.add_argument('--repeats', type=int, default=5)
    p.add_argument('--seed', type=int, default=20261104)
    p.add_argument('--out', default='results')
    args = p.parse_args()
    if min(args.nodes, args.queries, args.repeats) < 1 or min(args.initial_edges, args.updates) < 0:
        p.error('invalid dimensions')
    runs = [one_run(args.nodes, args.initial_edges, args.updates, args.queries, args.seed + r) for r in range(args.repeats)]
    Path(args.out).mkdir(parents=True, exist_ok=True)
    payload = {
        'title': 'Aether minimal controlled benchmark',
        'environment': {'python': sys.version, 'platform': platform.platform(), 'cpu_count': os.cpu_count()},
        'configuration': vars(args),
        'methodology': 'Deterministic synthetic directed graph; exact reachability queries during edge insertions. BFS is the oracle and conventional baseline. Timings include edge ingestion and query work; Python tracing adds overhead. Memory peak is tracemalloc; serialized bytes are logical pickle payload, not disk/RSS.',
        'runs': runs,
        'summary': {k: statistics.median(x[k] for x in runs) for k in runs[0] if isinstance(runs[0][k], (int, float)) and runs[0][k] is not None},
        'limitations': ['No direct energy or FLOP measurement; operation counters are algorithm-specific proxies, not FLOPs.', 'Synthetic random workload; no claim of general intelligence or real-world knowledge learning.', 'Timing is Python/runtime/hardware specific; tracemalloc affects latency.', 'Aether closure can require quadratic bits and its update cost can grow with dense reachability.', 'BFS baseline stores the graph and computes each query; this is not a comparison against every conventional index/algorithm.']
    }
    out = Path(args.out)
    (out / 'benchmark.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
    import csv
    with (out / 'runs.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(runs[0])); writer.writeheader(); writer.writerows(runs)
    print(json.dumps(payload['summary'], indent=2))
    print(f"Exact agreement: 100%; files: {out/'benchmark.json'}, {out/'runs.csv'}")

if __name__ == '__main__':
    main()
