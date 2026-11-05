#!/usr/bin/env python3
"""Measure adaptive reasoning on the audited email-Eu-core projection."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from aether_inference import Pattern, Rule
from aether_backward import BackwardLimits
from aether_inference import InferenceLimits
from aether_reasoning_controller import AdaptiveReasoningController
from aether_snap_semantic import load_email_eu_core
from aether_knowledge import KnowledgeStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", default="data/phase5_snap/email-eu-core/email-Eu-core.txt.gz")
    parser.add_argument("--out", default="results/phase7new/controller_email_eu_core")
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--max-facts", type=int, default=1000)
    args = parser.parse_args()
    manifest = json.loads(Path("phase5_datasets.json").read_text())
    entry = next(item for item in manifest["datasets"] if item["id"] == "email-eu-core")
    full_store, load = load_email_eu_core(args.archive, expected_sha256=entry["sha256"], source_url=entry["snap_page"])
    selected = full_store.query(predicate="sent_email_to")[: args.max_facts]
    store = KnowledgeStore()
    entity_ids = sorted({fact.subject for fact in selected} | {fact.object for fact in selected})
    for entity_id in entity_ids:
        store.add_entity(entity_id, {"dataset_id": load.dataset_id})
    for fact in selected:
        store.add_fact(fact.subject, fact.predicate, fact.object, provenance=fact.provenance, properties=fact.property_map())
    rule = Rule("email-projection", (Pattern("?x", "sent_email_to", "?y"),), Pattern("?x", "emailed", "?y"))
    facts = store.query(predicate="sent_email_to")
    rows = []
    for seed in range(args.seeds):
        fact = facts[seed % len(facts)]
        if seed % 3 == 0:
            goal = (fact.subject, "emailed", fact.object)
        elif seed % 3 == 1:
            goal = (fact.subject, "emailed", "?recipient")
        else:
            goal = (fact.subject, "emailed", f"snap:email-eu-core:node:{1005 + seed}")
        controller = AdaptiveReasoningController(
            store,
            [rule],
            backward_limits=BackwardLimits(max_operations=50000),
            forward_limits=InferenceLimits(max_operations=100000, max_conclusions=30000),
        )
        started = time.perf_counter_ns()
        result = controller.prove(goal)
        total_ns = time.perf_counter_ns() - started
        rows.append({
            "seed": seed,
            "split": "calibration" if seed < args.seeds // 2 else "holdout",
            "goal_subject": goal[0], "goal_predicate": goal[1], "goal_object": goal[2],
            "strategy": result.strategy, "proven": int(result.proven), "complete": int(result.complete),
            "operations": result.operations, "decision_ns": result.decision_ns,
            "execution_ns": result.execution_ns, "total_ns": total_ns,
            "stop_reason": result.stop_reason or "", "rationale": result.rationale,
        })
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    with (out / "runs.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    summary = {
        "dataset": load.as_dict(), "measured_fact_sample": len(selected), "full_projection_stats": full_store.stats(), "seeds": args.seeds, "exact_projection": True,
        "rows": len(rows),
        "strategy_counts": {name: sum(row["strategy"] == name for row in rows) for name in ("backward", "hybrid", "forward")},
        "holdout": {"n": sum(row["split"] == "holdout" for row in rows),
                     "median_total_ms": statistics.median(row["total_ns"] for row in rows if row["split"] == "holdout") / 1e6,
                     "median_decision_us": statistics.median(row["decision_ns"] for row in rows if row["split"] == "holdout") / 1e3,
                     "all_complete": all(row["complete"] for row in rows if row["split"] == "holdout")},
        "limitations": ["This controller benchmark uses one audited SNAP projection and one one-step rule.", "Decision cost excludes dataset loading but includes feature extraction and strategy selection.", "The controller does not claim semantic understanding beyond the documented edge-to-fact mapping."],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
