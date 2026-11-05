"""Hybrid query strategy combining backward proof and bounded forward fallback."""
from __future__ import annotations

from dataclasses import dataclass

from aether_backward import BackwardInference, BackwardLimits, Proof
from aether_inference import InferenceEngine, InferenceLimits, Rule
from aether_knowledge import KnowledgeStore, Scalar


@dataclass(frozen=True)
class HybridResult:
    goal: tuple[str, str, Scalar]
    proven: bool
    complete: bool
    strategy: str
    operations: int
    stop_reason: str | None = None


class HybridInference:
    def __init__(self, store: KnowledgeStore, rules: tuple[Rule, ...] | list[Rule] = ()) -> None:
        self.store = store
        self.rules = tuple(rules)

    def prove(
        self,
        goal: tuple[str, str, Scalar],
        *,
        backward_limits: BackwardLimits | None = None,
        forward_limits: InferenceLimits | None = None,
    ) -> HybridResult:
        backward = BackwardInference(self.store, self.rules).prove(goal, backward_limits)
        if backward.proven:
            return HybridResult(goal, True, backward.complete, "backward", backward.operations)
        if not backward.complete and backward.stop_reason in {"max_depth", "max_operations"}:
            return HybridResult(goal, False, False, "backward_limited", backward.operations, backward.stop_reason)
        forward = InferenceEngine(self.store, self.rules).infer(forward_limits)
        found = forward.by_key(goal) is not None
        return HybridResult(
            goal,
            found,
            forward.complete,
            "forward_fallback",
            backward.operations + forward.operations,
            forward.stop_reason,
        )
