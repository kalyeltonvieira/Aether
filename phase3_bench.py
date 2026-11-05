#!/usr/bin/env python3
"""Aether phase 3: scale, dynamic updates, compact storage, online cost learning."""
from __future__ import annotations
import argparse, csv, json, os, random, resource, statistics, subprocess, sys, time, gc
from pathlib import Path
from array import array
from aether_dynamic import DynamicGraph, reachable_set, reachable_epoch

METHODS = [('sets','set'),('sets','epoch'),('compact','set'),('compact','epoch'),('compact','adaptive')]


def offset(i, seed, shift=0, n=1000):
    span=max(1,n-i-2)
    return 2 + ((i * 2654435761 + seed * 97 + shift) % span)


def make_events(n, seed, queries):
    rng = random.Random(seed ^ 0xAE7E3)
    # A forward-only DAG creates positive and negative reachability queries.
    # Update bursts remove chain bridges and shortcuts so some answers change.
    k = max(10, n // 100)
    q1, q2, q3 = queries // 3, queries // 3, queries - 2 * (queries // 3)
    eligible=[i for i in range(n-3) if offset(i,seed,n=n)>2]
    chosen=rng.sample(eligible,k)
    events=[]
    for _ in range(q1-1): events.append(('q',rng.randrange(n),rng.randrange(n),'wide'))
    # This pair is true on the intact chain, then false after its bridge is removed.
    bridge=chosen[0]
    events.append(('q',bridge,bridge+1,'bridge_before_removal'))
    for i in chosen:
        events.append(('d',i,i+1,'update1'))
        events.append(('d',i,i+offset(i,seed,n=n),'update1'))
    for i in chosen: events.append(('a',i,i+2,'update1'))
    events.append(('q',bridge,bridge+1,'bridge_after_removal'))
    for j in range(q2-1):
        u=chosen[j%len(chosen)]
        v=u+2 if j%2==0 else u+1
        events.append(('q',u,v,'local_after_change'))
    for i in chosen: events.append(('d',i,i+2,'update2'))
    for i in chosen: events.append(('a',i,i+3,'update2'))
    for _ in range(q3-2): events.append(('q',rng.randrange(n),rng.randrange(n),'wide_after_churn'))
    events.append(('q',bridge,bridge+1,'bridge_after_churn'))
    events.append(('q',bridge,bridge+3,'replacement_after_churn'))
    return events


def current_rss_bytes():
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'): return int(line.split()[1])*1024
    except OSError: pass
    return 0


class OnlineCostController:
    """Learns query cost from real requests; exploration never duplicates a query."""
    def __init__(self, alpha=.5, calibration_queries=4, probe_every=96):
        self.alpha=alpha; self.calibration_queries=calibration_queries; self.probe_every=probe_every
        self.ema={'set':None,'epoch':None}; self.queries=0; self.probes=0
        self.recalibrate_remaining=0; self.route='epoch'; self.route_switches=0
        self.route_counts={}; self.phase_counts={}

    def notify_graph_change(self):
        # A changed topology can change BFS exploration cost; discard stale
        # averages and spend four real queries alternating the exact alternatives.
        self.ema={'set':None,'epoch':None}
        self.recalibrate_remaining=4

    def _observe(self, key, ns):
        old=self.ema[key]
        self.ema[key]=ns if old is None else self.alpha*ns+(1-self.alpha)*old

    def query(self, graph, s, t, marks, epoch, phase):
        methods={'set':lambda:reachable_set(graph,s,t), 'epoch':lambda:reachable_epoch(graph,s,t,marks,epoch)}
        if self.queries < self.calibration_queries:
            # Four real requests, alternating candidates, form initial calibration;
            # epoch BFS is the conservative default until another route wins clearly.
            selected='set' if self.queries % 2 == 0 else 'epoch'
            self.probes+=1
        elif self.recalibrate_remaining:
            # Alternate two samples per route after a topology change.
            selected=('set' if self.route=='epoch' else 'epoch') if self.recalibrate_remaining % 2 == 0 else self.route
            self.probes+=1
        elif self.queries % self.probe_every == 0:
            selected='set' if self.route=='epoch' else 'epoch'
            self.probes+=1
        else:
            selected=self.route
        start=time.perf_counter_ns(); result=methods[selected](); elapsed=time.perf_counter_ns()-start
        self._observe(selected,elapsed)
        if self.recalibrate_remaining: self.recalibrate_remaining-=1
        if self.ema['set'] is not None and self.ema['epoch'] is not None:
            best=min(self.ema,key=self.ema.get)
            if self.route is None:
                self.route=best
            elif best != self.route and self.ema[best] < .8*self.ema[self.route]:
                self.route=best; self.route_switches+=1
        self.route_counts[selected]=self.route_counts.get(selected,0)+1
        phase_counts=self.phase_counts.setdefault(phase,{})
        phase_counts[selected]=phase_counts.get(selected,0)+1
        self.queries+=1
        return result


def run_worker(n, seed, queries, backend, method):
    events=make_events(n,seed,queries)
    rss_before=current_rss_bytes()
    graph=DynamicGraph(n,backend)
    t0=time.perf_counter_ns(); c0=time.process_time_ns()
    for i in range(n-1): graph.add_edge(i,i+1)
    for i in range(n-2): graph.add_edge(i,i+offset(i,seed,n=n))
    build_wall=(time.perf_counter_ns()-t0)/1e6
    rss_after_build=current_rss_bytes()
    marks=array('I',[0])*n
    answers=[]; query_phase={}; upd_by_phase={}; upd_count=0; qwall=0.0; u_wall=0.0
    controller=OnlineCostController() if method=='adaptive' else None
    epoch=1
    for op,u,v,phase in events:
        if op=='q':
            start=time.perf_counter_ns()
            if controller: result=controller.query(graph,u,v,marks,epoch,phase)
            elif method=='set': result=reachable_set(graph,u,v)
            else: result=reachable_epoch(graph,u,v,marks,epoch)
            elapsed=(time.perf_counter_ns()-start)/1e6
            qwall+=elapsed; query_phase[phase]=query_phase.get(phase,0.0)+elapsed
            answers.append(bool(result)); epoch+=1
            if epoch>=0xFFFFFFFE: marks=array('I',[0])*n; epoch=1
        else:
            start=time.perf_counter_ns()
            changed=graph.add_edge(u,v) if op=='a' else graph.remove_edge(u,v)
            elapsed=(time.perf_counter_ns()-start)/1e6
            u_wall+=elapsed
            upd_by_phase[phase]=upd_by_phase.get(phase,0.0)+elapsed
            if not changed: raise AssertionError(f'expected edge change failed: {op} {(u,v)}')
            if controller: controller.notify_graph_change()
            upd_count+=1
    cpu_ms=(time.process_time_ns()-c0)/1e6
    rss_after=current_rss_bytes(); peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    retained=graph.memory_bytes()
    total_wall=build_wall+u_wall+qwall
    return {'n':n,'seed':seed,'backend':backend,'method':method,'initial_edges':2*n-3,
      'updates':upd_count,'queries':len(answers),'build_ms':build_wall,'update_ms':u_wall,
      'query_ms':qwall,'total_ms':total_wall,'process_cpu_ms':cpu_ms,
      'rss_before_graph_bytes':rss_before,'rss_after_build_bytes':rss_after_build,
      'rss_delta_after_build_bytes':rss_after_build-rss_before,
      'rss_after_workload_bytes':rss_after,'process_peak_rss_kib':peak_kib,
      'retained_graph_heap_bytes_estimate':retained,'controller_probes':controller.probes if controller else 0,
      'controller_route_switches':controller.route_switches if controller else 0,
      'controller_final_ema_ns':controller.ema if controller else {},
      'controller_route_counts':controller.route_counts if controller else {},
      'controller_phase_routes':controller.phase_counts if controller else {},
      'phase_query_wall_ms':query_phase,'phase_update_wall_ms':upd_by_phase,
      'positive_answers':sum(answers),'negative_answers':len(answers)-sum(answers),
      'answers':answers}


def isolated(cfg):
    proc=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker'],input=json.dumps(cfg).encode(),capture_output=True,check=True)
    return json.loads(proc.stdout)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seeds',type=int,default=5); p.add_argument('--out',default='results/phase3')
    p.add_argument('--worker',action='store_true'); a=p.parse_args()
    if a.worker:
        d=json.load(sys.stdin); print(json.dumps(run_worker(**d))); return
    scales=[(1000,300),(10000,180),(100000,90)]
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for n,q in scales:
        print(f'nodes={n} queries={q} seeds={a.seeds}',flush=True)
        for seed in range(31001,31001+a.seeds):
            run_results={}
            for backend,method in METHODS:
                cfg={'n':n,'seed':seed,'queries':q,'backend':backend,'method':method}
                res=isolated(cfg); run_results[(backend,method)]=res
            reference=run_results[('sets','set')]['answers']
            q1,q2= q//3, q//3
            if not reference[q1-1] or reference[q1] or reference[-2] or not reference[-1]:
                raise AssertionError(f'expected sentinel reachability transitions failed: n={n} seed={seed}')
            if not any(reference) or all(reference):
                raise AssertionError(f'workload lacks both positive and negative queries: n={n} seed={seed}')
            if any(r['answers']!=reference for r in run_results.values()):
                raise AssertionError(f'answers disagree at n={n} seed={seed}')
            for (backend,method),r in run_results.items():
                rows.append({k:v for k,v in r.items() if k!='answers'})
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with (out/'runs.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    summary={}
    for n,q in scales:
        summary[str(n)]={}
        for backend,method in METHODS:
            rs=[r for r in rows if r['n']==n and r['backend']==backend and r['method']==method]
            keys=('build_ms','update_ms','query_ms','total_ms','process_cpu_ms','rss_delta_after_build_bytes','rss_after_build_bytes','process_peak_rss_kib','retained_graph_heap_bytes_estimate','positive_answers','negative_answers')
            summary[str(n)][f'{backend}+{method}']={k:statistics.median(float(r[k]) for r in rs) for k in keys}
            summary[str(n)][f'{backend}+{method}']['accuracy_all_seeds']=True
            if method=='adaptive':
                routes={}
                phases={}
                for r in rs:
                    for route,count in r['controller_route_counts'].items(): routes[route]=routes.get(route,0)+count
                    for phase,counts in r['controller_phase_routes'].items():
                        dest=phases.setdefault(phase,{})
                        for route,count in counts.items(): dest[route]=dest.get(route,0)+count
                summary[str(n)][f'{backend}+{method}']['route_counts_all_seeds']=routes
                summary[str(n)][f'{backend}+{method}']['phase_routes_all_seeds']=phases
                summary[str(n)][f'{backend}+{method}']['median_probes']=statistics.median(r['controller_probes'] for r in rs)
                summary[str(n)][f'{backend}+{method}']['median_route_switches']=statistics.median(r['controller_route_switches'] for r in rs)
    payload={'title':'Aether phase 3 scale and dynamic benchmark','python':sys.version,'platform':sys.platform,'cpu_count':os.cpu_count(),
      'seeds_per_scale':a.seeds,'runs':len(rows),'workload':'Forward-only DAG (chain plus deterministic forward shortcuts); wide random queries include both reachable (s<t) and unreachable (s>t) pairs. First update burst removes chain bridges and shortcuts, then inserts new edges; local queries target inserted edges; second burst replaces these edges with different shortcuts, followed by wide queries. Removals change reachable answers. Exact iterative DFS runs over current adjacency, so no stale closure facts survive deletions.',
      'methods':'Set-backed iterative DFS; epoch-stamped uint32-array DFS; adaptive DFS controller executes each real query once, alternates strategies during initial calibration, records observed exponential-moving-average costs, recalibrates on graph changes and only switches on a measured 20% advantage. Graph storage: Python sets vs per-node array(I) compact adjacency. Each process generates its own deterministic workload.',
      'memory':'RSS sampled from /proc/self/status before/after graph build and after workload; process peak RSS from resource.ru_maxrss. Retained adjacency Python heap estimate counts container and neighbor object sizes. Values include interpreter/runtime; resident memory deltas are more informative than peak RSS for the graph structure.',
      'energy':'not measured; no joules inferred. FLOPs not applicable to this integer graph workload and not fabricated.',
      'limitations':['Synthetic workload, five seeds default; not an externally representative graph dataset.','100k-node cases use sparse degree-two base graph and 90 queries, not dense or adversarial worst case.','Deletion correctness comes from search over current adjacency rather than a fully dynamic transitive-closure algorithm.','Online controller adapts query traversal only; storage backend is fixed per run.','Compact arrays support unsigned 32-bit node identifiers.'],
      'summary':summary}
    (out/'summary.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2));print(f'PASS: {len(rows)} process-runs, exact agreement; {out}')

if __name__=='__main__':main()
