#!/usr/bin/env python3
"""End-to-end Rust relational index benchmark for the semantic SNAP projection."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from aether_knowledge_rust import RustKnowledgeIndex
from aether_snap_semantic import load_email_eu_core


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", default="data/phase5_snap/email-eu-core/email-Eu-core.txt.gz")
    parser.add_argument("--out", default="results/phase7new/rust_email_eu_core")
    parser.add_argument("--queries", type=int, default=1000)
    args = parser.parse_args()
    manifest = json.loads(Path("phase5_datasets.json").read_text())
    entry = next(item for item in manifest["datasets"] if item["id"] == "email-eu-core")
    store, load = load_email_eu_core(args.archive, expected_sha256=entry["sha256"], source_url=entry["snap_page"])
    facts = store.query(predicate="sent_email_to")
    pairs = [(fact.subject, fact.object) for fact in facts[: args.queries // 2]]
    pairs += [(facts[index].subject, f"snap:email-eu-core:node:{2000 + index}") for index in range(min(args.queries - len(pairs), len(facts)))]
    python_start = time.perf_counter_ns()
    python_answers = [bool(store.query(subject=source, predicate="sent_email_to", object=target)) for source, target in pairs]
    python_ns = time.perf_counter_ns() - python_start
    with RustKnowledgeIndex(store, "sent_email_to") as index:
        rust_start = time.perf_counter_ns()
        rust_answers = [index.has_fact(source, target) for source, target in pairs]
        rust_ns = time.perf_counter_ns() - rust_start
        if rust_answers != python_answers:
            raise AssertionError("Rust and KnowledgeStore answers differ")
        build = index.build
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    row = {"dataset": load.dataset_id, "facts": load.unique_facts, "entities": load.node_count, "queries": len(pairs), "python_query_ms": python_ns / 1e6, "rust_query_ms": rust_ns / 1e6, "conversion_ms": build.conversion_ns / 1e6, "rust_build_ms": build.rust_build_ns / 1e6, "exact_answers_match": True}
    with (out / "runs.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)
    summary = {"dataset": load.as_dict(), "measurement": row, "provenance_preserved_in_python": True, "rust_backend": "existing ABI v2 RustDynamicGraph", "limitations": ["Rust stores only dense relation edges; fact provenance and properties remain in Python.", "This benchmark measures direct relation lookup, not symbolic rule inference in Rust.", "Single local dataset and query batch; it is an end-to-end integration check, not a universal speed claim."]}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
