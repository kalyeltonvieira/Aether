#!/usr/bin/env python3
"""Phase 4 end-to-end experiments for mutable Aether reachability.

Python generates the common synthetic workload outside the per-strategy timer.
Each strategy runs in a fresh child process; subprocess wall time is separately
reported. Rust owns the live graph after a single bulk import through ctypes.
"""
from __future__ import annotations
import argparse, csv, gc, json, math, os, random, statistics, subprocess, sys, time
from array import array
from pathlib import Path

from aether.graph.dynamic import DynamicGraph, reachable_set, reachable_epoch
from aether.native.bindings import RustDynamicGraph, compile_native
from aether.metrics import current_rss_bytes as portable_current_rss_bytes, memory_delta_bytes, peak_rss_kib, total_memory_bytes

METHODS = ("python_current", "python_optimized", "rust_ffi", "legacy_controller", "new_policy", "python_csr", "python_rebuild")


def component_spans(n, parts=4):
    return [(i * n // parts, (i + 1) * n // parts) for i in range(parts)]


def shortcut_starts(n, family="sparse_chain"):
    if family == "disconnected":
        return [u for lo, hi in component_spans(n) for u in range(lo, hi - 2, 3)]
    return list(range(0, n - 2, 3))


def iter_initial_edges(n, family="sparse_chain"):
    if family == "dense_small":
        if n > 2000: raise ValueError("dense_small is restricted to n <= 2000")
        for u in range(n):
            for v in range(u + 1, min(n, u + 33)):
                yield u, v
    elif family == "disconnected":
        for lo, hi in component_spans(n):
            for u in range(lo, hi - 1): yield u, u + 1
            for u in range(lo, hi - 2, 3): yield u, u + 2
    else:
        for u in range(n - 1): yield u, u + 1
        for u in range(0, n - 2, 3): yield u, u + 2


def initial_edge_count(n, family="sparse_chain"):
    if family == "dense_small":
        return sum(min(32, n - 1 - u) for u in range(n))
    if family == "disconnected":
        return sum((hi - lo - 1) + len(range(lo, hi - 2, 3)) for lo, hi in component_spans(n))
    return (n - 1) + len(range(0, n - 2, 3))


def make_events(n, profile, queries, update_pairs, seed, family="sparse_chain"):
    rng = random.Random(seed ^ 0xAE7E4004)
    events = []
    if profile in ("stable", "query_heavy", "dense_stable"):
        for i in range(queries):
            slot = i % 6
            if slot == 0: q = (0, n - 1)
            elif slot == 1: q = (n - 1, 0)
            elif slot == 2: q = (n // 4, min(n - 1, 3 * n // 4))
            elif slot == 3: q = (min(n - 1, 3 * n // 4), n // 4)
            else: q = (rng.randrange(n), rng.randrange(n))
            events.append(("q", q[0], q[1], "stable"))
        return events

    early = max(1, (queries - 3) // 3)
    middle = max(0, (queries - 3) // 3)
    late = max(0, queries - 3 - early - middle)
    for i in range(early):
        if profile == "shift" and i % 2 == 0: s, t = 0, n - 1
        elif profile == "shift": s, t = n - 1, 0
        elif i % 3 == 0: s, t = 0, n - 1
        elif i % 3 == 1: s, t = n - 1, 0
        else: s, t = rng.randrange(n), rng.randrange(n)
        events.append(("q", s, t, "before_change"))

    candidates = shortcut_starts(n, family)
    available = max(1, len(candidates))
    changes = []
    for j in range(min(update_pairs, available)):
        u = candidates[(j * 7919 + seed) % available]
        if u + 3 < n: changes.append(u)

    def local_query(i, phase):
        u = (i * 97 + seed) % max(1, n - 4)
        if profile == "shift": s, t = u, u + 1
        elif i % 2: s, t = u, min(n - 1, u + 2)
        else: s, t = min(n - 1, u + 2), u
        return ("q", s, t, phase)

    if profile == "prolonged":
        # Interleave batches of mutations, explicit rebuild checkpoints and queries.
        change_i = 0
        for i in range(middle):
            groups_left = middle - i
            batch = math.ceil((len(changes) - change_i) / groups_left) if groups_left else 0
            for u in changes[change_i:change_i + batch]:
                events.extend((("d", u, u + 2, "churn"), ("a", u, u + 3, "churn")))
            change_i += batch
            events.append(("r", 0, 0, "rebuild_checkpoint"))
            events.append(local_query(i, "between_bursts"))
        if change_i < len(changes):
            for u in changes[change_i:]:
                events.extend((("d", u, u + 2, "churn"), ("a", u, u + 3, "churn")))
            events.append(("r", 0, 0, "rebuild_checkpoint"))
    else:
        for u in changes:
            events.extend((("d", u, u + 2, "churn"), ("a", u, u + 3, "churn")))
        events.append(("r", 0, 0, "rebuild_checkpoint"))
        for i in range(middle): events.append(local_query(i, "after_change"))

    # Explicit deletion sentinel: true before removal, false after, true after restore.
    events.append(("q", n - 2, n - 1, "sentinel_before"))
    events.append(("d", n - 2, n - 1, "sentinel_remove"))
    events.append(("r", 0, 0, "rebuild_after_remove"))
    events.append(("q", n - 2, n - 1, "sentinel_after_remove"))
    events.append(("a", n - 2, n - 1, "sentinel_restore"))
    events.append(("r", 0, 0, "rebuild_after_restore"))
    events.append(("q", n - 2, n - 1, "sentinel_after_restore"))

    for i in range(late):
        u = (i * 193 + seed) % max(1, n - 4)
        if profile == "shift": s, t = u, min(n - 1, u + 1 + (i % 3))
        elif i % 2: s, t = n - 1, 0
        else: s, t = 0, n - 1
        events.append(("q", s, t, "late"))
    return events


def current_rss_bytes():
    """Sample current resident/working-set bytes, or None when unavailable."""
    return portable_current_rss_bytes()


def hardware_info():
    import platform
    memory_bytes = total_memory_bytes()
    return {
        "cpu_model": platform.processor() or "unknown",
        "logical_cpu_count": os.cpu_count(),
        "total_memory_kib": None if memory_bytes is None else memory_bytes // 1024,
        "machine": platform.machine(),
        "python_platform": sys.platform,
    }


def percentile(values, p):
    if not values: return None
    if p >= .95 and len(values) < 100: return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]


def epoch_reuse(graph, source, target, marks, epoch, stack):
    if source == target: return True
    stack.clear(); stack.append(source); marks[source] = epoch
    while stack:
        u = stack.pop()
        for v in graph.neighbors(u):
            if v == target: return True
            if marks[v] != epoch:
                marks[v] = epoch; stack.append(v)
    return False


class CsrGraph:
    """Immutable CSR snapshot for stable-query workload only."""
    def __init__(self, n, edges):
        self.n = n
        counts = array("Q", [0]) * n
        for u, _ in edges: counts[u] += 1
        self.offsets = array("Q", [0]) * (n + 1)
        for i, count in enumerate(counts): self.offsets[i + 1] = self.offsets[i] + count
        cursor = array("Q", self.offsets[:-1])
        self.edges = array("I", [0]) * len(edges)
        for u, v in edges:
            pos = cursor[u]; self.edges[pos] = v; cursor[u] += 1
        self.rows = None

    def reachable(self, source, target, marks, epoch, stack):
        if source == target: return True
        stack.clear(); stack.append(source); marks[source] = epoch
        while stack:
            u = stack.pop()
            for i in range(self.offsets[u], self.offsets[u + 1]):
                v = self.edges[i]
                if v == target: return True
                if marks[v] != epoch:
                    marks[v] = epoch; stack.append(v)
        return False

    def memory_bytes(self):
        import sys
        return sys.getsizeof(self.offsets) + sys.getsizeof(self.edges)


def build_python_graph(method, n, edges):
    backend = "sets" if method == "python_current" else "compact"
    graph = DynamicGraph(n, backend)
    for u, v in edges: graph.add_edge(u, v)
    return graph


def graph_oracle(n, events, family="sparse_chain"):
    adj = {}
    for u, v in iter_initial_edges(n, family): adj.setdefault(u, set()).add(v)
    answers = []
    for op, u, v, _ in events:
        if op == "a": adj.setdefault(u, set()).add(v)
        elif op == "d": adj.get(u, set()).discard(v)
        elif op == "r": continue
        else:
            if u == v: result = True
            else:
                seen = {u}; stack = [u]; result = False
                while stack:
                    x = stack.pop()
                    for y in adj.get(x, ()):
                        if y == v: result = True; stack.clear(); break
                        if y not in seen: seen.add(y); stack.append(y)
            answers.append(bool(result))
    return answers


def warmup(method, library):
    if method in ("rust_ffi",):
        with RustDynamicGraph(64, ((i, i + 1) for i in range(63)), library=library) as g:
            assert g.reachable(0, 63) and not g.reachable(63, 0)
            g.remove_edge(62, 63); assert not g.reachable(0, 63)
    else:
        g = DynamicGraph(64, "sets" if method == "python_current" else "compact")
        for i in range(63): g.add_edge(i, i + 1)
        if method == "python_current": assert reachable_set(g, 0, 63)
        else:
            marks = array("I", [0]) * 64
            assert epoch_reuse(g, 0, 63, marks, 1, [])


def run_worker(cfg):
    n, seed, profile = cfg["n"], cfg["seed"], cfg["profile"]
    family = cfg.get("family", "sparse_chain")
    method, library = cfg["method"], cfg.get("library")
    events = make_events(n, profile, cfg["queries"], cfg["update_pairs"], seed, family)
    initial = list(iter_initial_edges(n, family))
    warmup(method, library)
    gc.collect()
    rss_before = current_rss_bytes()
    marks = None
    stack = []
    answers, qlatencies = [], []
    graph = None; controller = None; decision_ns = 0
    t0 = time.perf_counter_ns(); cpu0 = time.process_time_ns()

    if method == "rust_ffi":
        tbuild = time.perf_counter_ns(); graph = RustDynamicGraph(n, initial, library=library)
        build_ns = time.perf_counter_ns() - tbuild
    elif method == "python_csr":
        if profile not in ("stable", "query_heavy", "dense_stable"):
            raise ValueError("CSR snapshot is valid only when workload has no mutations")
        tbuild = time.perf_counter_ns(); graph = CsrGraph(n, initial)
        marks = array("I", [0]) * n
        build_ns = time.perf_counter_ns() - tbuild
    elif method in ("python_current", "python_optimized", "legacy_controller", "new_policy", "python_rebuild"):
        if method == "python_rebuild":
            edge_state = set(initial)
            graph = build_python_graph("python_optimized", n, initial)
            marks = array("I", [0]) * n
            build_ns = time.perf_counter_ns() - t0
        elif method == "new_policy":
            tdecision = time.perf_counter_ns()
            estimated_m = initial_edge_count(n, family)
            sets_est = 72 * n + 156 * estimated_m
            compact_est = 64 * n + 32 * estimated_m
            csr_est = 8 * (n + 1) + 4 * estimated_m
            budget = int(cfg["memory_budget_bytes"])
            if (profile in ("stable", "query_heavy", "dense_stable") and sets_est > budget
                    and csr_est <= budget and csr_est < compact_est):
                selected = "csr"
            elif (sets_est > budget and compact_est <= budget) or (n >= 10000 and cfg["queries"] >= cfg["update_pairs"]):
                selected = "compact"
            else:
                selected = "sets"
            decision_ns = time.perf_counter_ns() - tdecision
            if selected == "csr":
                if profile not in ("stable", "query_heavy", "dense_stable"): selected = "compact"
                else:
                    graph = CsrGraph(n, initial)
                    marks = array("I", [0]) * n
            if graph is None:
                graph = build_python_graph("python_current" if selected == "sets" else "python_optimized", n, initial)
        else:
            graph = build_python_graph(method, n, initial)
        if (method in ("python_optimized", "legacy_controller")
                or (method == "new_policy" and not isinstance(graph, CsrGraph)
                    and getattr(graph, "backend", None) == "compact")):
            marks = array("I", [0]) * n
        build_ns = time.perf_counter_ns() - t0
        if method == "legacy_controller":
            from benchmarks.phase3.phase3_bench import OnlineCostController
            controller = OnlineCostController()
    else:
        raise ValueError(f"unknown method {method}")

    rss_after_build_with_import_buffer = current_rss_bytes()
    # Drop common workload edge tuples after each implementation owns its graph.
    del initial; gc.collect()
    rss_after_build = current_rss_bytes()

    update_ns = 0; rebuild_ns = 0
    for op, u, v, phase in events:
        if op == "q":
            tq = time.perf_counter_ns()
            if method == "python_current": result = reachable_set(graph, u, v)
            elif method in ("python_optimized", "python_rebuild"):
                result = epoch_reuse(graph, u, v, marks, len(answers) + 1, stack)
            elif method == "rust_ffi": result = graph.reachable(u, v)
            elif method == "python_csr": result = graph.reachable(u, v, marks, len(answers) + 1, stack)
            elif method == "legacy_controller": result = controller.query(graph, u, v, marks, len(answers) + 1, phase)
            elif method == "new_policy":
                if isinstance(graph, CsrGraph): result = graph.reachable(u, v, marks, len(answers) + 1, stack)
                elif graph.backend == "sets": result = reachable_set(graph, u, v)
                else: result = epoch_reuse(graph, u, v, marks, len(answers) + 1, stack)
            else: raise AssertionError(method)
            qlatencies.append(time.perf_counter_ns() - tq); answers.append(bool(result))
        elif op in ("a", "d"):
            tu = time.perf_counter_ns()
            if method == "python_rebuild":
                edge = (u, v)
                if op == "a":
                    changed = edge not in edge_state
                    if changed: edge_state.add(edge)
                else:
                    changed = edge in edge_state
                    if changed: edge_state.remove(edge)
            else:
                changed = graph.add_edge(u, v) if op == "a" else graph.remove_edge(u, v)
            update_ns += time.perf_counter_ns() - tu
            if not changed: raise AssertionError(f"scheduled update did not change graph: {op} {(u,v)}")
            if controller: controller.notify_graph_change()
        elif op == "r" and method == "python_rebuild":
            tr = time.perf_counter_ns()
            rebuilt = DynamicGraph(n, "compact")
            for x, y in edge_state: rebuilt.add_edge(x, y)
            graph = rebuilt
            rebuild_ns += time.perf_counter_ns() - tr
    workload_wall_ns = time.perf_counter_ns() - t0
    process_cpu_ns = time.process_time_ns() - cpu0
    rss_after_workload = current_rss_bytes()
    peak_rss_kib_value = peak_rss_kib()
    heap_bytes = graph.memory_bytes()
    if method == "python_rebuild":
        import sys as _sys
        heap_bytes += (_sys.getsizeof(edge_state) + sum(_sys.getsizeof(edge) for edge in edge_state)
                       + sum(_sys.getsizeof(u) + _sys.getsizeof(v) for u, v in edge_state))
    if marks is not None:
        import sys as _sys
        heap_bytes += _sys.getsizeof(marks) + _sys.getsizeof(stack)
    edge_count = initial_edge_count(n, family) + sum(1 if e[0] == "a" else -1 if e[0] == "d" else 0 for e in events)
    if method == "rust_ffi": graph.close()

    # Independent BFS oracle replays the identical event stream after measurements.
    oracle_start = time.perf_counter_ns()
    oracle = graph_oracle(n, events, family)
    oracle_wall_ms = (time.perf_counter_ns() - oracle_start) / 1e6
    if answers != oracle:
        raise AssertionError(f"answer mismatch: {method}, n={n}, seed={seed}, profile={profile}")
    qs = [e for e in events if e[0] == "q"]
    expected = {"sentinel_before": True, "sentinel_after_remove": False, "sentinel_after_restore": True}
    phase_names = [q[3] for q in qs]
    sentinel_results = ({phase: answers[phase_names.index(phase)] for phase in expected}
                        if all(phase in phase_names for phase in expected) else {})
    if profile not in ("stable", "query_heavy", "dense_stable") and sentinel_results != expected:
        raise AssertionError(f"sentinel failure: {sentinel_results}")

    return {
        "n": n, "seed": seed, "profile": profile, "family": family, "method": method,
        "selected_representation": ("rust_vec_rows" if method == "rust_ffi" else
                                     "compact_rebuild+edge_set" if method == "python_rebuild" else
                                     "csr" if isinstance(graph, CsrGraph) else
                                     getattr(graph, "backend", "policy")),
        "initial_edges": initial_edge_count(n, family), "final_edges": edge_count,
        "event_count": len(events), "updates": sum(e[0] in ("a", "d") for e in events),
        "rebuilds": sum(e[0] == "r" for e in events) if method == "python_rebuild" else 0,
        "queries": len(answers), "build_ms": build_ns / 1e6,
        "update_ms": update_ns / 1e6, "rebuild_ms": rebuild_ns / 1e6,
        "query_ms": sum(qlatencies) / 1e6,
        "workload_wall_ms": workload_wall_ns / 1e6,
        "process_cpu_ms": process_cpu_ns / 1e6,
        "query_p50_ms": percentile(qlatencies, .50) / 1e6,
        "query_p95_ms": (percentile(qlatencies, .95) / 1e6) if len(qlatencies) >= 100 else None,
        "query_p99_ms": (percentile(qlatencies, .99) / 1e6) if len(qlatencies) >= 100 else None,
        "rss_before_build_bytes": rss_before,
        "rss_after_build_bytes": rss_after_build_with_import_buffer,
        "rss_after_initial_buffer_release_bytes": rss_after_build,
        "rss_delta_after_build_bytes": memory_delta_bytes(rss_after_build_with_import_buffer, rss_before),
        "rss_delta_after_initial_buffer_release_bytes": memory_delta_bytes(rss_after_build, rss_before),
        "rss_after_workload_bytes": rss_after_workload,
        "process_peak_rss_kib": peak_rss_kib_value,
        "retained_graph_bytes_estimate": heap_bytes,
        "edge_list_packed_payload_bytes": 8 * edge_count,
        "csr_packed_payload_bytes_final_snapshot": 8 * (n + 1) + 4 * edge_count,
        "policy_decision_us": decision_ns / 1000,
        "controller_decision_us": ((controller.decision_ns / 1000) if controller else decision_ns / 1000),
        "controller_probes": controller.probes if controller else 0,
        "controller_route_switches": controller.route_switches if controller else 0,
        "controller_route_counts": controller.route_counts if controller else {},
        "accuracy_vs_bfs": True, "oracle_validation_ms_excluded": oracle_wall_ms,
        "positive_answers": sum(answers),
        "negative_answers": len(answers) - sum(answers), "sentinels": sentinel_results,
    }


def worker_main():
    cfg = json.load(sys.stdin)
    result = run_worker(cfg)
    print(json.dumps(result, separators=(",", ":")))


def run_isolated(cfg):
    data = json.dumps(cfg, separators=(",", ":")).encode()
    start = time.perf_counter_ns()
    try:
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker"],
                              input=data, capture_output=True, check=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"worker failed for {cfg['method']} n={cfg['n']} profile={cfg['profile']}:\n{detail}") from exc
    process_wall_ms = (time.perf_counter_ns() - start) / 1e6
    result = json.loads(proc.stdout)
    result["process_wall_ms_including_oracle"] = process_wall_ms
    result["e2e_wall_ms_including_worker_startup"] = max(0.0, process_wall_ms - result["oracle_validation_ms_excluded"])
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="results/phase4")
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--large-seeds", type=int, default=1)
    p.add_argument("--small-only", action="store_true")
    p.add_argument("--worker", action="store_true")
    p.add_argument("--memory-budget-mib", type=int, default=256)
    args = p.parse_args()
    if args.worker:
        worker_main(); return

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    # Compilation is measured once separately, not charged to steady-state graph work.
    compile_start = time.perf_counter_ns()
    lib_path = compile_native()
    lib_compile_ms = (time.perf_counter_ns() - compile_start) / 1e6

    configs = []
    for n, q, updates in ((1000, 120, 80), (10000, 90, 80), (100000, 36, 40)):
        for profile in ("stable", "churn", "shift"):
            for seed in range(41000, 41000 + args.seeds):
                configs.append({"n": n, "queries": q, "update_pairs": 0 if profile == "stable" else updates // 2,
                                "profile": profile, "seed": seed})
    for seed in range(41500, 41500 + args.seeds):
        configs.append({"n": 1000, "queries": 3000, "update_pairs": 0,
                        "profile": "query_heavy", "seed": seed})
    for seed in range(41600, 41600 + args.large_seeds):
        configs.append({"n": 1000, "queries": 120, "update_pairs": 0,
                        "profile": "dense_stable", "family": "dense_small", "seed": seed})
        configs.append({"n": 1000, "queries": 120, "update_pairs": 40,
                        "profile": "disconnected", "family": "disconnected", "seed": seed})
    if not args.small_only:
        for n, q, pairs in ((1000, 300, 120), (10000, 180, 300), (100000, 90, 800)):
            for seed in range(43000, 43000 + args.large_seeds):
                configs.append({"n": n, "queries": q, "update_pairs": pairs,
                                "profile": "prolonged", "seed": seed})
    if not args.small_only:
        for n in (500000, 1000000):
            for seed in range(42000, 42000 + args.large_seeds):
                configs.append({"n": n, "queries": 8, "update_pairs": 20, "profile": "churn", "seed": seed})

    methods = list(METHODS)
    all_rows = []
    memory_budget = args.memory_budget_mib * 1024 * 1024
    for config in configs:
        n, profile, seed = config["n"], config["profile"], config["seed"]
        # CSR is a valid baseline only for the stable, no-update scenario.
        static_profile = profile in ("stable", "query_heavy", "dense_stable")
        available_methods = ([m for m in methods if m != "python_rebuild"] if static_profile
                             else [m for m in methods if m != "python_csr"])
        # Deterministic rotation avoids always giving a method the same order position.
        shift = seed % len(available_methods)
        order = available_methods[shift:] + available_methods[:shift]
        print(f"n={n} profile={profile} seed={seed} methods={len(order)}", flush=True)
        per_config = []
        for method in order:
            cfg = {**config, "method": method, "library": str(lib_path),
                   "memory_budget_bytes": memory_budget}
            result = run_isolated(cfg)
            per_config.append(result); all_rows.append(result)
        answers = {(r["method"], r["accuracy_vs_bfs"]) for r in per_config}
        if any(not ok for _, ok in answers): raise AssertionError("oracle mismatch")
        if not static_profile:
            sentinels = [r["sentinels"] for r in per_config]
            if any(s != {"sentinel_before": True, "sentinel_after_remove": False,
                         "sentinel_after_restore": True} for s in sentinels):
                raise AssertionError("mutation sentinel mismatch")

    fields = list(dict.fromkeys(k for row in all_rows for k, v in row.items() if not isinstance(v, (dict, list))))
    with (out / "runs.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        for row in all_rows: writer.writerow({k: v for k, v in row.items() if k in fields})

    grouped = {}
    for cfg in configs:
        key = f"{cfg['n']}|{cfg['profile']}"
        grouped[key] = {}
        rs = [r for r in all_rows if r["n"] == cfg["n"] and r["profile"] == cfg["profile"]]
        for method in sorted(set(r["method"] for r in rs)):
            mr = [r for r in rs if r["method"] == method]
            metrics = ("build_ms", "update_ms", "rebuild_ms", "rebuilds", "query_ms", "workload_wall_ms", "e2e_wall_ms_including_worker_startup",
                       "process_cpu_ms", "query_p50_ms", "query_p95_ms", "query_p99_ms",
                       "rss_delta_after_build_bytes", "process_peak_rss_kib", "retained_graph_bytes_estimate",
                       "edge_list_packed_payload_bytes", "csr_packed_payload_bytes_final_snapshot",
                       "policy_decision_us", "controller_decision_us", "controller_probes", "controller_route_switches",
                       "positive_answers", "negative_answers")
            grouped[key][method] = {m: (statistics.median(float(r[m]) for r in mr if r[m] is not None)
                                          if any(r[m] is not None for r in mr) else None) for m in metrics}
            grouped[key][method]["accuracy_all_seeds"] = all(r["accuracy_vs_bfs"] for r in mr)
            grouped[key][method]["representations"] = sorted(set(r["selected_representation"] for r in mr))
            if method == "new_policy":
                grouped[key][method]["policy_decision_us_median_in_runs"] = statistics.median(r["policy_decision_us"] for r in mr)
            if method == "legacy_controller":
                route_totals = {}
                for r in mr:
                    for route, count in r["controller_route_counts"].items():
                        route_totals[route] = route_totals.get(route, 0) + count
                grouped[key][method]["route_counts_all_runs"] = route_totals

    summary = {
        "title": "Aether phase 4 end-to-end mutable reachability",
        "protocol": "Each strategy runs in an isolated Python process on a deterministic, identical workload. Python generation of the common initial-edge/query/update workload is outside per-strategy algorithm timings; construction/import, FFI calls, updates, queries, and strategy-level event handling are timed. Whole worker subprocess wall time including startup is recorded separately. Rust owns its live graph after bulk import (no persistent Python mirror); import buffer and ctypes boundary costs are included in build/query/update measurements. Native library compilation is a one-time separately measured setup cost.",
        "python": sys.version, "platform": sys.platform, "cpu_count": os.cpu_count(),
        "hardware": hardware_info(),
        "rustc": subprocess.run(["rustc", "--version"], capture_output=True, text=True, check=True).stdout.strip(),
        "rust_library_compile_ms_separately_measured": lib_compile_ms,
        "rust_abi": "ctypes C ABI; mutable Vec<Vec<u32>> rows, reusable marks and DFS stack; no per-query serialization or graph copy; one bulk import then one FFI call per update/query.",
        "methods": {
            "python_current": "Python sets with per-query visited set and DFS stack.",
            "python_optimized": "Python array('I') adjacency, uint32 epoch marks and reused DFS stack.",
            "rust_ffi": "Mutable Rust Vec<Vec<u32>> graph with reusable marks/stack; one ctypes call per update/query; one initial bulk copy.",
            "legacy_controller": "Phase 3 online EMA strategy controller on compact arrays; controller decision cost instrumented separately.",
            "new_policy": "One-time feature/memory-budget policy chooses sets, compact rows or static CSR; no live conversion.",
            "python_csr": "Immutable Python CSR snapshot; static workloads only, conversion/build included.",
            "python_rebuild": "Active edge set plus compact snapshot rebuilt from scratch at explicit checkpoints; update and rebuild costs separated.",
        }, "memory_budget_mib_for_new_policy": args.memory_budget_mib,
        "latency_percentile_policy": "P50 recorded for all non-empty query samples; P95 and P99 are null when fewer than 100 queries were measured in that run.",
        "configurations": configs, "runs": len(all_rows), "summary": grouped,
        "memory_policy": "One-time, pre-build feature decision; never converts a live graph. Estimates set heap as 72*n+156*m, compact heap as 64*n+32*m, and CSR payload as 8*(n+1)+4*m based on Phase 3 sparse graphs. CSR is selected only on static workloads where sets exceed the memory budget and the CSR snapshot fits; the query-heavy pilot showed pure-Python CSR slower than sets, so query count alone does not trigger conversion. Otherwise the policy considers memory budget and n/query-to-update features to choose compact or sets. Hypothesis under evaluation, not a universal policy.",
        "limitations": ["Synthetic workloads only; 500k and 1m use one seed by default due to their higher memory/query cost.",
                        "Python CSR is read-only and therefore only compared on stable/no-update workloads; mutable workloads use exact sets, compact arrays, Rust row vectors, or edge-set plus rebuild checkpoints.",
                        "Rust Vec<Vec<u32>> is mutation-friendly but not CSR; CSR payload is measured separately for immutable graphs.",
                        "Process startup included in e2e worker wall time; compiler setup is reported separately.",
                        "RSS/heap values are process-level and estimates have allocator/interpreter limitations; no energy/FLOPs claimed."],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"runs": len(all_rows), "lib_compile_ms": lib_compile_ms,
                      "scenarios": {k: v for k, v in grouped.items()}}, indent=2))
    print(f"PASS: {len(all_rows)} runs; every query agrees with independent BFS; wrote {out}")


if __name__ == "__main__":
    main()
