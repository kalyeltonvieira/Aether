from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aether.metrics import current_rss_bytes, peak_rss_bytes, peak_rss_kib, total_memory_bytes


ROOT = Path(__file__).resolve().parents[2]


class PackagePortabilityTests(unittest.TestCase):
    def test_package_and_legacy_imports_are_single_implementation(self):
        import aether
        from aether.core.knowledge.store import KnowledgeStore
        from aether_knowledge import KnowledgeStore as LegacyKnowledgeStore

        self.assertIs(KnowledgeStore, LegacyKnowledgeStore)
        self.assertIsInstance(aether.KnowledgeStore(), KnowledgeStore)

    def test_memory_metrics_are_nonnegative_or_unavailable(self):
        for value in (current_rss_bytes(), peak_rss_bytes(), peak_rss_kib(), total_memory_bytes()):
            self.assertTrue(value is None or (isinstance(value, int) and value >= 0))

    def test_paths_with_spaces_and_non_ascii_can_be_read_written_and_removed(self):
        with tempfile.TemporaryDirectory(prefix="aether espaço-ä-") as temporary:
            path = Path(temporary) / "dados com espaço-ç.txt"
            path.write_text("AETHER — caminho portátil\n", encoding="utf-8", newline="\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "AETHER — caminho portátil\n")
            nested = path.parent / "sub dir"
            nested.mkdir()
            moved = nested / path.name
            path.replace(moved)
            self.assertTrue(moved.is_file())
            moved.unlink()
            nested.rmdir()

    def test_imports_work_from_directory_outside_checkout(self):
        env = os.environ.copy()
        package_path = str(ROOT / "src")
        benchmark_path = str(ROOT)
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = os.pathsep.join(
            value for value in (package_path, benchmark_path, existing) if value
        )
        with tempfile.TemporaryDirectory(prefix="aether-import-") as outside:
            result = subprocess.run(
                [sys.executable, "-c", "from aether import KnowledgeStore; from benchmarks.phase3.phase3_bench import make_events; assert KnowledgeStore and make_events"],
                cwd=outside,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rust_source_is_packaged_next_to_bindings_resource(self):
        from importlib.resources import files

        resource = files("aether.native").joinpath("rust", "aether_native.rs")
        self.assertTrue(resource.is_file())

    def test_manifest_exists_in_checkout(self):
        from benchmarks._paths import phase5_manifest_path

        self.assertTrue(phase5_manifest_path().is_file())


if __name__ == "__main__":
    unittest.main()
