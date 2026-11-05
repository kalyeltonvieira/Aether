import unittest

from phase5_synthetic_bench import SCENARIOS, generate_edges, make_actions, oracle


class SyntheticBenchmarkGeneratorTests(unittest.TestCase):
    def test_graphs_change_across_seeds_but_repeat_exactly(self):
        for scenario in ("sparse-static-1k", "dense-disconnected-1k", "disconnected-dynamic-10k"):
            first = generate_edges(scenario, 7)
            self.assertEqual(first, generate_edges(scenario, 7))
            self.assertNotEqual(first[1], generate_edges(scenario, 8)[1])
            self.assertEqual(len(first[1]), SCENARIOS[scenario]["m"])

    def test_static_and_dynamic_streams_have_exact_positive_and_negative_pairs(self):
        for scenario, seed in (("sparse-static-1k", 3), ("dense-disconnected-1k", 4),
                               ("disconnected-dynamic-10k", 5)):
            n, edges = generate_edges(scenario, seed)
            actions = make_actions(n, edges, scenario, seed, 100)
            answers = oracle(n, edges, actions)
            self.assertEqual(len(answers), 100)
            self.assertEqual(sum(answers), 100 // 2 - (100 // 3 % 2 if SCENARIOS[scenario]["dynamic"] else 0))
            self.assertEqual(sum(action["kind"] == "add" for action in actions), int(SCENARIOS[scenario]["dynamic"]))
            self.assertEqual(sum(action["kind"] == "remove" for action in actions), int(SCENARIOS[scenario]["dynamic"]))

    def test_disconnected_scenarios_keep_updates_inside_components(self):
        for scenario, seed in (("dense-disconnected-1k", 11), ("disconnected-dynamic-10k", 12)):
            n, edges = generate_edges(scenario, seed)
            actions = make_actions(n, edges, scenario, seed, 100)
            updates = [pair for action in actions if action["kind"] in ("add", "remove") for pair in action["edges"]]
            for source, target in updates:
                self.assertEqual(source * 10 // n, target * 10 // n)


if __name__ == "__main__":
    unittest.main()
