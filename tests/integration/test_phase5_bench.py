import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from aether.native.bindings import compile_native
from benchmarks.phase5.phase5_bench import load_snap_graph, make_actions, run_worker, _independent_validation


class Phase5BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="aether-phase5-fixture-")
        cls.root = Path(cls.tmp.name)
        cls.dataset = cls.root / "fixture.txt"
        cls.dataset.write_text(
            "# tiny correctness fixture; not a benchmark dataset\n"
            "0 1\n1 2\n2 3\n3 4\n5 6\n",
            encoding="utf-8",
        )
        cls.entry = {
            "id": "fixture",
            "nodes": 8,
            "edges": 5,
            "directed": True,
            "snap_page": "fixture-only",
            "download_url": "fixture-only",
        }
        cls.library = None
        if shutil.which("rustc"):
            suffix = ".dll" if __import__("sys").platform == "win32" else ".dylib" if __import__("sys").platform == "darwin" else ".so"
            filename = "aether_native" + suffix if suffix == ".dll" else "libaether_native" + suffix
            build_dir = Path(__file__).resolve().parents[2] / "build" / "test-phase5"
            cls.library = str(compile_native(build_dir / filename))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_parser_records_duplicates_loops_and_keeps_directed_ids(self):
        sample = self.root / "parser.txt"
        sample.write_text("# header\n0 1\n0 1\n1 1\n2 0\n", encoding="utf-8")
        entry = {"nodes": 4, "edges": 3, "directed": True}
        n, edges, stats = load_snap_graph(sample, entry)
        self.assertEqual(n, 4)
        self.assertEqual(edges, [(0, 1), (1, 1), (2, 0)])
        self.assertEqual(stats["raw_edge_records"], 4)
        self.assertEqual(stats["duplicate_records_removed"], 1)
        self.assertEqual(stats["self_loop_records"], 1)
        self.assertEqual(stats["normalized_directed_edges"], 3)
        self.assertEqual(stats["directedness_transform"], "nenhuma; as arestas dirigidas originais foram mantidas")

    def test_undirected_input_is_expanded_in_both_directions(self):
        sample = self.root / "undirected.txt"
        sample.write_text("0 1\n1 2\n", encoding="utf-8")
        n, edges, stats = load_snap_graph(sample, {"nodes": 3, "directed": False})
        self.assertEqual(n, 3)
        self.assertEqual(edges, [(0, 1), (1, 0), (1, 2), (2, 1)])
        self.assertIn("dois sentidos", stats["directedness_transform"])

    def test_static_and_dynamic_streams_are_reproducible_for_30_seeds(self):
        _, edges, _ = load_snap_graph(self.dataset, self.entry)
        for seed in range(30):
            for mode in ("static", "dynamic"):
                actions = make_actions(8, edges, mode, seed, 20, 1, 2)
                repeated = make_actions(8, edges, mode, seed, 20, 1, 2)
                self.assertEqual(actions, repeated)
                answers, _, _ = _independent_validation(self.dataset, self.entry, mode, actions)
                self.assertTrue(any(answers))
                self.assertTrue(not all(answers))

    def _worker_cfg(self, method, mode):
        return {
            "dataset_id": "fixture",
            "dataset_path": str(self.dataset),
            "dataset_sha256": hashlib.sha256(self.dataset.read_bytes()).hexdigest(),
            "entry": self.entry,
            "mode": mode,
            "seed": 57003,
            "repeat": 0,
            "queries": 12,
            "batch_size": 3,
            "rounds": 1,
            "updates_per_round": 2,
            "memory_budget_bytes": 256 * 1024 * 1024,
            "library": self.library,
            "method": method,
        }

    def test_static_methods_share_stream_and_validate_new_capabilities(self):
        methods = ["python_sets", "python_compact", "python_csr", "feature_policy", "online_controller"]
        if self.library:
            methods += ["rust_ffi_single", "rust_ffi_batch"]
        rows = [run_worker(self._worker_cfg(method, "static")) for method in methods]
        self.assertEqual(len({row["workload_sha256"] for row in rows}), 1)
        self.assertEqual(len({row["answer_sha256"] for row in rows}), 1)
        for row in rows:
            self.assertTrue(row["accuracy_vs_independent_bfs"])
            self.assertTrue(row["shortest_path_matches_oracle"])
            self.assertTrue(row["neighborhood_matches_oracle"])
            self.assertGreater(row["positive_answers"], 0)
            self.assertGreater(row["negative_answers"], 0)

    def test_dynamic_methods_validate_insertions_removals_and_batch_calls(self):
        methods = ["python_sets", "python_compact", "feature_policy", "online_controller"]
        if self.library:
            methods += ["rust_ffi_single", "rust_ffi_batch"]
        rows = [run_worker(self._worker_cfg(method, "dynamic")) for method in methods]
        self.assertEqual(len({row["workload_sha256"] for row in rows}), 1)
        self.assertEqual(len({row["answer_sha256"] for row in rows}), 1)
        for row in rows:
            self.assertEqual(row["updates"], 4)
            self.assertTrue(row["accuracy_vs_independent_bfs"])
            self.assertTrue(row["shortest_path_matches_oracle"])
            self.assertTrue(row["neighborhood_matches_oracle"])
        batch = next((row for row in rows if row["method"] == "rust_ffi_batch"), None)
        if batch:
            self.assertGreater(batch["batch_calls"], 0)


if __name__ == "__main__":
    unittest.main()
