import unittest

from aether.memory.adaptive_controller import EmpiricalAdaptiveController, WorkloadSignature


class AdaptiveControllerTests(unittest.TestCase):
    def signature(self, queries=100):
        return WorkloadSignature(
            nodes=1000,
            edges=4000,
            updates=20,
            queries=queries,
            batch_size=8,
            memory_budget_bytes=256 * 1024 * 1024,
        )

    def test_unknown_workload_uses_safe_fallback(self):
        controller = EmpiricalAdaptiveController(("sets", "rust"), fallback="sets")
        selected, detail = controller.choose(self.signature())
        self.assertEqual(selected, "sets")
        self.assertEqual(detail["reason"], "fallback_unknown_workload")
        self.assertGreaterEqual(detail["decision_ns"], 0)

    def test_measured_history_selects_lower_ema_strategy(self):
        controller = EmpiricalAdaptiveController(("sets", "rust"), fallback="sets")
        signature = self.signature()
        for _ in range(2):
            controller.record(signature, "sets", 20.0)
            controller.record(signature, "rust", 5.0)
        selected, detail = controller.choose(signature)
        self.assertEqual(selected, "rust")
        self.assertEqual(detail["reason"], "lowest_measured_ema")
        self.assertEqual(detail["eligible"], ("rust", "sets"))

    def test_hysteresis_prevents_small_oscillation(self):
        controller = EmpiricalAdaptiveController(("sets", "rust"), fallback="sets", switch_margin=0.10)
        signature = self.signature()
        for _ in range(2):
            controller.record(signature, "sets", 10.0)
            controller.record(signature, "rust", 9.0)
        self.assertEqual(controller.choose(signature)[0], "rust")
        controller.record(signature, "sets", 6.0)
        controller.record(signature, "rust", 9.0)
        selected, detail = controller.choose(signature)
        self.assertEqual(selected, "rust")
        self.assertEqual(detail["reason"], "hysteresis_kept_previous")

    def test_signatures_bucket_nearby_workloads(self):
        first = self.signature(100)
        second = self.signature(101)
        self.assertEqual(first.bucket(), second.bucket())
        self.assertGreater(first.density, 0)
        self.assertGreater(first.update_query_ratio, 0)

    def test_invalid_measurements_and_strategies_are_rejected(self):
        with self.assertRaises(ValueError): EmpiricalAdaptiveController(("sets",), fallback="rust")
        controller = EmpiricalAdaptiveController(("sets",), fallback="sets")
        with self.assertRaises(ValueError): controller.record(self.signature(), "rust", 1.0)
        with self.assertRaises(ValueError): controller.record(self.signature(), "sets", -1.0)


if __name__ == "__main__":
    unittest.main()
