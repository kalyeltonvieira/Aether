"""Concurrent execution helpers with isolated graph handles for AETHER phase 6."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from time import perf_counter_ns

from aether.graph.dynamic import reachable_epoch


def parallel_reachability(graph_factory, n: int, edges, pairs, *, workers: int = 4) -> tuple[list[bool], dict]:
    """Run exact reachability with independent graph instances per worker.

    ``graph_factory`` receives ``(n, edges)`` and must return an independent
    graph handle. The graph is never mutated during query execution. Build and
    query costs are reported separately so parallelism cannot hide copying.
    """
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be a positive integer")
    pair_list = list(pairs)
    if not pair_list:
        return [], {
            "workers": workers,
            "queries": 0,
            "build_ms": 0.0,
            "query_ms": 0.0,
            "total_ms": 0.0,
            "isolated_handles": 0,
        }
    chunks = [
        [(position, pair) for position, pair in enumerate(pair_list) if position % workers == index]
        for index in range(min(workers, len(pair_list)))
    ]
    started_build = perf_counter_ns()
    graphs = [graph_factory(n, edges) for _ in chunks]
    build_ms = (perf_counter_ns() - started_build) / 1_000_000

    def run(index_and_pairs):
        index, chunk = index_and_pairs
        graph = graphs[index]
        marks = [0] * n
        return [
            (position, bool(reachable_epoch(graph, source, target, marks, offset + 1)))
            for offset, (position, (source, target)) in enumerate(chunk)
        ]

    started_query = perf_counter_ns()
    with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
        completed = list(pool.map(run, enumerate(chunks)))
    query_ms = (perf_counter_ns() - started_query) / 1_000_000
    results = [False] * len(pair_list)
    for worker_results in completed:
        for position, value in worker_results:
            results[position] = value
    return results, {
        "workers": len(chunks),
        "queries": len(pair_list),
        "build_ms": build_ms,
        "query_ms": query_ms,
        "total_ms": build_ms + query_ms,
        "isolated_handles": len(graphs),
    }
