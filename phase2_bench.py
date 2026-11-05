#!/usr/bin/env python3
"""Phase 2 controlled dynamic-reachability benchmark; standard library only."""
from __future__ import annotations
import argparse, csv, json, os, pickle, random, statistics, subprocess, sys, time
from pathlib import Path
from aether_metrics import peak_rss_bytes

ALGORITHMS = ('bfs', 'bitset_bfs', 'incremental_closure_dual', 'aether_rows_only', 'adaptive')


def choose_strategy(n, edge_count, update_count, query_count):
    """Empirical nanosecond cost model calibrated on the phase-2 pilot medians.

    Model scope: this Python runtime and graph workloads similar to the tested
    random directed graphs. Costs include a conservative per-edge row scan and
    per-query constants; callers retain exactness whichever path is selected.
    """
    edges = edge_count + update_count
    closure_ns = 55 * n * edges + 130 * query_count
    bitset_ns = 140 * edges + 6000 * (n / 120) * query_count
    selected = 'aether_rows_only' if closure_ns < bitset_ns else 'bitset_bfs'
    return selected, {'estimated_closure_ms': closure_ns / 1e6,
                      'estimated_bitset_ms': bitset_ns / 1e6}


def make_workload(n, initial_edges, updates, queries, seed):
    pairs = [(u, v) for u in range(n) for v in range(n) if u != v]
    random.Random(seed).shuffle(pairs)
    total = min(initial_edges + updates, len(pairs))
    initial, added = pairs[:min(initial_edges, total)], pairs[min(initial_edges, total):total]
    rng = random.Random(seed ^ 0xA37E)
    scheduled = [(min(updates, (i * updates) // max(1, queries)), rng.randrange(n), rng.randrange(n)) for i in range(queries)]
    return initial, added, scheduled


def worker(algorithm, n, initial, added, scheduled):
    requested_algorithm = algorithm
    estimate = {}
    if algorithm == 'adaptive':
        algorithm, estimate = choose_strategy(n, len(initial), len(added), len(scheduled))
    cpu_start_ns = time.process_time_ns()
    upd_ns = query_ns = build_ns = 0
    true_count = 0
    operations = 0
    if algorithm == 'bfs':
        adj = [set() for _ in range(n)]
        t = time.perf_counter_ns()
        for u, v in initial: adj[u].add(v)
        build_ns += time.perf_counter_ns() - t
        def insert(u, v): adj[u].add(v)
        def reachable(s, target):
            nonlocal operations
            if s == target: return True
            seen, stack = {s}, [s]
            while stack:
                u = stack.pop()
                for v in adj[u]:
                    operations += 1
                    if v == target: return True
                    if v not in seen: seen.add(v); stack.append(v)
            return False
        state = adj
    elif algorithm == 'bitset_bfs':
        adj = [0] * n
        t = time.perf_counter_ns()
        for u, v in initial: adj[u] |= 1 << v
        build_ns += time.perf_counter_ns() - t
        def insert(u, v): adj[u] |= 1 << v
        def reachable(s, target):
            nonlocal operations
            goal = 1 << target
            if s == target: return True
            visited = frontier = 1 << s
            while frontier:
                x, neighbors = frontier, 0
                while x:
                    low = x & -x
                    neighbors |= adj[low.bit_length() - 1]
                    operations += 1
                    x ^= low
                if neighbors & goal: return True
                frontier = neighbors & ~visited
                if not frontier: return False
                visited |= frontier
            return False
        state = adj
    elif algorithm == 'incremental_closure_dual':
        rows, cols = [1 << i for i in range(n)], [1 << i for i in range(n)]
        def insert(u, v):
            nonlocal operations
            succ, x = rows[v], cols[u]
            while x:
                low = x & -x
                p = low.bit_length() - 1
                old = rows[p]
                new = old | succ
                if new != old:
                    delta = new ^ old
                    rows[p] = new
                    while delta:
                        bit = delta & -delta
                        cols[bit.bit_length() - 1] |= 1 << p
                        operations += 1
                        delta ^= bit
                operations += 1
                x ^= low
        t = time.perf_counter_ns()
        for u, v in initial: insert(u, v)
        build_ns += time.perf_counter_ns() - t
        def reachable(s, target): return bool((rows[s] >> target) & 1)
        state = (rows, cols)
    else:
        # Exact incremental closure without a duplicated transpose. Recompute
        # predecessors by scanning row bitsets, trading O(n) checks/update for
        # fewer Python-level per-relation transpose writes and half the index.
        rows = [1 << i for i in range(n)]
        def insert(u, v):
            nonlocal operations
            source_bit, succ = 1 << u, rows[v]
            for p, old in enumerate(rows):
                operations += 1
                if old & source_bit:
                    rows[p] = old | succ
        t = time.perf_counter_ns()
        for u, v in initial: insert(u, v)
        build_ns += time.perf_counter_ns() - t
        def reachable(s, target): return bool((rows[s] >> target) & 1)
        state = rows

    outputs = []
    cursor = 0
    for checkpoint, s, target in scheduled:
        end = min(checkpoint, len(added))
        if cursor < end:
            t = time.perf_counter_ns()
            while cursor < end:
                insert(*added[cursor]); cursor += 1
            upd_ns += time.perf_counter_ns() - t
        t = time.perf_counter_ns(); result = reachable(s, target); query_ns += time.perf_counter_ns() - t
        outputs.append(result); true_count += result
    if cursor < len(added):
        t = time.perf_counter_ns()
        while cursor < len(added): insert(*added[cursor]); cursor += 1
        upd_ns += time.perf_counter_ns() - t
    cpu_ms = (time.process_time_ns() - cpu_start_ns) / 1e6
    serialized = len(pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL))
    peak_bytes = peak_rss_bytes()
    rss_kib = peak_bytes / 1024 if peak_bytes is not None else None
    return {'algorithm': requested_algorithm, 'selected_strategy': algorithm,
            **estimate, 'build_ms': build_ns / 1e6, 'update_ms': upd_ns / 1e6,
            'query_ms': query_ns / 1e6, 'total_ms': (build_ns + upd_ns + query_ns) / 1e6,
            'process_cpu_ms': cpu_ms,
            'process_peak_rss_kib': rss_kib, 'operation_proxy': operations,
            'serialized_state_bytes': serialized, 'positive_queries': true_count,
            'answers': outputs}


def isolated(algorithm, n, initial, added, scheduled):
    data = json.dumps({'algorithm': algorithm, 'n': n, 'initial': initial, 'added': added, 'scheduled': scheduled}).encode()
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'], input=data, capture_output=True, check=True)
    return json.loads(proc.stdout)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', default='results/phase2')
    p.add_argument('--seeds', type=int, default=30)
    p.add_argument('--worker', action='store_true')
    args = p.parse_args()
    if args.worker:
        d=json.load(sys.stdin); print(json.dumps(worker(d['algorithm'],d['n'],d['initial'],d['added'],d['scheduled']))); return
    configs = [
        {'label':'small_sparse_low_reuse','n':60,'initial_edges':120,'updates':60,'queries':100},
        {'label':'medium_sparse','n':120,'initial_edges':360,'updates':240,'queries':500},
        {'label':'medium_dense','n':120,'initial_edges':1800,'updates':600,'queries':500},
        {'label':'larger_sparse_query_heavy','n':240,'initial_edges':720,'updates':480,'queries':1000},
        {'label':'static_many_queries','n':120,'initial_edges':360,'updates':0,'queries':20000},
    ]
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    records=[]
    for cfg in configs:
        print(f"scenario={cfg['label']} seeds={args.seeds}",flush=True)
        for seed in range(20261104,20261104+args.seeds):
            initial,added,scheduled=make_workload(cfg['n'],cfg['initial_edges'],cfg['updates'],cfg['queries'],seed)
            results={a:isolated(a,cfg['n'],initial,added,scheduled) for a in ALGORITHMS}
            oracle=results['bfs']['answers']
            valid=all(r['answers']==oracle for r in results.values())
            if not valid: raise AssertionError(f"oracle disagreement: {cfg['label']} {seed}")
            for algo,r in results.items():
                records.append({**cfg,'seed':seed,'algorithm':algo,'accuracy_vs_bfs':1.0,
                    **{k:v for k,v in r.items() if k not in ('algorithm','answers')}})
    fields=list(dict.fromkeys(k for row in records for k in row))
    with (out/'runs.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(records)
    grouped={}
    for cfg in configs:
        label=cfg['label']; grouped[label]={}
        for algo in ALGORITHMS:
            rows=[r for r in records if r['label']==label and r['algorithm']==algo]
            grouped[label][algo]={k:statistics.median(float(x[k]) for x in rows) for k in ('build_ms','update_ms','query_ms','total_ms','process_cpu_ms','operation_proxy','process_peak_rss_kib','serialized_state_bytes')}
            grouped[label][algo]['accuracy_all_seeds']=all(x['accuracy_vs_bfs']==1 for x in rows)
            if algo == 'adaptive':
                grouped[label][algo]['selected_strategies']={s:sum(x['selected_strategy']==s for x in rows) for s in sorted(set(x['selected_strategy'] for x in rows))}
                grouped[label][algo]['estimated_closure_ms']=statistics.median(float(x['estimated_closure_ms']) for x in rows)
                grouped[label][algo]['estimated_bitset_ms']=statistics.median(float(x['estimated_bitset_ms']) for x in rows)
    payload={'title':'Aether phase 2 benchmark','python':sys.version,'platform':sys.platform,'cpu_count':os.cpu_count(),
      'methodology':'Synthetic deterministic directed graphs; 30 seeds by default per scenario. Each strategy executes in a separate child process for isolated peak RSS. Wall-clock timing uses no tracing/profiler and separates initial build, updates and queries; process CPU time is measured independently across algorithm work. BFS is exact oracle; bitset_bfs is conventional frontier search using integer adjacency masks; incremental_closure_dual maintains rows plus a transpose; aether_rows_only tests removal of the duplicate transpose; adaptive applies a cost model calibrated on phase-2 pilot medians to choose between bitset_bfs and aether_rows_only. Timings exclude process launch, data generation, serialization and output. No direct energy or FLOP measurement.',
      'configurations':configs,'seeds_per_configuration':args.seeds,'runs':len(records),'summary':grouped,
      'controller_model':'closure_ns = 55*n*(initial_edges+updates)+130*queries; bitset_ns = 140*(initial_edges+updates)+6000*(n/120)*queries. Coefficients are approximate pilot-derived nanosecond costs for this interpreter/hardware and tested graph family, not portable constants. The lower predicted-cost strategy is selected; compare actual measured totals to predictions.',
      'limits':['Synthetic random workloads only.','Process peak RSS is reported in KiB using the platform API; null denotes an unavailable OS measurement. It includes the interpreter and workload input.','Operation proxy counts differ by algorithm and are not FLOPs.','No direct energy measurement.','Controller coefficients require recalibration on new hardware or workload families.']}
    (out/'summary.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
    print(json.dumps(grouped,indent=2))
    print(f"PASS: {len(records)} strategy-runs, exact answers; outputs at {out}")

if __name__=='__main__': main()
