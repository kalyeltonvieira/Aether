"""AETHER: experimental dynamic graphs and structured relational reasoning."""
from aether.core.knowledge.store import Entity, Fact, FactEvidence, KnowledgeStore, Provenance, Scalar
from aether.graph.dynamic import DynamicGraph
from aether.reasoning.reasoner import KnowledgeReasoner

__all__ = [
    "DynamicGraph",
    "Entity",
    "Fact",
    "FactEvidence",
    "KnowledgeReasoner",
    "KnowledgeStore",
    "Provenance",
    "Scalar",
]
__version__ = "0.1.0"
