"""Compatibility shim for legacy imports; implementation lives in aether.metrics."""
import sys
from aether import metrics as _metrics

sys.modules[__name__] = _metrics
