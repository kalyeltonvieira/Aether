import unittest
from unittest.mock import patch

import aether_metrics


class PlatformMetricsTests(unittest.TestCase):
    def test_available_process_and_system_metrics_are_positive(self):
        for metric in (
            aether_metrics.current_rss_bytes(),
            aether_metrics.peak_rss_bytes(),
            aether_metrics.total_physical_memory_bytes(),
        ):
            self.assertTrue(metric is None or (isinstance(metric, int) and metric > 0))

    def test_windows_metrics_use_windows_api_results_without_resource(self):
        with patch.object(aether_metrics.sys, "platform", "win32"), patch.object(
            aether_metrics, "_windows_memory_counters", return_value=(4096, 8192)
        ):
            self.assertEqual(aether_metrics.current_rss_bytes(), 4096)
            self.assertEqual(aether_metrics.peak_rss_bytes(), 8192)

    def test_windows_metric_api_failure_is_reported_as_unavailable(self):
        with patch.object(aether_metrics.sys, "platform", "win32"), patch.object(
            aether_metrics, "_windows_memory_counters", return_value=None
        ):
            self.assertIsNone(aether_metrics.current_rss_bytes())
            self.assertIsNone(aether_metrics.peak_rss_bytes())


if __name__ == "__main__":
    unittest.main()
