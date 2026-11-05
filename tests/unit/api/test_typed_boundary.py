import unittest

try:
    from pydantic import ValidationError
    from aether.interfaces.api.schemas.models import ConfigUpdate, EventProcess, FactCreate, FactPatch, QueryCreate, MemoryBudgetUpdate
except ImportError:
    FactCreate = None


@unittest.skipIf(FactCreate is None, 'optional API dependencies unavailable')
class TypedBoundaryTests(unittest.TestCase):
    def test_browser_integral_float_uses_explicit_type_tag(self):
        base = {'subject': 's', 'predicate': 'p', 'object': 1}
        integer = FactCreate.model_validate({**base, 'object_type': 'int'})
        floating = FactCreate.model_validate({**base, 'object_type': 'float'})
        self.assertIs(type(integer.object), int)
        self.assertIs(type(floating.object), float)
        patch = FactPatch.model_validate({'object': 1, 'object_type': 'float'})
        self.assertIs(type(patch.object), float)
        query = QueryCreate.model_validate({**base, 'object_type': 'float', 'strategy': 'forward'})
        self.assertIs(type(query.object), float)

    def test_no_boolean_number_or_scalar_coercions(self):
        with self.assertRaises(ValidationError):
            FactCreate.model_validate({'subject': 's', 'predicate': 'p', 'object': True, 'object_type': 'int'})
        with self.assertRaises(ValidationError):
            MemoryBudgetUpdate.model_validate({'max_bytes': True})
        with self.assertRaises(ValidationError):
            FactCreate.model_validate({'subject': 's', 'predicate': 'p', 'object': '1', 'object_type': 'float'})

    def test_query_strategy_and_event_limit_are_optional_at_the_boundary(self):
        query = QueryCreate.model_validate({'subject': 's', 'predicate': 'p', 'object': 1})
        self.assertIsNone(query.strategy)
        process = EventProcess.model_validate({})
        self.assertIsNone(process.limit)

    def test_adaptive_cannot_be_configured_as_default_strategy(self):
        with self.assertRaises(ValidationError):
            ConfigUpdate.model_validate({'default_strategy': 'adaptive'})


if __name__ == '__main__':
    unittest.main()
