import hashlib
import tempfile
import unittest
from array import array
from pathlib import Path

from aether_cache import VersionedReachabilityCache
from aether_dynamic import DynamicGraph, reachable_epoch
from aether_temporal import TemporalEdgeHistory
from phase5_temporal_bench import load_temporal_snap, run_temporal_experiment


class TemporalHistoryTests(unittest.TestCase):
    def test_ordered_events_current_and_historical_reconstruction(self):
        history = TemporalEdgeHistory(6)
        self.assertTrue(history.append(10, "add", 0, 1))
        self.assertTrue(history.append(10, "add", 1, 2))
        self.assertFalse(history.append(10, "add", 0, 1))
        self.assertTrue(history.append(20, "remove", 1, 2))
        self.assertFalse(history.has_edge(1, 2))
        at_10 = history.state_at_timestamp(10)
        at_19 = history.state_at_timestamp(19)
        at_20 = history.state_at_timestamp(20)
        self.assertTrue(at_10.has_edge(1, 2))
        self.assertTrue(at_19.has_edge(1, 2))
        self.assertFalse(at_20.has_edge(1, 2))
        self.assertEqual(history.event_count, 4)
        self.assertEqual(history.edge_count, 1)
        self.assertEqual(history.cached_snapshots, 0)
        self.assertGreater(history.log_memory_bytes, 0)

    def test_same_timestamp_uses_append_order_and_event_count_is_exact(self):
        history = TemporalEdgeHistory(4)
        history.append(5, "add", 0, 1)
        history.append(5, "remove", 0, 1)
        self.assertFalse(history.state_at_event_count(2).has_edge(0, 1))
        self.assertTrue(history.state_at_event_count(1).has_edge(0, 1))

    def test_rejects_bad_time_order_operation_and_ids(self):
        history = TemporalEdgeHistory(3)
        history.append(5, "add", 0, 1)
        with self.assertRaises(ValueError): history.append(4, "add", 1, 2)
        with self.assertRaises(ValueError): history.append(6, "update", 0, 2)
        with self.assertRaises(IndexError): history.append(6, "add", 3, 0)
        with self.assertRaises(ValueError): history.state_at_timestamp(-1)
        with self.assertRaises(IndexError): history.state_at_event_count(2)

    def test_rebuilt_snapshots_do_not_mutate_live_state(self):
        history = TemporalEdgeHistory(5)
        history.append(1, "add", 0, 1)
        snapshot = history.state_at_timestamp(1)
        snapshot.remove_edge(0, 1)
        self.assertTrue(history.has_edge(0, 1))
        history.append(2, "remove", 0, 1)
        self.assertFalse(history.has_edge(0, 1))
        self.assertFalse(snapshot.has_edge(0, 1))

    def test_temporal_file_is_stably_sorted_and_matches_independent_snapshots(self):
        with tempfile.TemporaryDirectory(prefix="aether-temporal-fixture-") as folder:
            path = Path(folder) / "events.txt"
            path.write_text(
                "# SRC DST UNIXTS\n"
                "0 1 2\n"
                "1 2 1\n"
                "2 3 1\n"
                "2 3 4\n"
                "3 4 8\n",
                encoding="utf-8",
            )
            entry = {
                "id": "temporal-fixture",
                "name": "small temporal fixture",
                "snap_page": "fixture-only",
                "download_url": "fixture-only",
                "nodes": 6,
                "temporal_events": 5,
                "static_edges": 4,
                "event_semantics": "test-only",
                "license_or_terms": "test-only",
            }
            n, events, stats, _, _ = load_temporal_snap(path, entry)
            self.assertEqual(n, 6)
            self.assertEqual([event[0] for event in events], [1, 1, 2, 4, 8])
            self.assertTrue(stats["events_reordered_by_timestamp"])
            report, rows = run_temporal_experiment(
                path, entry, hashlib.sha256(path.read_bytes()).hexdigest()
            )
            self.assertEqual(report["measurements"]["event_count"], 5)
            self.assertEqual(report["measurements"]["current_unique_directed_edges"], 4)
            self.assertTrue(all(row["exact_vs_independent_replay"] for row in rows))
            self.assertEqual(
                report["measurements"]["historical_reconstruction_max_ms"],
                max(row["reconstruction_ms"] for row in rows),
            )
            self.assertNotIn("historical_reconstruction_p95_ms", report["measurements"])
            self.assertEqual(report["architecture"]["cache_count"], 0)
            self.assertGreater(report["measurements"]["materialized_snapshots_graph_bytes_estimate"], 0)


class VersionedCacheTests(unittest.TestCase):
    def make_cache(self, n=5, capacity=4):
        graph = DynamicGraph(n, "compact")
        graph.add_edge(0, 1); graph.add_edge(1, 2)
        marks = array("I", [0]) * n
        epoch = [1]
        def query(source, target):
            value = reachable_epoch(graph, source, target, marks, epoch[0])
            epoch[0] += 1
            return value
        return graph, VersionedReachabilityCache(graph, query, capacity)

    def test_repeated_query_hits_and_capacity_is_bounded(self):
        graph, cache = self.make_cache(capacity=2)
        self.assertTrue(cache.reachable(0, 2))
        self.assertTrue(cache.reachable(0, 2))
        cache.reachable(1, 4); cache.reachable(4, 0); cache.reachable(0, 2)
        stats = cache.stats()
        self.assertGreaterEqual(stats["hits"], 1)
        self.assertLessEqual(stats["entries"], 2)
        self.assertGreater(stats["estimated_bytes"], 0)
        self.assertTrue(graph.has_edge(0, 1))

    def test_successful_insert_and_remove_invalidate_cached_answers(self):
        graph, cache = self.make_cache()
        self.assertFalse(cache.reachable(4, 0))
        self.assertFalse(cache.reachable(4, 0))
        self.assertGreaterEqual(cache.stats()["hits"], 1)
        self.assertTrue(cache.add_edge(4, 0))
        self.assertTrue(cache.reachable(4, 0))
        self.assertTrue(cache.remove_edge(4, 0))
        self.assertFalse(cache.reachable(4, 0))
        self.assertEqual(cache.stats()["invalidations"], 2)
        self.assertEqual(cache.stats()["generation"], 2)
        self.assertEqual(cache.entries, 1)

    def test_duplicate_or_missing_updates_do_not_invalidate(self):
        _, cache = self.make_cache()
        cache.reachable(0, 2)
        before = cache.stats()["invalidations"]
        self.assertFalse(cache.add_edge(0, 1))
        self.assertFalse(cache.remove_edge(3, 4))
        self.assertEqual(cache.stats()["invalidations"], before)
        self.assertEqual(cache.entries, 1)

    def test_bulk_mutation_invalidates_only_when_graph_changes(self):
        _, cache = self.make_cache()
        cache.reachable(0, 2)
        self.assertEqual(cache.add_edges([(3, 4), (3, 4)]), 1)
        self.assertEqual(cache.entries, 0)
        self.assertEqual(cache.remove_edges([(3, 4), (3, 4)]), 1)
        self.assertEqual(cache.stats()["invalidations"], 2)

    def test_invalid_cache_capacity(self):
        graph = DynamicGraph(2)
        with self.assertRaises(ValueError): VersionedReachabilityCache(graph, lambda u, v: False, 0)


if __name__ == "__main__":
    unittest.main()
