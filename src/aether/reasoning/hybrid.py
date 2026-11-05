"""Hybrid query strategy combining backward proof and bounded forward fallback."""
from __future__ import annotations

from dataclasses import dataclass

from aether.reasoning.backward import BackwardInference, BackwardLimits, Proof
from aether.reasoning.inference import InferenceEngine, InferenceLimits, Rule
from aether.core.knowledge.store import KnowledgeStore, Scalar


@dataclass(frozen=True)
class HybridResult:
    goal: tuple[str, str, Scalar]
    proven: bool
    complete: bool
    strategy: str
    operations: int
    stop_reason: str | None = None


class HybridInference:
    def __init__(
        self,
        store: KnowledgeStore,
        rules: tuple[Rule, ...] | list[Rule] = (),
        *,
        join_planner: str = "input",
    ) -> None:
        self.store = store
        self.rules = tuple(rules)
        if join_planner not in {"input", "selective"}:
            raise ValueError("join_planner must be 'input' or 'selective'")
        self.join_planner = join_planner

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
        forward = InferenceEngine(
            self.store, self.rules, join_planner=self.join_planner
        ).infer(forward_limits)
        found = forward.by_key(goal) is not None
        return HybridResult(
            goal,
            found,
            forward.complete,
            "forward_fallback",
            backward.operations + forward.operations,
            forward.stop_reason,
        )
