"""Exact mutable directed graph backends used by Aether phase 3 and 5."""
from array import array
from collections import deque
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
        if not isinstance(u, int) or isinstance(u, bool) or not isinstance(v, int) or isinstance(v, bool) or not (0 <= u < self.n and 0 <= v < self.n):
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
        if not isinstance(u, int) or isinstance(u, bool) or not 0 <= u < self.n:
            raise IndexError('node id out of range')
        return self.rows[u]

    def memory_bytes(self):
        """Approximate retained Python heap size of adjacency objects."""
        total = sys.getsizeof(self.rows)
        if self.backend == 'sets':
            total += sum(sys.getsizeof(row) + sum(sys.getsizeof(v) for v in row) for row in self.rows)
        else:
            total += sum(sys.getsizeof(row) for row in self.rows)
        return total


def _check_nodes(graph, *nodes):
    for node in nodes:
        if (not isinstance(node, int) or isinstance(node, bool)
                or not 0 <= node < graph.n):
            raise IndexError('node ids out of range')


def reachable_set(graph, source, target):
    """Exact iterative depth-first reachability using a per-query visited set."""
    _check_nodes(graph, source, target)
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
    _check_nodes(graph, source, target)
    if len(marks) != graph.n:
        raise ValueError('marks buffer length must equal graph.n')
    if not isinstance(epoch, int) or isinstance(epoch, bool) or not 0 < epoch <= 0xFFFFFFFF:
        raise ValueError('epoch must be an integer in [1, 2**32-1]')
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


def shortest_path(graph, source, target, max_depth=None):
    """Return one exact unweighted shortest path, or None if no path is in range.

    A path is a list of node IDs. ``max_depth`` bounds the number of edges;
    ``None`` means an unrestricted BFS. The search always reads current neighbors
    and intentionally does not cache results across graph mutations.
    """
    _check_nodes(graph, source, target)
    if max_depth is not None and (
        isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0
    ):
        raise ValueError('max_depth must be a non-negative integer or None')
    if source == target:
        return [source]
    if max_depth == 0:
        return None

    parent = {source: None}
    depth = {source: 0}
    queue = deque([source])
    while queue:
        current = queue.popleft()
        next_depth = depth[current] + 1
        if max_depth is not None and next_depth > max_depth:
            continue
        for neighbor in graph.neighbors(current):
            if neighbor in parent:
                continue
            parent[neighbor] = current
            depth[neighbor] = next_depth
            if neighbor == target:
                path = [target]
                while path[-1] != source:
                    path.append(parent[path[-1]])
                path.reverse()
                return path
            queue.append(neighbor)
    return None


def neighbors_within_hops(graph, source, max_hops=1):
    """Return nodes at shortest distance 1..max_hops from ``source``.

    The source is excluded from the returned set even if a self-loop or cycle
    leads back to it. This helper evaluates the current graph on every call.
    """
    if not isinstance(source, int) or isinstance(source, bool) or not 0 <= source < graph.n:
        raise IndexError('node id out of range')
    if isinstance(max_hops, bool) or not isinstance(max_hops, int) or max_hops < 1:
        raise ValueError('max_hops must be a positive integer')

    distances = {source: 0}
    queue = deque([source])
    while queue:
        current = queue.popleft()
        distance = distances[current]
        if distance >= max_hops:
            continue
        for neighbor in graph.neighbors(current):
            if neighbor not in distances:
                distances[neighbor] = distance + 1
                queue.append(neighbor)
    return set(distances).difference((source,))
