#!/usr/bin/env python3
"""Measure the real API pipeline with temporary test data, not production traffic."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from fastapi.testclient import TestClient
from aether.interfaces.api.app import create_app
from aether.metrics import cpu_model, peak_rss_bytes

TOKEN = "aether-api-benchmark-fixture-token-not-production"


def call(client, method, path, timings, **kwargs) -> Any:
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    response = getattr(client, method)("/api/v1" + path, **kwargs)
    timings.setdefault(path.split('?')[0], []).append({"elapsed_ns": time.perf_counter_ns() - start, "cpu_ns": time.process_time_ns() - cpu, "status": response.status_code})
    if response.status_code >= 400:
        raise AssertionError(f"{method} {path}: {response.status_code} {response.text}")
    return response.json() if response.content else None


def session(client, timings):
    login = call(client, "post", "/auth/login", timings, json={"token": TOKEN})
    client.headers.update({"X-CSRF-Token": login["csrf_token"]})


def run(seed):
    rng = random.Random(seed)
    pairs = sorted({(f"person:{rng.randrange(12)}", f"person:{rng.randrange(12)}") for _ in range(40)})
    expected = set(pairs)
    timings = {}
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    with tempfile.TemporaryDirectory(prefix="aether api benchmark ") as folder:
        app = create_app(data_dir=folder, auth_mode="token", token=TOKEN, public_origin="http://testserver")
        with TestClient(app) as client:
            session(client, timings)
            for i in range(12):
                call(client, "post", "/entities", timings, json={"entity_id": f"person:{i}", "properties": {"benchmark_fixture": True, "seed": seed}})
            fact_ids = {}
            for source, target in pairs:
                fact = call(client, "post", "/facts", timings, json={"subject": source, "predicate": "email", "object": target, "object_type": "str", "provenance": {"source": "api-benchmark-fixture", "evidence_type": "fixture"}})
                fact_ids[(source, target)] = fact["fact_id"]
            call(client, "post", "/rules", timings, json={"rule_id": "email-to-contact", "antecedents": [{"subject": "?x", "predicate": "email", "object": "?y"}], "consequent": {"subject": "?x", "predicate": "contact", "object": "?y"}})
            query = {"subject": "?x", "predicate": "contact", "object": "?y", "strategy": "forward", "offset": 0, "limit": 100}
            result = call(client, "post", "/queries", timings, json=query)
            actual = {(item["key"][0], item["key"][2]) for item in result["solutions"]}
            if not result["complete"] or actual != expected:
                raise AssertionError("API query oracle mismatch")
            cached = call(client, "post", "/queries", timings, json=query)
            if {(item["key"][0], item["key"][2]) for item in cached["solutions"]} != expected:
                raise AssertionError("cache oracle mismatch")
            chosen = pairs[0]
            explanation = call(client, "post", "/explanations", timings, json={"subject": chosen[0], "predicate": "contact", "object": chosen[1], "object_type": "str"})
            if not explanation["proofs"]:
                raise AssertionError("proof missing for real derived conclusion")
            call(client, "delete", f"/facts/{fact_ids[chosen]}", timings)
            expected.remove(chosen)
            after = call(client, "post", "/queries", timings, json=query)
            if {(item["key"][0], item["key"][2]) for item in after["solutions"]} != expected:
                raise AssertionError("stale cache or invalidation mismatch")
            history = call(client, "get", "/history?offset=0&limit=100", timings)
            if not any(item["operation"] == "fact_removed" for item in history["items"]):
                raise AssertionError("history missing mutation")
            memory = call(client, "get", "/memory", timings)
        restart_start = time.perf_counter_ns()
        with TestClient(create_app(data_dir=folder, auth_mode="token", token=TOKEN, public_origin="http://testserver")) as restarted:
            session(restarted, timings)
            recovered = call(restarted, "post", "/queries", timings, json=query)
            if {(item["key"][0], item["key"][2]) for item in recovered["solutions"]} != expected:
                raise AssertionError("API restart oracle mismatch")
        restart_ns = time.perf_counter_ns() - restart_start
    return {"seed": seed, "split": "calibration" if seed < 20 else "holdout", "facts_inserted": len(pairs), "dataset_sha256": hashlib.sha256(json.dumps(pairs).encode()).hexdigest(), "elapsed_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu, "restart_ns": restart_ns, "endpoint_timings": timings, "memory": memory, "oracle_match": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/evolution/phase9_api.json")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; preserve measurements and choose a new path")
    records = []
    for seed in range(30):
        records.append(run(seed))
        print(f"api flow {seed + 1}/30", flush=True)
    summary = {}
    for split in ("calibration", "holdout"):
        rows = [item for item in records if item["split"] == split]
        totals = sorted(item["elapsed_ns"] for item in rows)
        summary[split] = {"seeds": len(rows), "p50_complete_pipeline_ns": statistics.median(totals), "p95_observed_complete_pipeline_ns": totals[min(len(totals) - 1, int((len(totals) - 1) * .95))], "p50_cpu_ns": statistics.median(item["cpu_ns"] for item in rows), "p50_restart_ns": statistics.median(item["restart_ns"] for item in rows), "oracle_matches": sum(item["oracle_match"] for item in rows)}
    report = {"family": "studio_api_pipeline", "scope": "TestClient in-process full HTTP ASGI/auth/CSRF/JSON/core/cache/persistence cycle; no network/browser latency or production throughput claim", "fixture_type": "explicit synthetic relations/identities used only for independent correctness tests", "environment": {"platform": platform.platform(), "python": sys.version, "cpu_model": cpu_model(), "peak_rss_bytes_whole_process": peak_rss_bytes()}, "sources_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((ROOT / "src/aether/interfaces/api").rglob("*.py"))}, "summary": summary, "runs": records, "mismatches": 0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
