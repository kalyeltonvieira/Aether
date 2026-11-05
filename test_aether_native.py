import ctypes
import gc
import shutil
import sys
import tempfile
import unittest
import uuid
from array import array
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aether_dynamic import neighbors_within_hops, shortest_path
from aether_native import RustDynamicGraph, compile_native
from phase4_bench import run_worker


class RustDynamicGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("rustc") is None:
            raise unittest.SkipTest("rustc is not installed")
        cls.tmp = tempfile.TemporaryDirectory(prefix="aether-native-test-")
        suffix = ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"
        filename = "aether_native" + suffix if suffix == ".dll" else "libaether_native" + suffix
        build_dir = Path(__file__).resolve().parent / "build" / f"test-native-{uuid.uuid4().hex}"
        cls.library = compile_native(build_dir / filename)
        cls.lib = ctypes.CDLL(str(cls.library))
        cls.lib.aether_graph_abi_version.argtypes = []
        cls.lib.aether_graph_abi_version.restype = ctypes.c_uint32
        cls.lib.aether_graph_add_edges.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_size_t
        ]
        cls.lib.aether_graph_add_edges.restype = ctypes.c_int64
        cls.lib.aether_graph_reachable_many.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        cls.lib.aether_graph_reachable_many.restype = ctypes.c_int64
        cls.lib.aether_graph_add_edge.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32
        ]
        cls.lib.aether_graph_add_edge.restype = ctypes.c_int64

    @classmethod
    def tearDownClass(cls):
        gc.collect()
        if hasattr(cls, "tmp"):
            cls.tmp.cleanup()

    def test_abi_version_platform_and_architecture_checked(self):
        self.assertEqual(self.lib.aether_graph_abi_version(), 2)
        with RustDynamicGraph(2, [], self.library) as graph:
            self.assertEqual(graph.edge_count(), 0)

    def test_initial_graph_positive_negative_and_identity(self):
        with RustDynamicGraph(6, [(0, 1), (1, 2), (2, 5)], self.library) as graph:
            self.assertTrue(graph.reachable(0, 5))
            self.assertFalse(graph.reachable(5, 0))
            self.assertTrue(graph.reachable(3, 3))
            self.assertEqual(graph.edge_count(), 3)
            self.assertGreater(graph.memory_bytes(), 0)
            self.assertEqual(list(graph.neighbors(1)), [2])

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
                           lambda: graph.has_edge(5, 0), lambda: graph.reachable(0, 5),
                           lambda: graph.neighbors(5)):
                with self.assertRaises(IndexError): action()

    def test_batch_updates_queries_and_reusable_output_buffer(self):
        with RustDynamicGraph(7, [(0, 1), (1, 2)], self.library) as graph:
            self.assertEqual(graph.add_edges([(2, 3), (3, 4), (2, 3), (5, 6)]), 3)
            self.assertEqual(graph.edge_count(), 5)
            output = bytearray([99] * 8)
            result = graph.reachable_many([(0, 4), (6, 0), (2, 3), (4, 4)], output)
            self.assertEqual(bytes(result), b"\x01\x00\x01\x01")
            self.assertEqual(output, bytearray([1, 0, 1, 1, 99, 99, 99, 99]))
            result2 = graph.reachable_many([(5, 6), (6, 5)], output)
            self.assertIs(result2.obj, output)
            self.assertEqual(bytes(result2), b"\x01\x00")
            self.assertEqual(graph.remove_edges([(2, 3), (2, 3), (0, 1), (6, 5)]), 2)
            self.assertEqual(graph.edge_count(), 3)
            self.assertEqual(bytes(graph.reachable_many([(0, 4), (2, 3)])), b"\x00\x00")

    def test_thousand_edge_batches_and_two_thousand_pair_query(self):
        with RustDynamicGraph(1001, [], self.library) as graph:
            edges = [(node, node + 1) for node in range(1000)]
            self.assertEqual(graph.add_edges(edges), 1000)
            queries = [(0, node) for node in range(1001)]
            queries.extend((node, 0) for node in range(1, 1001))
            output = bytearray(len(queries))
            result = graph.reachable_many(queries, output)
            self.assertIs(result.obj, output)
            self.assertEqual(bytes(result), b"\x01" * 1001 + b"\x00" * 1000)
            self.assertEqual(graph.remove_edges(edges), 1000)
            self.assertEqual(graph.edge_count(), 0)
            self.assertEqual(
                bytes(graph.reachable_many(queries, output)),
                b"\x01" + b"\x00" * 2000,
            )

    def test_batch_argument_and_output_validation(self):
        with RustDynamicGraph(4, [], self.library) as graph:
            with self.assertRaises(IndexError): graph.add_edges([(0, 1), (4, 2)])
            with self.assertRaises(IndexError): graph.reachable_many([(0, 1), (0, 4)])
            with self.assertRaises(ValueError): graph.reachable_many([(0, 1), (1, 2)], bytearray(1))
            with self.assertRaises(ValueError): graph.reachable_many([(0, 1)], bytes(1))
            with self.assertRaises(ValueError): graph.add_edges([(0, 1, 2)])
            self.assertEqual(graph.edge_count(), 0)

    def test_invalid_native_batches_are_prevalidated_before_mutation_or_output(self):
        with RustDynamicGraph(4, [], self.library) as graph:
            invalid_edges = array("I", [0, 1, 4, 2])
            status = self.lib.aether_graph_add_edges(
                graph._handle,
                ctypes.cast(ctypes.c_void_p(invalid_edges.buffer_info()[0]), ctypes.POINTER(ctypes.c_uint32)),
                len(invalid_edges),
            )
            self.assertEqual(status, -2)
            self.assertEqual(graph.edge_count(), 0)
            invalid_queries = array("I", [0, 1, 4, 2])
            output = (ctypes.c_uint8 * 2)(77, 77)
            status = self.lib.aether_graph_reachable_many(
                graph._handle,
                ctypes.cast(ctypes.c_void_p(invalid_queries.buffer_info()[0]), ctypes.POINTER(ctypes.c_uint32)),
                output,
                2,
            )
            self.assertEqual(status, -2)
            self.assertEqual(list(output), [77, 77])

    def test_native_null_odd_length_and_overflow_errors(self):
        null_u32 = ctypes.POINTER(ctypes.c_uint32)()
        null_u8 = ctypes.POINTER(ctypes.c_uint8)()
        self.assertEqual(self.lib.aether_graph_add_edge(None, 0, 1), -1)
        with RustDynamicGraph(2, [], self.library) as graph:
            self.assertEqual(self.lib.aether_graph_add_edges(graph._handle, null_u32, 1), -2)
            self.assertEqual(self.lib.aether_graph_add_edges(graph._handle, null_u32, 2), -1)
            too_many = sys.maxsize // 2 + 1
            self.assertEqual(
                self.lib.aether_graph_reachable_many(graph._handle, null_u32, null_u8, too_many),
                -5,
            )
            self.assertEqual(graph.edge_count(), 0)

    def test_close_is_idempotent_and_blocks_use_after_close(self):
        graph = RustDynamicGraph(3, [(0, 1)], self.library)
        graph.close(); graph.close()
        self.assertTrue(graph.closed)
        with self.assertRaises(RuntimeError): graph.reachable(0, 1)
        with self.assertRaises(RuntimeError): graph.edge_count()

    def test_native_shortest_path_reads_current_neighbors(self):
        with RustDynamicGraph(6, [(0, 1), (1, 4), (0, 2), (2, 3), (3, 4), (4, 5)], self.library) as graph:
            path = shortest_path(graph, 0, 5)
            self.assertEqual(len(path) - 1, 3)
            self.assertEqual(path[0], 0); self.assertEqual(path[-1], 5)
            self.assertEqual(neighbors_within_hops(graph, 0, 2), {1, 2, 3, 4})
            graph.remove_edges([(1, 4), (3, 4)])
            self.assertIsNone(shortest_path(graph, 0, 5))

    def test_calls_on_one_handle_are_serialized_for_threads(self):
        with RustDynamicGraph(200, ((i, i + 1) for i in range(199)), self.library) as graph:
            pairs = [(i, min(199, i + 30)) for i in range(160)]
            def check(_):
                return bytes(graph.reachable_many(pairs))
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(check, range(8)))
            self.assertTrue(all(result == results[0] for result in results))
            self.assertEqual(results[0], b"\x01" * len(pairs))

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
