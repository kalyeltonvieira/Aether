import shutil
import tempfile
import unittest
from pathlib import Path

from aether_native import RustDynamicGraph, compile_native
from phase4_bench import run_worker


class RustDynamicGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("rustc") is None:
            raise unittest.SkipTest("rustc is not installed")
        cls.tmp = tempfile.TemporaryDirectory(prefix="aether-native-test-")
        cls.library = compile_native(Path(cls.tmp.name) / "libaether_native.so")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            cls.tmp.cleanup()

    def test_initial_graph_positive_negative_and_identity(self):
        with RustDynamicGraph(6, [(0, 1), (1, 2), (2, 5)], self.library) as graph:
            self.assertTrue(graph.reachable(0, 5))
            self.assertFalse(graph.reachable(5, 0))
            self.assertTrue(graph.reachable(3, 3))
            self.assertEqual(graph.edge_count(), 3)
            self.assertGreater(graph.memory_bytes(), 0)

    def test_updates_duplicates_missing_edges_and_invalid_ids(self):
        with RustDynamicGraph(5, [(0, 1), (1, 2)], self.library) as graph:
            self.assertFalse(graph.add_edge(0, 1))
            self.assertFalse(graph.remove_edge(2, 3))
            self.assertTrue(graph.add_edge(2, 3))
            self.assertTrue(graph.reachable(0, 3))
            self.assertTrue(graph.remove_edge(2, 3))
            self.assertFalse(graph.reachable(0, 3))
            self.assertFalse(graph.has_edge(2, 3))
            for action in (lambda: graph.add_edge(5, 0), lambda: graph.remove_edge(0, 5),
                           lambda: graph.has_edge(5, 0), lambda: graph.reachable(0, 5)):
                with self.assertRaises(IndexError): action()

    def test_duplicate_edges_rejected_during_bulk_import(self):
        with self.assertRaises(ValueError):
            RustDynamicGraph(3, [(0, 1), (0, 1)], self.library)

    def test_end_to_end_dynamic_scenarios_match_oracle(self):
        for method in ("python_current", "python_optimized", "rust_ffi", "legacy_controller", "new_policy", "python_rebuild"):
            result = run_worker({"n": 40, "seed": 41007, "profile": "churn", "queries": 18,
                                 "update_pairs": 4, "method": method, "library": str(self.library),
                                 "memory_budget_bytes": 256 * 1024 * 1024})
            self.assertTrue(result["accuracy_vs_bfs"], method)
            self.assertEqual(result["sentinels"], {"sentinel_before": True,
                                                    "sentinel_after_remove": False,
                                                    "sentinel_after_restore": True})
            self.assertGreater(result["queries"], 0)
            if method == "python_rebuild": self.assertGreater(result["rebuilds"], 0)

    def test_csr_stable_workload_matches_oracle(self):
        result = run_worker({"n": 40, "seed": 41008, "profile": "stable", "queries": 12,
                             "update_pairs": 0, "method": "python_csr", "library": str(self.library),
                             "memory_budget_bytes": 256 * 1024 * 1024})
        self.assertTrue(result["accuracy_vs_bfs"])
        self.assertGreater(result["retained_graph_bytes_estimate"], 0)

    def test_new_policy_uses_csr_only_under_memory_pressure(self):
        common = {"n": 1000, "seed": 41500, "profile": "query_heavy", "queries": 3000,
                  "update_pairs": 0, "method": "new_policy", "library": str(self.library)}
        normal = run_worker({**common, "memory_budget_bytes": 256 * 1024 * 1024})
        pressured = run_worker({**common, "memory_budget_bytes": 100_000})
        self.assertEqual(normal["selected_representation"], "sets")
        self.assertEqual(pressured["selected_representation"], "csr")
        self.assertTrue(normal["accuracy_vs_bfs"] and pressured["accuracy_vs_bfs"])

    def test_dense_and_disconnected_graph_families(self):
        dense = run_worker({"n": 40, "seed": 41600, "profile": "dense_stable", "family": "dense_small",
                            "queries": 12, "update_pairs": 0, "method": "python_csr",
                            "library": str(self.library), "memory_budget_bytes": 256 * 1024 * 1024})
        disconnected = run_worker({"n": 100, "seed": 41600, "profile": "disconnected",
                                   "family": "disconnected", "queries": 18, "update_pairs": 4,
                                   "method": "rust_ffi", "library": str(self.library),
                                   "memory_budget_bytes": 256 * 1024 * 1024})
        self.assertTrue(dense["accuracy_vs_bfs"] and disconnected["accuracy_vs_bfs"])
        self.assertEqual(disconnected["sentinels"]["sentinel_after_remove"], False)


if __name__ == "__main__":
    unittest.main()
