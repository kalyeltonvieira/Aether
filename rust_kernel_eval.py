#!/usr/bin/env python3
"""Microbenchmark Rust vs Python reachability kernel; excludes graph building/updates."""
import argparse, csv, json, statistics, subprocess, time
from array import array
from pathlib import Path
from aether_dynamic import DynamicGraph, reachable_epoch
from phase3_bench import make_events, offset


def build_final(n, seed, query_count):
    g=DynamicGraph(n,'compact')
    for i in range(n-1): g.add_edge(i,i+1)
    for i in range(n-2): g.add_edge(i,i+offset(i,seed,n=n))
    queries=[]
    for op,u,v,phase in make_events(n,seed,query_count):
        if op=='a': g.add_edge(u,v)
        elif op=='d': g.remove_edge(u,v)
        elif phase in ('wide_after_churn','bridge_after_churn','replacement_after_churn'):
            queries.append((u,v))
    return g,queries


def python_reuse(g, s, t, marks, epoch, stack):
    if s==t:return True
    stack.clear();stack.append(s);marks[s]=epoch
    while stack:
        u=stack.pop()
        for v in g.neighbors(u):
            if v==t:return True
            if marks[v]!=epoch:
                marks[v]=epoch;stack.append(v)
    return False


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seeds',type=int,default=5);p.add_argument('--n',type=int,default=100000)
    p.add_argument('--queries',type=int,default=90);p.add_argument('--repetitions',type=int,default=10)
    p.add_argument('--out',default='results/phase3/rust_eval');a=p.parse_args()
    base=Path(__file__).resolve().parent
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    binary=out/'rust_dfs_kernel'
    subprocess.run(['rustc','-O','--edition=2021',str(base/'rust_dfs_kernel.rs'),'-o',str(binary)],check=True)
    rows=[]
    for seed in range(31001,31001+a.seeds):
        g,queries=build_final(a.n,seed,a.queries)
        marks=array('I',[0])*a.n;stack=[];epoch=1;api_answers=[]
        start=time.perf_counter_ns();cpu0=time.process_time_ns()
        for _ in range(a.repetitions):
            for s,t in queries:
                api_answers.append(reachable_epoch(g,s,t,marks,epoch));epoch+=1
        api_wall=(time.perf_counter_ns()-start);api_cpu=time.process_time_ns()-cpu0
        marks=array('I',[0])*a.n;stack=[];epoch=1;reuse_answers=[]
        start=time.perf_counter_ns();cpu0=time.process_time_ns()
        for _ in range(a.repetitions):
            for s,t in queries:
                reuse_answers.append(python_reuse(g,s,t,marks,epoch,stack));epoch+=1
        reuse_wall=(time.perf_counter_ns()-start);reuse_cpu=time.process_time_ns()-cpu0
        if api_answers!=reuse_answers:raise AssertionError('Python variants disagree')
        lines=[str(a.n),str(sum(len(g.neighbors(i)) for i in range(a.n))),str(len(queries)),str(a.repetitions)]
        for u in range(a.n):
            lines.extend(f'{u} {v}' for v in g.neighbors(u))
        lines.extend(f'{s} {t}' for s,t in queries)
        proc=subprocess.run([str(binary)],input=('\n'.join(lines)+'\n').encode(),capture_output=True,check=True)
        fields=proc.stdout.decode().strip().split()
        rust_total,rust_positive,rust_ns=int(fields[0]),int(fields[1]),int(fields[2]);rust_answers=[c=='1' for c in fields[3]]
        if rust_total!=len(reuse_answers) or rust_answers!=reuse_answers:
            raise AssertionError(f'Rust/Python result mismatch at seed {seed}')
        rows.append({'n':a.n,'seed':seed,'final_edges':sum(len(g.neighbors(i)) for i in range(a.n)),
          'queries_per_pass':len(queries),'repetitions':a.repetitions,'answers_compared':len(reuse_answers),
          'positive_fraction':sum(reuse_answers)/len(reuse_answers),'python_api_wall_ms':api_wall/1e6,
          'python_api_process_cpu_ms':api_cpu/1e6,'python_reused_stack_wall_ms':reuse_wall/1e6,
          'python_reused_stack_cpu_ms':reuse_cpu/1e6,'rust_csr_kernel_wall_ms':rust_ns/1e6,
          'rust_positive_fraction':rust_positive/rust_total,'python_api_vs_rust':api_wall/rust_ns,
          'python_reused_stack_vs_rust':reuse_wall/rust_ns})
        print(f"seed={seed} api={api_wall/1e6:.1f}ms py_reuse={reuse_wall/1e6:.1f}ms rust_kernel={rust_ns/1e6:.1f}ms",flush=True)
    with (out/'runs.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    metrics=('python_api_wall_ms','python_reused_stack_wall_ms','rust_csr_kernel_wall_ms','python_api_process_cpu_ms','python_reused_stack_cpu_ms','python_api_vs_rust','python_reused_stack_vs_rust')
    summary={'title':'Aether Rust iterative DFS kernel microbenchmark','scope':'Isolated final-graph query kernel only. Graph generation, updates, serialization, Rust process start, parsing and CSR construction are outside timed intervals. Rust uses optimized rustc -O, CSR adjacency, reusable epoch marks and reusable DFS stack. Python includes the current production compact-array API and an optimized Python loop with reusable stack. This is not an end-to-end system comparison and does not measure energy or Rust process CPU.',
      'rustc':subprocess.run(['rustc','--version'],capture_output=True,text=True,check=True).stdout.strip(),
      'n':a.n,'seeds':a.seeds,'queries_per_pass':len(queries),'repetitions':a.repetitions,'timed_answers_per_seed':len(queries)*a.repetitions,
      'exact_answers_match':True,'median':{k:statistics.median(r[k] for r in rows) for k in metrics},'runs':rows,
      'limitations':['Synthetic DAG workload and a single final graph snapshot per seed.','CSR layout is part of the Rust comparison; Rust does not yet implement Aether dynamic updates or controller.','Per-query answers are validated against both Python implementations.','Wall-clock kernel timings are sensitive to shared-host noise; five seeds are exploratory, not a production SLA.']}
    (out/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary['median'],indent=2));print('PASS: all Rust answers match Python.')

if __name__=='__main__':main()
