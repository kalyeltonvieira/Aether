"""Auditable semantic projection of a SNAP edge list into KnowledgeStore."""
from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from aether.core.knowledge.store import KnowledgeStore, Provenance


@dataclass(frozen=True)
class SemanticLoad:
    dataset_id: str
    archive_sha256: str
    source_url: str
    edge_records: int
    unique_facts: int
    duplicate_records: int
    comment_lines: int
    malformed_lines: tuple[int, ...]
    node_count: int
    predicate: str

    def as_dict(self) -> dict:
        value = self.__dict__.copy()
        value["malformed_lines"] = list(self.malformed_lines)
        return value


def archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _entity_id(dataset_id: str, node: int) -> str:
    return f"snap:{dataset_id}:node:{node}"


def load_email_eu_core(
    archive: str | Path,
    *,
    dataset_id: str = "email-eu-core",
    source_url: str = "https://snap.stanford.edu/data/email-Eu-core.txt.gz",
    expected_sha256: str | None = None,
    predicate: str = "sent_email_to",
) -> tuple[KnowledgeStore, SemanticLoad]:
    """Load directed email edges with stable IDs and source-line provenance.

    The SNAP page defines a directed email interaction. The projection creates
    one entity per node id and one fact per unique directed pair. No inference,
    direction reversal or unstated natural-language meaning is added.
    """
    path = Path(archive)
    actual_sha = archive_sha256(path)
    if expected_sha256 and actual_sha.lower() != expected_sha256.lower():
        raise ValueError(f"archive SHA-256 mismatch: expected {expected_sha256}, got {actual_sha}")
    records: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int]] = set()
    node_ids: set[int] = set()
    edge_records = duplicate_records = comment_lines = 0
    malformed: list[int] = []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="strict") as stream:
        for line_number, line in enumerate(stream, 1):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("#", "%", "//")):
                comment_lines += 1
                continue
            fields = stripped.split()
            if len(fields) != 2:
                malformed.append(line_number)
                continue
            try:
                source, target = map(int, fields)
            except ValueError:
                malformed.append(line_number)
                continue
            if source < 0 or target < 0:
                raise ValueError(f"negative node id at line {line_number}")
            edge_records += 1
            node_ids.update((source, target))
            key = (source, target)
            if key in seen:
                duplicate_records += 1
                continue
            seen.add(key)
            records.append((source, target, line_number))
    if malformed:
        raise ValueError(f"malformed non-comment rows at lines {malformed[:10]}")

    store = KnowledgeStore()
    for node in sorted(node_ids):
        store.add_entity(_entity_id(dataset_id, node), {"dataset_id": dataset_id, "snap_node_id": node})
    for source, target, line_number in records:
        store.add_fact(
            _entity_id(dataset_id, source), predicate, _entity_id(dataset_id, target),
            provenance=Provenance(source=source_url, evidence=f"{path.name}:line:{line_number}"),
            properties={"dataset_id": dataset_id, "source_node": source, "target_node": target},
        )
    return store, SemanticLoad(
        dataset_id, actual_sha, source_url, edge_records, len(records), duplicate_records,
        comment_lines, tuple(malformed), len(node_ids), predicate,
    )


def write_semantic_report(load: SemanticLoad, path: str | Path) -> None:
    Path(path).write_text(json.dumps(load.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
