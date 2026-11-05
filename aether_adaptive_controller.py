"""Empirical workload controller for AETHER phase 6.

The controller learns only measured strategy costs grouped by a compact workload
signature. Unknown workloads use a safe fixed fallback. It never claims a
strategy is best without observations and reports its own decision overhead.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkloadSignature:
    nodes: int
    edges: int
    updates: int
    queries: int
    batch_size: int
    memory_budget_bytes: int

    @property
    def density(self) -> float:
        possible = self.nodes * self.nodes
        return self.edges / possible if possible else 0.0

    @property
    def update_query_ratio(self) -> float:
        return self.updates / max(1, self.queries)

    def bucket(self) -> tuple[int, int, int, int, int, int]:
        """Stable coarse key to allow nearby workloads to reuse observations."""
        return (
            max(1, int(round(math.log2(max(1, self.nodes))))),
            max(0, int(round(math.log2(max(1, self.edges + 1))))),
            max(0, int(round(math.log2(max(1, self.updates + 1))))),
            max(0, int(round(math.log2(max(1, self.queries + 1))))),
            max(1, int(round(math.log2(max(1, self.batch_size))))),
            max(0, int(round(math.log2(max(1, self.memory_budget_bytes))))),
        )


class EmpiricalAdaptiveController:
    """Select among measured strategies without making an unknown-workload guess."""

    def __init__(
        self,
        strategies,
        *,
        fallback: str,
        min_observations: int = 2,
        switch_margin: float = 0.05,
        ema_alpha: float = 0.35,
    ):
        self.strategies = tuple(strategies)
        if not self.strategies or fallback not in self.strategies:
            raise ValueError("fallback must be one of the available strategies")
        if not isinstance(min_observations, int) or min_observations < 1:
            raise ValueError("min_observations must be positive")
        if not 0 <= switch_margin < 1:
            raise ValueError("switch_margin must be in [0, 1)")
        if not 0 < ema_alpha <= 1:
            raise ValueError("ema_alpha must be in (0, 1]")
        self.fallback = fallback
        self.min_observations = min_observations
        self.switch_margin = switch_margin
        self.ema_alpha = ema_alpha
        self._history: dict[tuple, dict[str, dict[str, float]]] = {}
        self._current: dict[tuple, str] = {}
        self.decisions = 0
        self.decision_ns = 0
        self.explorations = 0

    def _bucket(self, signature: WorkloadSignature) -> tuple:
        if not isinstance(signature, WorkloadSignature):
            raise TypeError("signature must be a WorkloadSignature")
        return signature.bucket()

    def record(self, signature: WorkloadSignature, strategy: str, total_ms: float) -> None:
        if strategy not in self.strategies:
            raise ValueError(f"unknown strategy: {strategy}")
        if not isinstance(total_ms, (int, float)) or total_ms < 0 or not math.isfinite(total_ms):
            raise ValueError("total_ms must be a finite non-negative number")
        bucket = self._bucket(signature)
        by_strategy = self._history.setdefault(bucket, {})
        state = by_strategy.setdefault(strategy, {"observations": 0.0, "ema_ms": 0.0, "sum_ms": 0.0})
        state["observations"] += 1
        state["sum_ms"] += float(total_ms)
        if state["observations"] == 1:
            state["ema_ms"] = float(total_ms)
        else:
            state["ema_ms"] = self.ema_alpha * float(total_ms) + (1 - self.ema_alpha) * state["ema_ms"]

    def choose(self, signature: WorkloadSignature) -> tuple[str, dict]:
        started = time.perf_counter_ns()
        bucket = self._bucket(signature)
        by_strategy = self._history.get(bucket, {})
        eligible = {
            strategy: data
            for strategy, data in by_strategy.items()
            if data["observations"] >= self.min_observations
        }
        reason = "fallback_unknown_workload"
        selected = self.fallback
        if eligible:
            best = min(eligible, key=lambda name: (eligible[name]["ema_ms"], name))
            previous = self._current.get(bucket)
            selected = best
            reason = "lowest_measured_ema"
            if previous in eligible and previous != best:
                previous_cost = eligible[previous]["ema_ms"]
                best_cost = eligible[best]["ema_ms"]
                if best_cost >= previous_cost * (1 - self.switch_margin):
                    selected = previous
                    reason = "hysteresis_kept_previous"
            self._current[bucket] = selected
        else:
            self.explorations += 1
        self.decisions += 1
        elapsed = time.perf_counter_ns() - started
        self.decision_ns += elapsed
        return selected, {
            "reason": reason,
            "decision_ns": elapsed,
            "eligible": tuple(sorted(eligible)),
            "bucket": bucket,
        }

    def stats(self) -> dict:
        observations = sum(
            int(data["observations"])
            for by_strategy in self._history.values()
            for data in by_strategy.values()
        )
        return {
            "strategies": self.strategies,
            "fallback": self.fallback,
            "signature_buckets": len(self._history),
            "observations": observations,
            "decisions": self.decisions,
            "explorations": self.explorations,
            "decision_ns_total": self.decision_ns,
            "decision_ns_mean": self.decision_ns / self.decisions if self.decisions else 0.0,
        }

    def history(self) -> dict:
        return {
            str(bucket): {strategy: dict(data) for strategy, data in values.items()}
            for bucket, values in self._history.items()
        }
