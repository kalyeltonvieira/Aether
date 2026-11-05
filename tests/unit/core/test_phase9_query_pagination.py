import unittest

from aether.core.knowledge.store import KnowledgeStore
from aether.reasoning.inference import InferenceEngine, Pattern


class QueryPaginationTests(unittest.TestCase):
    def setUp(self):
        self.store = KnowledgeStore()
        for entity in ("a", "b", "c", "d", "e"):
            self.store.add_entity(entity)
        for source, target in (("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")):
            self.store.add_fact(source, "edge", target)
        self.engine = InferenceEngine(self.store)
        self.pattern = Pattern("?source", "edge", "?target")

    def test_pages_cover_all_solutions_without_overlap(self):
        first = self.engine.query(self.pattern, max_results=2)
        self.assertEqual(len(first.solutions), 2)
        self.assertFalse(first.complete)
        self.assertEqual(first.stop_reason, "max_results")
        self.assertEqual(first.next_offset, 2)

        second = self.engine.query(self.pattern, max_results=2, offset=first.next_offset)
        self.assertEqual(len(second.solutions), 2)
        self.assertTrue(second.complete)
        self.assertIsNone(second.next_offset)
        self.assertEqual(second.offset, 2)

        first_bindings = [solution.bindings for solution in first.solutions]
        second_bindings = [solution.bindings for solution in second.solutions]
        self.assertEqual(len(set(first_bindings + second_bindings)), 4)
        self.assertEqual(first_bindings + second_bindings, [
            (("?source", "a"), ("?target", "b")),
            (("?source", "b"), ("?target", "c")),
            (("?source", "c"), ("?target", "d")),
            (("?source", "d"), ("?target", "e")),
        ])

    def test_offset_after_end_is_empty_and_complete(self):
        page = self.engine.query(self.pattern, max_results=2, offset=20)
        self.assertEqual(page.solutions, ())
        self.assertTrue(page.complete)
        self.assertIsNone(page.next_offset)

    def test_offset_validation(self):
        for invalid in (-1, True, 1.5):
            with self.subTest(offset=invalid):
                with self.assertRaises(ValueError):
                    self.engine.query(self.pattern, offset=invalid)


if __name__ == "__main__":
    unittest.main()
