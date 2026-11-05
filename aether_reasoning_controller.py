"""Adaptive strategy selection for bounded, auditable relational reasoning."""
from __future__ import annotations

import time
from dataclasses import dataclass, replace

from aether_backward import BackwardInference, BackwardLimits
from aether_hybrid import HybridInference
from aether_inference import (
    InferenceEngine,
    InferenceLimits,
    Pattern,
    QuerySolution,
    Rule,
)
from aether_knowledge import KnowledgeStore, Scalar


@dataclass(frozen=True)
class DecisionFeatures:
    predicate_facts: int
    candidate_estimate: int
    direct_fact_candidates: int
    entities: int
    free_variables: int
    unbound_rule_variables: int
    relation_density: float
    expected_depth: int
    historical_queries: int
    index_entries: int
    estimated_index_cost_ns: int
    maintenance_cost_ns: int
    max_operations: int
    max_depth: int


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
    solutions: tuple[QuerySolution, ...] = ()
    features: DecisionFeatures | None = None
    facts_examined: int | None = None
    conclusions_produced: int | None = None

    @property
    def total_ns(self) -> int:
        return self.decision_ns + self.execution_ns


class AdaptiveReasoningController:
    """Choose among backward, hybrid and forward routes using query/session data.

    Ground goals are eligible for all three strategies. Open goals are routed to
    the forward query enumerator, which returns bindings and explanations rather
    than reducing an open query to a boolean. Ground-session choices use a small
    exploration phase so all eligible strategies acquire observations before the
    controller relies on their per-session exponentially smoothed costs.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        rules=(),
        *,
        sparse_predicate_limit: int = 128,
        backward_limits: BackwardLimits | None = None,
        forward_limits: InferenceLimits | None = None,
        max_query_results: int = 1000,
        index_build_ns: int = 0,
        maintenance_cost_ns: int = 0,
    ) -> None:
        if not isinstance(store, KnowledgeStore):
            raise TypeError("store must be a KnowledgeStore")
        if isinstance(sparse_predicate_limit, bool) or not isinstance(sparse_predicate_limit, int) or sparse_predicate_limit < 0:
            raise ValueError("sparse_predicate_limit must be a non-negative integer")
        for name, value in (("max_query_results", max_query_results), ("index_build_ns", index_build_ns), ("maintenance_cost_ns", maintenance_cost_ns)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0 or (name == "max_query_results" and value == 0):
                raise ValueError(f"{name} must be a positive integer" if name == "max_query_results" else f"{name} must be a non-negative integer")
        self.store = store
        self._rules = list(rules)
        if any(not isinstance(rule, Rule) for rule in self._rules):
            raise TypeError("rules must contain Rule values")
        if len({rule.rule_id for rule in self._rules}) != len(self._rules):
            raise ValueError("rule IDs must be unique")
        self.rules_version = 0
        self.sparse_predicate_limit = sparse_predicate_limit
        self.backward_limits = backward_limits or BackwardLimits()
        self.forward_limits = forward_limits or InferenceLimits()
        self.max_query_results = max_query_results
        self.index_build_ns = index_build_ns
        self._maintenance_cost_ns = maintenance_cost_ns
        self._ema_ns: dict[str, float] = {}
        self._observations: dict[str, int] = {}
        self._bucket_ema_ns: dict[tuple, dict[str, float]] = {}
        self._bucket_observations: dict[tuple, dict[str, int]] = {}
        self._bucket_completions: dict[tuple, dict[str, int]] = {}
        self._historical_queries = 0
        self._last_features: DecisionFeatures | None = None

    @property
    def rules(self) -> tuple[Rule, ...]:
        return tuple(self._rules)

    def _rules_changed(self) -> None:
        self.rules_version += 1
        # Cost observations from a different rule set are not comparable.
        self._ema_ns.clear()
        self._observations.clear()
        self._bucket_ema_ns.clear()
        self._bucket_observations.clear()
        self._bucket_completions.clear()

    def add_rule(self, rule: Rule) -> None:
        if not isinstance(rule, Rule):
            raise TypeError("rule must be a Rule")
        if any(existing.rule_id == rule.rule_id for existing in self._rules):
            raise ValueError(f"duplicate rule id: {rule.rule_id}")
        self._rules.append(rule)
        self._rules_changed()

    def remove_rule(self, rule_id: str) -> Rule:
        for index, rule in enumerate(self._rules):
            if rule.rule_id == rule_id:
                removed = self._rules.pop(index)
                self._rules_changed()
                return removed
        raise KeyError(rule_id)

    def replace_rule(self, rule_id: str, rule: Rule) -> Rule:
        if not isinstance(rule, Rule) or rule.rule_id != rule_id:
            raise ValueError("replacement rule must be a Rule with the existing rule_id")
        for index, old in enumerate(self._rules):
            if old.rule_id == rule_id:
                revised = replace(rule, revision=old.revision + 1)
                self._rules[index] = revised
                self._rules_changed()
                return revised
        raise KeyError(rule_id)

    def set_rule_enabled(self, rule_id: str, enabled: bool) -> Rule:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be bool")
        for old in self._rules:
            if old.rule_id == rule_id:
                if old.enabled == enabled:
                    return old
                return self.replace_rule(rule_id, replace(old, enabled=enabled))
        raise KeyError(rule_id)

    @property
    def observations(self) -> dict[str, int]:
        return dict(self._observations)

    @property
    def estimated_cost_ns(self) -> dict[str, float]:
        return dict(self._ema_ns)

    @property
    def historical_queries(self) -> int:
        return self._historical_queries

    def observe_maintenance(self, elapsed_ns: int) -> None:
        if isinstance(elapsed_ns, bool) or not isinstance(elapsed_ns, int) or elapsed_ns < 0:
            raise ValueError("elapsed_ns must be a non-negative integer")
        self._maintenance_cost_ns = int(
            elapsed_ns if self._maintenance_cost_ns == 0
            else self._maintenance_cost_ns * 0.8 + elapsed_ns * 0.2
        )

    @staticmethod
    def _is_open(goal: tuple[str, str, Scalar]) -> bool:
        return not Pattern(*goal).is_ground

    def _features(self, goal: tuple[str, str, Scalar]) -> DecisionFeatures:
        pattern = Pattern(*goal)
        direct_predicate_facts = self.store.query(predicate=goal[1])
        entities = len(self.store.entities())
        matching_rules = [
            rule for rule in self.rules
            if rule.enabled and rule.consequent.predicate == goal[1]
        ]
        relevant_predicates = {goal[1]}
        unbound_variables = set()
        for rule in matching_rules:
            relevant_predicates.update(pattern.predicate for pattern in rule.antecedents)
            antecedent_variables = set().union(*(pattern.variables() for pattern in rule.antecedents))
            unbound_variables.update(antecedent_variables - rule.consequent.variables())
        relevant_fact_count = sum(
            len(self.store.query(predicate=predicate)) for predicate in relevant_predicates
        )
        candidate_kwargs = {"predicate": goal[1]}
        if not (isinstance(goal[0], str) and goal[0].startswith("?")):
            candidate_kwargs["subject"] = goal[0]
        if not (isinstance(goal[2], str) and goal[2].startswith("?")):
            candidate_kwargs["object"] = goal[2]
        direct_candidate_count = len(self.store.query(**candidate_kwargs))
        candidate_estimate = direct_candidate_count
        if pattern.variables():
            candidate_estimate = max(candidate_estimate, len(direct_predicate_facts))
        candidate_estimate = max(candidate_estimate, relevant_fact_count if candidate_estimate == 0 else candidate_estimate)
        density = relevant_fact_count / max(1, entities * entities)
        expected_depth = max((len(rule.antecedents) for rule in matching_rules), default=1)
        stats = self.store.stats()
        index_entries = stats["subject_index_keys"] + stats["predicate_index_keys"] + stats["object_index_keys"]
        index_cost = int((candidate_estimate + 1) * 100)
        limits = self.forward_limits
        return DecisionFeatures(
            relevant_fact_count, candidate_estimate, direct_candidate_count, entities, len(pattern.variables()),
            len(unbound_variables), density, expected_depth, self.historical_queries, index_entries,
            self.index_build_ns + index_cost, self._maintenance_cost_ns,
            limits.max_operations, limits.max_depth,
        )

    def _prior_costs(self, features: DecisionFeatures) -> dict[str, float]:
        predicate_scan = max(1, features.predicate_facts)
        candidates = max(1, features.candidate_estimate)
        depth = max(1, features.expected_depth)
        fact_count = max(1, self.store.stats()["facts"])
        active_rules = max(1, sum(rule.enabled for rule in self.rules))
        index_overhead = features.estimated_index_cost_ns + features.maintenance_cost_ns
        backward = (candidates * depth + features.free_variables + 1) * 1000
        forward = (fact_count * active_rules + predicate_scan) * 1000 + index_overhead
        backward += features.unbound_rule_variables * max(1, predicate_scan) * 10_000
        hybrid = backward + (
            forward if features.unbound_rule_variables else
            min(forward, max(1000, int(forward * predicate_scan / fact_count)))
        )
        if features.predicate_facts <= self.sparse_predicate_limit:
            backward *= 0.8
        else:
            backward *= 1.0 + min(4.0, features.predicate_facts / max(1, self.sparse_predicate_limit))
        return {"backward": float(backward), "hybrid": float(hybrid), "forward": float(forward)}

    @staticmethod
    def _feature_bucket(features: DecisionFeatures) -> tuple:
        density_class = "dense" if features.relation_density >= 0.25 else "sparse"
        return (
            features.free_variables,
            features.unbound_rule_variables,
            int(features.direct_fact_candidates > 0),
            features.expected_depth,
            density_class,
        )

    def choose(self, goal: tuple[str, str, Scalar]) -> tuple[str, str]:
        if not isinstance(goal, tuple) or len(goal) != 3:
            raise TypeError("goal must be (subject, predicate, object)")
        pattern = Pattern(*goal)
        features = self._features(goal)
        self._last_features = features
        if not pattern.is_ground:
            return "forward", f"open_query_bindings:variables={features.free_variables};candidates={features.candidate_estimate}"
        priors = self._prior_costs(features)
        eligible = ("backward", "hybrid", "forward")
        if features.unbound_rule_variables and features.direct_fact_candidates == 0:
            return "forward", (
                f"forward_for_complete_search:unbound_rule_variables={features.unbound_rule_variables};"
                f"direct_candidates=0;history={features.historical_queries}"
            )
        bucket = self._feature_bucket(features)
        bucket_observations = self._bucket_observations.get(bucket, {})
        bucket_ema = self._bucket_ema_ns.get(bucket, {})
        bucket_completions = self._bucket_completions.get(bucket, {})
        unobserved = [name for name in eligible if bucket_observations.get(name, 0) == 0]
        if unobserved:
            chosen = min(unobserved, key=lambda name: (priors[name], eligible.index(name)))
            return chosen, f"session_exploration:{chosen};history={features.historical_queries};prior_ns={priors[chosen]:.0f}"
        scores = {
            name: (
                float("inf")
                if bucket_completions.get(name, 0) == 0
                else 0.7 * bucket_ema[name] + 0.3 * priors[name]
            )
            for name in eligible
        }
        if all(value == float("inf") for value in scores.values()):
            scores = {
                name: 0.7 * bucket_ema.get(name, self._ema_ns.get(name, priors[name])) + 0.3 * priors[name]
                for name in eligible
            }
        chosen = min(eligible, key=lambda name: (scores[name], eligible.index(name)))
        return (
            chosen,
            f"lowest_blended_cost:{scores[chosen]:.0f};history={features.historical_queries};"
            f"candidates={features.candidate_estimate};depth={features.expected_depth};density={features.relation_density:.6g}",
        )

    def _run(
        self, strategy: str, goal: tuple[str, str, Scalar]
    ) -> tuple[bool, bool, int, str | None, tuple[QuerySolution, ...], int | None, int | None]:
        pattern = Pattern(*goal)
        if strategy == "backward":
            if not pattern.is_ground:
                raise ValueError("backward proof requires a ground goal; use forward query for bindings")
            result = BackwardInference(self.store, self.rules).prove(goal, self.backward_limits)
            return result.proven, result.complete, result.operations, result.stop_reason, (), None, None
        if strategy == "hybrid":
            if not pattern.is_ground:
                raise ValueError("hybrid proof requires a ground goal; use forward query for bindings")
            result = HybridInference(self.store, self.rules).prove(
                goal, backward_limits=self.backward_limits, forward_limits=self.forward_limits
            )
            return result.proven, result.complete, result.operations, result.stop_reason, (), None, None
        if strategy == "forward":
            result = InferenceEngine(self.store, self.rules).query(
                pattern, self.forward_limits, max_results=self.max_query_results
            )
            return (
                bool(result.solutions), result.complete, result.operations, result.stop_reason,
                result.solutions, result.facts_examined, result.conclusions_produced,
            )
        raise ValueError(f"unknown reasoning strategy: {strategy}")

    def prove(self, goal: tuple[str, str, Scalar], *, learn: bool = True) -> ControllerResult:
        if not isinstance(learn, bool):
            raise TypeError("learn must be bool")
        if not isinstance(goal, tuple) or len(goal) != 3:
            raise TypeError("goal must be (subject, predicate, object)")
        Pattern(*goal)
        decision_start = time.perf_counter_ns()
        strategy, rationale = self.choose(goal)
        decision_ns = time.perf_counter_ns() - decision_start
        features = self._last_features
        execution_start = time.perf_counter_ns()
        proven, complete, operations, stop_reason, solutions, facts_examined, conclusions_produced = self._run(strategy, goal)
        execution_ns = time.perf_counter_ns() - execution_start
        if learn:
            previous = self._ema_ns.get(strategy)
            self._ema_ns[strategy] = float(execution_ns if previous is None else previous * 0.8 + execution_ns * 0.2)
            self._observations[strategy] = self._observations.get(strategy, 0) + 1
            bucket = self._feature_bucket(features)
            costs = self._bucket_ema_ns.setdefault(bucket, {})
            counts = self._bucket_observations.setdefault(bucket, {})
            completions = self._bucket_completions.setdefault(bucket, {})
            old_cost = costs.get(strategy)
            costs[strategy] = float(execution_ns if old_cost is None else old_cost * 0.8 + execution_ns * 0.2)
            counts[strategy] = counts.get(strategy, 0) + 1
            completions[strategy] = completions.get(strategy, 0) + int(complete)
        self._historical_queries += 1
        return ControllerResult(
            goal, strategy, proven, complete, operations, decision_ns, execution_ns,
            stop_reason, rationale, solutions, features, facts_examined, conclusions_produced,
        )
