import random
import unittest
from array import array
from aether_dynamic import DynamicGraph, reachable_set, reachable_epoch


def oracle(n, edges, s, t):
    if s==t:return True
    adj=[[] for _ in range(n)]
    for u,v in edges: adj[u].append(v)
    seen={s}; stack=[s]
    while stack:
        u=stack.pop()
        for v in adj[u]:
            if v==t:return True
            if v not in seen:seen.add(v);stack.append(v)
    return False


class DynamicGraphTests(unittest.TestCase):
    def test_random_add_remove_stream_both_backends(self):
        n=25
        for backend in ('sets','compact'):
            rng=random.Random(90210)
            graph=DynamicGraph(n,backend); edges=set(); marks=array('I',[0])*n; epoch=1
            for _ in range(500):
                u,v=rng.randrange(n),rng.randrange(n)
                if rng.random()<.55:
                    changed=graph.add_edge(u,v)
                    self.assertEqual(changed,(u,v) not in edges); edges.add((u,v))
                else:
                    changed=graph.remove_edge(u,v)
                    self.assertEqual(changed,(u,v) in edges); edges.discard((u,v))
                s,t=rng.randrange(n),rng.randrange(n)
                expected=oracle(n,edges,s,t)
                self.assertEqual(reachable_set(graph,s,t),expected)
                self.assertEqual(reachable_epoch(graph,s,t,marks,epoch),expected)
                epoch+=1

    def test_missing_edge_removal_and_invalid_id(self):
        for backend in ('sets','compact'):
            g=DynamicGraph(8,backend)
            self.assertFalse(g.remove_edge(1,2))
            self.assertTrue(g.add_edge(1,2));self.assertFalse(g.add_edge(1,2))
            self.assertTrue(g.remove_edge(1,2));self.assertFalse(g.has_edge(1,2))
            with self.assertRaises(IndexError):g.add_edge(8,0)


class OnlineControllerTests(unittest.TestCase):
    def test_learns_real_query_cost_and_recalibrates_after_update(self):
        from phase3_bench import OnlineCostController
        g=DynamicGraph(20,'compact'); marks=array('I',[0])*20
        for i in range(19): g.add_edge(i,i+1)
        c=OnlineCostController()
        expected=reachable_set(g,0,19)
        self.assertEqual(c.query(g,0,19,marks,1,'wide'),expected)
        self.assertEqual(c.query(g,19,0,marks,2,'wide'),reachable_set(g,19,0))
        self.assertIsNotNone(c.route)
        self.assertEqual(c.probes,2)
        c.notify_graph_change();g.remove_edge(5,6)
        for q in range(4): c.query(g,2,18,marks,3+q,'after_remove')
        self.assertIsNotNone(c.ema['set']);self.assertIsNotNone(c.ema['epoch'])
        self.assertEqual(c.recalibrate_remaining,0)


if __name__=='__main__':unittest.main()
