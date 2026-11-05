"""Minimal adaptive exact reachability engine for an evolving directed graph.

The caller supplies a rough workload forecast. Cost coefficients are pilot-fitted
for this project's Python benchmark and are not portable across environments.
"""

class AdaptiveReachability:
    def __init__(self, n, initial_edges=(), *, expected_updates=0, expected_queries=0):
        if n < 1 or expected_updates < 0 or expected_queries < 0:
            raise ValueError('n must be positive and workload forecasts non-negative')
        self.n = n
        initial_edges = list(initial_edges)
        self.expected_updates = expected_updates
        self.expected_queries = expected_queries
        self.estimated_costs_ns = self.estimate_costs(n, len(initial_edges), expected_updates, expected_queries)
        self.strategy = min(self.estimated_costs_ns, key=self.estimated_costs_ns.get)
        self.updates_seen = 0
        self.queries_seen = 0
        if self.strategy == 'aether_rows_only':
            self.rows = [1 << i for i in range(n)]
            self.adjacency = None
            for u, v in initial_edges:
                self.add_edge(u, v)
            self.updates_seen = 0
        else:
            self.rows = None
            self.adjacency = [0] * n
            for u, v in initial_edges:
                self._check_node(u); self._check_node(v)
                self.adjacency[u] |= 1 << v

    @staticmethod
    def estimate_costs(n, initial_edges, expected_updates, expected_queries):
        e = initial_edges + expected_updates
        return {
            'aether_rows_only': 55 * n * e + 130 * expected_queries,
            'bitset_bfs': 140 * e + 6000 * (n / 120) * expected_queries,
        }

    def _check_node(self, node):
        if not isinstance(node, int) or not 0 <= node < self.n:
            raise IndexError(f'node must be an integer in [0, {self.n})')

    def add_edge(self, source, target):
        self._check_node(source); self._check_node(target)
        if self.strategy == 'aether_rows_only':
            successors = self.rows[target]
            source_bit = 1 << source
            for i, old in enumerate(self.rows):
                if old & source_bit:
                    self.rows[i] = old | successors
        else:
            self.adjacency[source] |= 1 << target
        self.updates_seen += 1

    def reachable(self, source, target):
        self._check_node(source); self._check_node(target)
        self.queries_seen += 1
        if self.strategy == 'aether_rows_only':
            return bool((self.rows[source] >> target) & 1)
        if source == target:
            return True
        goal = 1 << target
        visited = frontier = 1 << source
        while frontier:
            pending, neighbors = frontier, 0
            while pending:
                bit = pending & -pending
                neighbors |= self.adjacency[bit.bit_length() - 1]
                pending ^= bit
            if neighbors & goal:
                return True
            frontier = neighbors & ~visited
            if not frontier:
                return False
            visited |= frontier
        return False

    def stats(self):
        return {
            'strategy': self.strategy,
            'updates_seen': self.updates_seen,
            'queries_seen': self.queries_seen,
            'estimated_costs_ns': dict(self.estimated_costs_ns),
        }
