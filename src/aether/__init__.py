"""AETHER: experimental dynamic graphs and structured relational reasoning."""
from aether.core.knowledge.store import (
    ConflictResolution,
    Entity,
    EvidenceRemoval,
    Fact,
    FactEvidence,
    KnowledgeChange,
    KnowledgeStore,
    Provenance,
    Scalar,
)
from aether.core.knowledge.persistence import load_store, save_store
from aether.graph.dynamic import DynamicGraph
from aether.reasoning.reasoner import KnowledgeReasoner

__all__ = [
    "DynamicGraph",
    "ConflictResolution",
    "Entity",
    "Fact",
    "FactEvidence",
    "EvidenceRemoval",
    "KnowledgeChange",
    "KnowledgeReasoner",
    "KnowledgeStore",
    "Provenance",
    "Scalar",
    "load_store",
    "save_store",
]
__version__ = "0.1.0"
