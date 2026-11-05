"""Exact mutable directed graph backends used by Aether phase 3."""
from array import array
import sys


class DynamicGraph:
    def __init__(self, n, backend='compact'):
        if n < 1 or backend not in ('compact', 'sets'):
            raise ValueError('n must be positive; backend must be compact or sets')
        self.n, self.backend = n, backend
        self.rows = [set() for _ in range(n)] if backend == 'sets' else [array('I') for _ in range(n)]
        if backend == 'compact' and array('I').itemsize != 4:
            raise RuntimeError('compact backend requires 32-bit unsigned array items')

    def _check(self, u, v):
        if not isinstance(u, int) or not isinstance(v, int) or not (0 <= u < self.n and 0 <= v < self.n):
            raise IndexError('node ids out of range')

    def has_edge(self, u, v):
        self._check(u, v)
        return v in self.rows[u]

    def add_edge(self, u, v):
        self._check(u, v)
        row = self.rows[u]
        if v in row:
            return False
        row.add(v) if self.backend == 'sets' else row.append(v)
        return True

    def remove_edge(self, u, v):
        self._check(u, v)
        row = self.rows[u]
        if self.backend == 'sets':
            if v not in row: return False
            row.remove(v); return True
        try:
            i = row.index(v)
        except ValueError:
            return False
        last = len(row) - 1
        if i != last: row[i] = row[last]
        row.pop()
        return True

    def neighbors(self, u):
        return self.rows[u]

    def memory_bytes(self):
        """Approximate retained Python heap size of adjacency objects."""
        total = sys.getsizeof(self.rows)
        if self.backend == 'sets':
            total += sum(sys.getsizeof(row) + sum(sys.getsizeof(v) for v in row) for row in self.rows)
        else:
            total += sum(sys.getsizeof(row) for row in self.rows)
        return total


def reachable_set(graph, source, target):
    """Exact iterative depth-first reachability using a per-query visited set."""
    if source == target: return True
    seen, stack = {source}, [source]
    while stack:
        u = stack.pop()
        for v in graph.neighbors(u):
            if v == target: return True
            if v not in seen:
                seen.add(v); stack.append(v)
    return False


def reachable_epoch(graph, source, target, marks, epoch):
    """Exact iterative depth-first reachability with reusable uint32 stamps."""
    if source == target: return True
    stack = [source]
    marks[source] = epoch
    while stack:
        u = stack.pop()
        for v in graph.neighbors(u):
            if v == target: return True
            if marks[v] != epoch:
                marks[v] = epoch
                stack.append(v)
    return False
