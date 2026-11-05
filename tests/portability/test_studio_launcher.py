import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_studio.py"


class StudioLauncherTests(unittest.TestCase):
    def test_launcher_help_works_outside_checkout(self):
        with tempfile.TemporaryDirectory(prefix="aether studio ") as folder:
            result = subprocess.run([sys.executable, str(SCRIPT), "--help"], cwd=folder, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--api-only", result.stdout)
        self.assertIn("--seed-fixture", result.stdout)

    def test_invalid_ports_are_rejected_before_starting(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--api-only", "--api-port", "80"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("1024..65535", result.stderr)

    def test_real_child_is_stopped_and_reaped(self):
        spec = importlib.util.spec_from_file_location("studio_launcher", SCRIPT)
        assert spec is not None and spec.loader is not None
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        try:
            launcher.stop_child(child)
            self.assertIsNotNone(child.poll())
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
        self.assertEqual(launcher.ROOT, ROOT)


if __name__ == "__main__":
    unittest.main()
