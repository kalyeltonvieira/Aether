"""Proof-aware dependency tracking and localized invalidation."""
from __future__ import annotations

from dataclasses import dataclass, replace

from aether.reasoning.inference import DerivationProof, DerivedFact, InferenceResult, _support_identity
from aether.core.knowledge.store import FactIdentity, fact_key_identity

DerivedKey = tuple[str, str, object]
SupportToken = tuple


@dataclass(frozen=True)
class InvalidationStats:
    requested_supports: int
    conclusions_visited: int
    conclusions_invalidated: int
    remaining_conclusions: int
    proofs_invalidated: int = 0
    conclusions_preserved_by_alternative: int = 0


class DependencyTracker:
    """Maintain reverse links per proof support, not just per conclusion key."""

    def __init__(self, result: InferenceResult):
        if not isinstance(result, InferenceResult):
            raise TypeError("result must be an InferenceResult")
        self._facts: dict[FactIdentity, DerivedFact] = {
            fact.identity: fact for fact in result.conclusions
        }
        self._dependents: dict[SupportToken, set[FactIdentity]] = {}
        self._rebuild_reverse_index()
        self.invalidated_total = 0
        self.proofs_invalidated_total = 0
        self.preserved_total = 0
        self.visited_total = 0

    @staticmethod
    def _token(support: int | tuple[str, str, object]) -> SupportToken:
        return _support_identity(support)

    def _rebuild_reverse_index(self) -> None:
        self._dependents = {}
        for identity, fact in self._facts.items():
            for proof in fact.proofs:
                for support in proof.supports:
                    self._dependents.setdefault(self._token(support), set()).add(identity)

    @property
    def active(self) -> tuple[DerivedFact, ...]:
        return tuple(self._facts.values())

    @property
    def active_proofs(self) -> tuple[tuple[FactIdentity, DerivationProof], ...]:
        return tuple(
            (identity, proof)
            for identity, fact in self._facts.items()
            for proof in fact.proofs
        )

    def invalidate(
        self,
        support_ids: set[int] | frozenset[int],
        support_keys: set[DerivedKey] | frozenset[DerivedKey] = frozenset(),
    ) -> InvalidationStats:
        if not isinstance(support_ids, (set, frozenset)) or not isinstance(support_keys, (set, frozenset)):
            raise TypeError("support_ids and support_keys must be sets")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in support_ids):
            raise ValueError("support IDs must be positive integers")
        if any(not isinstance(key, tuple) or len(key) != 3 for key in support_keys):
            raise TypeError("support keys must be 3-tuples")

        queue: list[SupportToken] = [self._token(value) for value in support_ids]
        requested_derived = {fact_key_identity(key) for key in support_keys}
        invalidated = 0
        proofs_invalidated = 0
        preserved = 0
        visited: set[SupportToken] = set()

        # A requested derived conclusion is itself withdrawn, then its dependents
        # are reconsidered exactly like dependents of an explicitly removed fact.
        for identity in requested_derived:
            fact = self._facts.pop(identity, None)
            if fact is not None:
                invalidated += 1
                proofs_invalidated += len(fact.proofs)
                queue.append(("derived", identity))

        while queue:
            token = queue.pop(0)
            if token in visited:
                continue
            visited.add(token)
            for dependent_identity in tuple(self._dependents.get(token, ())):
                fact = self._facts.get(dependent_identity)
                if fact is None:
                    continue
                retained = tuple(
                    proof for proof in fact.proofs
                    if all(self._token(support) != token for support in proof.supports)
                )
                if len(retained) == len(fact.proofs):
                    continue
                proofs_invalidated += len(fact.proofs) - len(retained)
                if retained:
                    self._facts[dependent_identity] = fact.with_proofs(retained)
                    preserved += 1
                    continue
                self._facts.pop(dependent_identity, None)
                invalidated += 1
                queue.append(("derived", dependent_identity))

        self.invalidated_total += invalidated
        self.proofs_invalidated_total += proofs_invalidated
        self.preserved_total += preserved
        self.visited_total += len(visited)
        return InvalidationStats(
            requested_supports=len(support_ids) + len(support_keys),
            conclusions_visited=len(visited),
            conclusions_invalidated=invalidated,
            remaining_conclusions=len(self._facts),
            proofs_invalidated=proofs_invalidated,
            conclusions_preserved_by_alternative=preserved,
        )

    def add(self, conclusions: tuple[DerivedFact, ...] | list[DerivedFact]) -> None:
        for fact in conclusions:
            if not isinstance(fact, DerivedFact):
                raise TypeError("conclusions must contain DerivedFact values")
            existing = self._facts.get(fact.identity)
            if existing is None:
                self._facts[fact.identity] = fact
                continue
            proofs = list(existing.proofs)
            known = {proof.identity for proof in proofs}
            proofs.extend(proof for proof in fact.proofs if proof.identity not in known)
            self._facts[fact.identity] = existing.with_proofs(proofs)
        self._rebuild_reverse_index()

    def stats(self) -> dict[str, int]:
        return {
            "active_conclusions": len(self._facts),
            "active_proofs": sum(len(fact.proofs) for fact in self._facts.values()),
            "dependency_keys": len(self._dependents),
            "invalidated_total": self.invalidated_total,
            "proofs_invalidated_total": self.proofs_invalidated_total,
            "preserved_by_alternative_total": self.preserved_total,
            "visited_total": self.visited_total,
        }
