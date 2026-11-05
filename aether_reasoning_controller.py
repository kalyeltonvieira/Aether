"""Online strategy controller for bounded relational reasoning."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from aether_backward import BackwardInference, BackwardLimits
from aether_hybrid import HybridInference
from aether_inference import InferenceEngine, InferenceLimits
from aether_knowledge import KnowledgeStore, Scalar


@dataclass(frozen=True)
class ControllerResult:
    goal: tuple[str, str, Scalar]
    strategy: str
    proven: bool
    complete: bool
    operations: int
    decision_ns: int
    execution_ns: int
    stop_reason: str | None
    rationale: str


class AdaptiveReasoningController:
    """Select a strategy from query shape and observed online costs.

    The controller never changes logical results. For open goals it uses forward
    chaining because the current proof API accepts concrete goals. For ground
    goals it starts with the low-cardinality query-driven route, then uses the
    exponentially smoothed observed cost to choose among eligible strategies.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        rules=(),
        *,
        sparse_predicate_limit: int = 128,
        backward_limits: BackwardLimits | None = None,
        forward_limits: InferenceLimits | None = None,
    ) -> None:
        self.store = store
        self.rules = tuple(rules)
        self.sparse_predicate_limit = sparse_predicate_limit
        self.backward_limits = backward_limits
        self.forward_limits = forward_limits
        self._ema_ns: dict[str, float] = {}
        self._observations: dict[str, int] = {}

    @property
    def observations(self) -> dict[str, int]:
        return dict(self._observations)

    @property
    def estimated_cost_ns(self) -> dict[str, float]:
        return dict(self._ema_ns)

    @staticmethod
    def _is_open(goal: tuple[str, str, Scalar]) -> bool:
        return any(isinstance(value, str) and value.startswith("?") for value in (goal[0], goal[2]))

    def choose(self, goal: tuple[str, str, Scalar]) -> tuple[str, str]:
        if self._is_open(goal):
            return "forward", "open_goal_requires_closure"
        predicate_count = len(self.store.query(predicate=goal[1]))
        eligible = ("backward", "hybrid", "forward")
        if predicate_count <= self.sparse_predicate_limit and "backward" not in self._ema_ns:
            return "backward", f"sparse_predicate:{predicate_count}"
        measured = [(self._ema_ns[name], name) for name in eligible if name in self._ema_ns]
        if measured:
            _, strategy = min(measured)
            return strategy, f"lowest_ema_ns:{self._ema_ns[strategy]:.0f}"
        return "hybrid", f"dense_predicate:{predicate_count}"

    def _run(self, strategy: str, goal: tuple[str, str, Scalar]) -> tuple[bool, bool, int, str | None]:
        if strategy == "backward":
            result = BackwardInference(self.store, self.rules).prove(goal, self.backward_limits)
            return result.proven, result.complete, result.operations, result.stop_reason
        if strategy == "hybrid":
            result = HybridInference(self.store, self.rules).prove(
                goal, backward_limits=self.backward_limits, forward_limits=self.forward_limits
            )
            return result.proven, result.complete, result.operations, result.stop_reason
        if strategy == "forward":
            result = InferenceEngine(self.store, self.rules).infer(self.forward_limits)
            def matches(key):
                return (
                    key[1] == goal[1]
                    and (isinstance(goal[0], str) and goal[0].startswith("?") or key[0] == goal[0])
                    and (isinstance(goal[2], str) and goal[2].startswith("?") or key[2] == goal[2])
                )
            explicit = self.store.query(predicate=goal[1])
            proven = any(matches((fact.subject, fact.predicate, fact.object)) for fact in explicit)
            proven = proven or any(matches(fact.key) for fact in result.conclusions)
            return proven, result.complete, result.operations, result.stop_reason
        raise ValueError(f"unknown reasoning strategy: {strategy}")

    def prove(self, goal: tuple[str, str, Scalar]) -> ControllerResult:
        decision_start = time.perf_counter_ns()
        strategy, rationale = self.choose(goal)
        decision_ns = time.perf_counter_ns() - decision_start
        execution_start = time.perf_counter_ns()
        proven, complete, operations, stop_reason = self._run(strategy, goal)
        execution_ns = time.perf_counter_ns() - execution_start
        previous = self._ema_ns.get(strategy)
        self._ema_ns[strategy] = float(execution_ns if previous is None else previous * 0.8 + execution_ns * 0.2)
        self._observations[strategy] = self._observations.get(strategy, 0) + 1
        return ControllerResult(goal, strategy, proven, complete, operations, decision_ns, execution_ns, stop_reason, rationale)
