#!/usr/bin/env python3
"""Operational benchmarks for AETHER phase 9 memory and event criteria.

The benchmark measures complete operation paths using the repository's real
AdaptiveMemory, KnowledgeStore persistence, and EventEngine implementations.
Each family has 30 deterministic seeds (20 calibration, 10 holdout) and a
configurable number of fresh-process-equivalent repeats. Calibration and
holdout are labels only: this harness does not train or select an adaptive
strategy, so it makes no adaptive generalization claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - resource is unavailable on Windows.
    resource = None

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aether.core.knowledge.persistence import scalar_identity
from aether.core.knowledge.store import KnowledgeStore
from aether.memory.adaptive_storage import AdaptiveMemory
from aether.memory.patterns import IncrementalPatternLearner
from aether.temporal.engine import EventEngine


FAMILIES = ("memory", "persistence", "events")
SEEDS_PER_FAMILY = 30
CALIBRATION_SEEDS = 20
HOLDOUT_SEEDS = 10
DEFAULT_REPEATS = 3


def _measure(function):
    started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    value = function()
    return value, time.perf_counter_ns() - started, time.process_time_ns() - cpu_started


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_ids(values) -> str:
    return _sha256_bytes("\n".join(values).encode("utf-8"))


def _canonical_state(edges) -> tuple[str, ...]:
    return tuple(sorted(f"{source}:{target}" for source, target in edges))


def _memory_workload(seed: int, repeat: int) -> dict:
    rng = random.Random(seed * 1009 + repeat)
    key_count = 192 + rng.randrange(33)
    max_bytes = 8 * 1024
    payloads = {
        f"memory-{seed}-{index}": bytes(
            ((seed + index * 13 + offset) % 251 for offset in range(48 + index % 17))
        )
        for index in range(key_count)
    }
    expected_digest = _sha256_bytes(
        json.dumps(
            [(key, payload.hex()) for key, payload in sorted(payloads.items())],
            separators=(",", ":"),
        ).encode("utf-8")
    )
    pattern_learner = IncrementalPatternLearner(
        max_keys=512,
        max_kinds=32,
        max_transition_sources=512,
        max_transition_targets=32,
    )
    pattern_events = [
        (f"kind-{index % 17}", f"pattern-{seed}-{index}")
        for index in range(2048)
    ]

    def observe_patterns():
        for kind, key in pattern_events:
            pattern_learner.observe(kind, key)
        return pattern_learner.stats()

    pattern_result, pattern_update_elapsed_ns, pattern_update_cpu_ns = _measure(
        observe_patterns
    )
    max_actual_resident_bytes = 0
    with tempfile.TemporaryDirectory(prefix=f"aether-phase9-memory-{seed}-") as folder:
        cold_path = Path(folder) / "memory.sqlite3"
        memory = AdaptiveMemory(max_bytes, cold_store=cold_path)
        put_stats = {"max_resident_bytes": 0}

        def put_all():
            for key, payload in payloads.items():
                memory.put(key, payload)
                put_stats["max_resident_bytes"] = max(
                    put_stats["max_resident_bytes"], memory.stats()["resident_bytes"]
                )
            return memory.stats()

        put_result, put_elapsed_ns, put_cpu_ns = _measure(put_all)
        max_actual_resident_bytes = max(max_actual_resident_bytes, put_stats["max_resident_bytes"])

        get_keys = list(payloads)
        rng.shuffle(get_keys)

        def get_all():
            for key in get_keys:
                if memory.get(key) != payloads[key]:
                    raise AssertionError(f"memory oracle mismatch before restart: {key}")
            return memory.stats()

        get_result, get_elapsed_ns, get_cpu_ns = _measure(get_all)
        max_actual_resident_bytes = max(max_actual_resident_bytes, get_result["resident_bytes"])
        memory.close()

        def restart():
            return AdaptiveMemory(max_bytes, cold_store=cold_path)

        restarted, restart_elapsed_ns, restart_cpu_ns = _measure(restart)
        try:
            def recover_all():
                for key in get_keys:
                    if restarted.get(key) != payloads[key]:
                        raise AssertionError(f"memory oracle mismatch after restart: {key}")
                return restarted.stats()

            recovery_result, recovery_elapsed_ns, recovery_cpu_ns = _measure(recover_all)
            max_actual_resident_bytes = max(
                max_actual_resident_bytes, recovery_result["resident_bytes"]
            )
            final_stats = recovery_result
        finally:
            restarted.close()

    return {
        "put_elapsed_ns": put_elapsed_ns,
        "put_cpu_ns": put_cpu_ns,
        "get_elapsed_ns": get_elapsed_ns,
        "get_cpu_ns": get_cpu_ns,
        "restart_elapsed_ns": restart_elapsed_ns,
        "restart_cpu_ns": restart_cpu_ns,
        "restart_recovery_elapsed_ns": recovery_elapsed_ns,
        "restart_recovery_cpu_ns": recovery_cpu_ns,
        "pattern_update_elapsed_ns": pattern_update_elapsed_ns,
        "pattern_update_cpu_ns": pattern_update_cpu_ns,
        "pattern_events": len(pattern_events),
        "pattern_resident_keys": pattern_result["distinct_keys"],
        "pattern_resident_kinds": pattern_result["distinct_kinds"],
        "pattern_transition_sources": pattern_result["transition_sources"],
        "pattern_transition_edges": pattern_result["transition_edges"],
        "evictions": int(final_stats["evictions"]),
        "persist_writes": int(final_stats["persist_writes"]),
        "expected_keys": len(payloads),
        "recovered_keys": len(payloads),
        "max_actual_resident_bytes": int(max_actual_resident_bytes),
        "resident_budget_bytes": max_bytes,
        "resident_budget_ok": max_actual_resident_bytes <= max_bytes,
        "pattern_budget_ok": (
            pattern_result["distinct_keys"] <= pattern_learner.max_keys
            and pattern_result["distinct_kinds"] <= pattern_learner.max_kinds
            and pattern_result["transition_sources"] <= pattern_learner.max_transition_sources
            and pattern_result["transition_edges"]
            <= pattern_learner.max_transition_sources * pattern_learner.max_transition_targets
            and pattern_result["events_seen"] == len(pattern_events)
        ),
        "oracle_state_sha256": expected_digest,
        "oracle_match": final_stats["cold_entries"] + final_stats["resident_entries"] == len(payloads),
    }


def _build_persistence_store(seed: int) -> tuple[KnowledgeStore, set[tuple[str, str, tuple]]]:
    store = KnowledgeStore(history_limit=512)
    subjects = [f"entity-{seed}-{index}" for index in range(48)]
    for subject in subjects:
        store.add_entity(subject, {"seed": seed, "index": subjects.index(subject)})

    typed_subject = subjects[0]
    typed_values = (None, False, True, 1, 1.0, "1", 0.0, -0.0)
    expected: set[tuple[str, str, tuple]] = set()
    for value in typed_values:
        store.add_fact(typed_subject, "typed-value", value)
        expected.add((typed_subject, "typed-value", scalar_identity(value)))

    for index in range(96):
        subject = subjects[index % len(subjects)]
        value = f"object-{seed}-{index}"
        store.add_fact(subject, f"predicate-{index % 7}", value)
        expected.add((subject, f"predicate-{index % 7}", scalar_identity(value)))
    return store, expected


def _fact_identity_set(store: KnowledgeStore) -> set[tuple[str, str, tuple]]:
    return {
        (fact.subject, fact.predicate, scalar_identity(fact.object))
        for fact in store.query()
    }


def _persistence_workload(seed: int, repeat: int) -> dict:
    del repeat  # Fresh deterministic store for every repeat.
    store, expected = _build_persistence_store(seed)
    state_signature = json.dumps(
        [
            [subject, predicate, identity[0], repr(identity[1])]
            for subject, predicate, identity in sorted(expected, key=repr)
        ],
        separators=(",", ":"),
    ).encode("utf-8")
    expected_digest = _sha256_bytes(state_signature)

    with tempfile.TemporaryDirectory(prefix=f"aether-phase9-persistence-{seed}-") as folder:
        snapshot_path = Path(folder) / "knowledge.snapshot.json"
        corrupt_path = Path(folder) / "knowledge.corrupt.json"
        incompatible_path = Path(folder) / "knowledge.incompatible.json"
        _, save_elapsed_ns, save_cpu_ns = _measure(lambda: store.save(snapshot_path))

        def load_snapshot():
            return KnowledgeStore.load(snapshot_path)

        loaded, load_elapsed_ns, load_cpu_ns = _measure(load_snapshot)

        def scan_history():
            return store.history_changes(offset=0, limit=10_000)

        history, history_elapsed_ns, history_cpu_ns = _measure(scan_history)

        def scan_loaded_history():
            return loaded.history_changes(offset=0, limit=10_000)

        loaded_history, loaded_history_elapsed_ns, loaded_history_cpu_ns = _measure(
            scan_loaded_history
        )
        snapshot_bytes = snapshot_path.read_bytes()
        tampered = bytearray(snapshot_bytes)
        tampered[-2] ^= 1
        corrupt_path.write_bytes(tampered)

        def verify_corruption_is_rejected():
            try:
                KnowledgeStore.load(corrupt_path)
            except (RuntimeError, ValueError):
                return True
            return False

        checksum_rejected, checksum_elapsed_ns, checksum_cpu_ns = _measure(
            verify_corruption_is_rejected
        )

        envelope = json.loads(snapshot_path.read_text(encoding="utf-8"))
        envelope["payload"]["schema_version"] = 999
        canonical_payload = json.dumps(
            envelope["payload"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        envelope["sha256"] = _sha256_bytes(canonical_payload)
        incompatible_path.write_text(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        def verify_incompatible_schema_is_rejected():
            try:
                KnowledgeStore.load(incompatible_path)
            except ValueError as exc:
                return "unsupported knowledge snapshot schema" in str(exc)
            return False

        schema_rejected, schema_elapsed_ns, schema_cpu_ns = _measure(
            verify_incompatible_schema_is_rejected
        )

    loaded_identity = _fact_identity_set(loaded)
    oracle_match = loaded_identity == expected and _fact_identity_set(store) == expected
    typed_identity_preserved = {
        identity
        for subject, predicate, identity in loaded_identity
        if subject == f"entity-{seed}-0" and predicate == "typed-value"
    } == {
        scalar_identity(value) for value in (None, False, True, 1, 1.0, "1", 0.0, -0.0)
    }
    return {
        "snapshot_save_elapsed_ns": save_elapsed_ns,
        "snapshot_save_cpu_ns": save_cpu_ns,
        "snapshot_load_restart_elapsed_ns": load_elapsed_ns,
        "snapshot_load_restart_cpu_ns": load_cpu_ns,
        "history_scan_elapsed_ns": history_elapsed_ns,
        "history_scan_cpu_ns": history_cpu_ns,
        "loaded_history_scan_elapsed_ns": loaded_history_elapsed_ns,
        "loaded_history_scan_cpu_ns": loaded_history_cpu_ns,
        "checksum_validation_elapsed_ns": checksum_elapsed_ns,
        "checksum_validation_cpu_ns": checksum_cpu_ns,
        "schema_validation_elapsed_ns": schema_elapsed_ns,
        "schema_validation_cpu_ns": schema_cpu_ns,
        "snapshot_bytes": len(snapshot_bytes),
        "history_records": len(history),
        "loaded_history_records": len(loaded_history),
        "facts": len(expected),
        "checksum_rejected": bool(checksum_rejected),
        "schema_incompatible_rejected": bool(schema_rejected),
        "typed_identity_preserved": typed_identity_preserved,
        "oracle_match": oracle_match,
        "oracle_state_sha256": expected_digest,
    }


def _event_specs(seed: int):
    rng = random.Random(seed * 9176 + 23)
    specs = []
    prior_edges = []
    for index in range(84):
        if index % 5 == 4 and prior_edges:
            source, target = prior_edges[(index * 7 + seed) % len(prior_edges)]
            operation = "remove"
        else:
            source = (seed + index * 3) % 17
            target = (seed * 2 + index * 5) % 19
            edge = (source, target)
            if edge not in prior_edges:
                prior_edges.append(edge)
            operation = "add"
        specs.append(
            {
                "event_id": f"phase9-{seed}-{index}",
                "timestamp_ns": 1_700_000_000_000_000_000 + ((index * 17 + seed * 3) % 29),
                "payload": {
                    "operation": operation,
                    "source": source,
                    "target": target,
                },
            }
        )
    order = list(range(len(specs)))
    rng.shuffle(order)
    return [specs[index] for index in order]


def _event_workload(seed: int, repeat: int) -> dict:
    del repeat
    specs = _event_specs(seed)
    with tempfile.TemporaryDirectory(prefix=f"aether-phase9-events-{seed}-") as folder:
        database_path = Path(folder) / "events.sqlite3"
        engine = EventEngine(database_path, max_pending=512, lease_seconds=0.001)
        inserted_records = []
        duplicate_receipts = 0
        enqueue_timestamp_values = []

        def enqueue_all():
            nonlocal duplicate_receipts
            for spec in specs:
                receipt = engine.enqueue(
                    "graph.edge",
                    spec["payload"],
                    source="phase9-benchmark",
                    event_id=spec["event_id"],
                    timestamp_ns=spec["timestamp_ns"],
                    provenance={"seed": seed, "family": "events"},
                )
                enqueue_timestamp_values.append(receipt.event.timestamp_ns)
                if receipt.inserted:
                    inserted_records.append(receipt.event)
                duplicate = engine.enqueue(
                    "graph.edge",
                    spec["payload"],
                    source="phase9-benchmark",
                    event_id=spec["event_id"],
                    timestamp_ns=spec["timestamp_ns"],
                    provenance={"seed": seed, "family": "events"},
                )
                if not duplicate.inserted:
                    duplicate_receipts += 1
            return len(inserted_records)

        inserted_count, enqueue_elapsed_ns, enqueue_cpu_ns = _measure(enqueue_all)
        if not inserted_records:
            raise AssertionError("event workload inserted no records")
        input_timestamps = [record.timestamp_ns for record in inserted_records]
        out_of_order_input = any(
            left > right for left, right in zip(input_timestamps, input_timestamps[1:])
        )
        expected_ids = [record.event_id for record in inserted_records]
        expected_state: set[tuple[int, int]] = set()
        for record in inserted_records:
            edge = (record.payload["source"], record.payload["target"])
            if record.payload["operation"] == "add":
                expected_state.add(edge)
            else:
                expected_state.discard(edge)

        claimed, claim_elapsed_ns, claim_cpu_ns = _measure(
            lambda: engine._claim_next("phase9-crash-simulation", time.time_ns(), 3)
        )
        if claimed is None:
            raise AssertionError("event workload could not claim a recovery candidate")
        recovery_now_ns = time.time_ns() + engine.lease_ns + 1
        engine.close()
        restarted, restart_elapsed_ns, restart_cpu_ns = _measure(
            lambda: EventEngine(database_path, max_pending=512, lease_seconds=0.001)
        )
        recovered_count, recovery_elapsed_ns, recovery_cpu_ns = _measure(
            lambda: restarted.recover_interrupted(now_ns=recovery_now_ns)
        )
        if recovered_count != 1:
            raise AssertionError(f"expected one expired processing lease, got {recovered_count}")

        processed_ids = []
        processed_state: set[tuple[int, int]] = set()

        def handler(event):
            processed_ids.append(event.event_id)
            edge = (event.payload["source"], event.payload["target"])
            if event.payload["operation"] == "add":
                processed_state.add(edge)
            else:
                processed_state.discard(edge)

        batch, process_elapsed_ns, process_cpu_ns = _measure(
            lambda: restarted.process_batch(handler, limit=512, worker_id="phase9-worker")
        )
        replay_ids = []
        replay, replay_elapsed_ns, replay_cpu_ns = _measure(
            lambda: restarted.replay(lambda event: replay_ids.append(event.event_id), page_size=32)
        )
        checkpoint_state = json.dumps(sorted(f"{source}:{target}" for source, target in processed_state)).encode()
        checkpoint, checkpoint_save_elapsed_ns, checkpoint_save_cpu_ns = _measure(
            lambda: restarted.save_checkpoint(checkpoint_state, checkpoint_id=f"checkpoint-{seed}")
        )
        loaded_checkpoint, checkpoint_load_elapsed_ns, checkpoint_load_cpu_ns = _measure(
            lambda: restarted.load_checkpoint(checkpoint.checkpoint_id)
        )
        fifo_hash = _sha256_ids(processed_ids)
        replay_hash = _sha256_ids(replay_ids)
        queue_stats = restarted.queue_stats()
        integrity = restarted.integrity_check()
        restarted.close()

    return {
        "enqueue_elapsed_ns": enqueue_elapsed_ns,
        "enqueue_cpu_ns": enqueue_cpu_ns,
        "claim_elapsed_ns": claim_elapsed_ns,
        "claim_cpu_ns": claim_cpu_ns,
        "restart_elapsed_ns": restart_elapsed_ns,
        "restart_cpu_ns": restart_cpu_ns,
        "recovery_elapsed_ns": recovery_elapsed_ns,
        "recovery_cpu_ns": recovery_cpu_ns,
        "process_elapsed_ns": process_elapsed_ns,
        "process_cpu_ns": process_cpu_ns,
        "replay_elapsed_ns": replay_elapsed_ns,
        "replay_cpu_ns": replay_cpu_ns,
        "checkpoint_save_elapsed_ns": checkpoint_save_elapsed_ns,
        "checkpoint_save_cpu_ns": checkpoint_save_cpu_ns,
        "checkpoint_load_elapsed_ns": checkpoint_load_elapsed_ns,
        "checkpoint_load_cpu_ns": checkpoint_load_cpu_ns,
        "enqueued_unique": inserted_count,
        "duplicate_receipts": duplicate_receipts,
        "processed": batch.processed,
        "replayed": replay.events_replayed,
        "recovered_leases": recovered_count,
        "out_of_order_input_timestamps": out_of_order_input,
        "fifo_sequence_ok": processed_ids == expected_ids,
        "processed_fifo_hash": fifo_hash,
        "replay_fifo_hash": replay_hash,
        "fifo_replay_hash_match": fifo_hash == replay_hash,
        "oracle_match": processed_state == expected_state,
        "checkpoint_checksum_match": loaded_checkpoint is not None and loaded_checkpoint.digest == checkpoint.digest,
        "queue_drained": queue_stats["unprocessed"] == 0,
        "integrity": integrity,
    }


def _run_family(family: str, seed: int, repeats: int) -> dict:
    runner = {
        "memory": _memory_workload,
        "persistence": _persistence_workload,
        "events": _event_workload,
    }[family]
    samples = [runner(seed, repeat) for repeat in range(repeats)]
    metric_names = sorted(
        name
        for name, value in samples[0].items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    metrics = {
        name: {
            "samples": [sample[name] for sample in samples],
            "median": int(statistics.median(sample[name] for sample in samples)),
        }
        for name in metric_names
    }
    checks = {
        name: all(bool(sample[name]) for sample in samples)
        for name, value in samples[0].items()
        if isinstance(value, bool)
    }
    hashes = {
        name: samples[0][name]
        for name, value in samples[0].items()
        if name.endswith("sha256") or name.endswith("_hash") or name == "integrity"
    }
    return {"repeats": repeats, "metrics": metrics, "checks": checks, "identities": hashes}


def _percentile(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def _summarize_family(records: list[dict]) -> dict:
    summary = {"seeds": len(records), "calibration": {}, "holdout": {}}
    metric_names = sorted({name for record in records for name in record["result"]["metrics"]})
    for segment, selected in (
        ("all", records),
        ("calibration", [r for r in records if r["calibration_or_holdout"] == "calibration"]),
        ("holdout", [r for r in records if r["calibration_or_holdout"] == "holdout"]),
    ):
        segment_summary = {"seeds": len(selected)}
        for name in metric_names:
            values = [record["result"]["metrics"][name]["median"] for record in selected if name in record["result"]["metrics"]]
            if not values:
                continue
            segment_summary[name] = {
                "p50_observed": int(statistics.median(values)),
                "p95_observed": int(_percentile(values, 0.95)),
            }
        check_names = sorted({name for record in selected for name in record["result"]["checks"]})
        segment_summary["checks"] = {
            name: sum(bool(record["result"]["checks"].get(name, False)) for record in selected)
            for name in check_names
        }
        if segment == "all":
            summary["all"] = segment_summary
        else:
            summary[segment] = segment_summary
    return summary


def _git_head():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return None


def _rust_metadata():
    rustc = shutil.which("rustc")
    if rustc is None:
        return {"available": False, "rustc": None, "rust_source_sha256": None}
    try:
        version = subprocess.run([rustc, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        version = None
    rust_files = sorted((ROOT / "src" / "aether" / "native" / "rust").glob("*.rs"))
    digest = hashlib.sha256()
    for path in rust_files:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return {"available": True, "rustc": version, "rust_source_sha256": digest.hexdigest()}


def _environment_metadata():
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "uname": dict(zip(("system", "node", "release", "version", "machine", "processor"), platform.uname())),
        "process_peak_rss_bytes": (
            None
            if resource is None
            else int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            * (1 if sys.platform == "darwin" else 1024)
        ),
        "process_peak_rss_scope": "whole benchmark process; not attributed per operation",
        "rust": _rust_metadata(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "results" / "evolution" / "phase9_operational.json",
    )
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--force", action="store_true", help="allow replacing an existing output path")
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 15:
        parser.error("--repeats must be between 1 and 15")
    if args.output.exists() and not args.force:
        parser.error(f"refusing to overwrite existing result: {args.output}; use --force")

    records = []
    for family in FAMILIES:
        for seed_index in range(SEEDS_PER_FAMILY):
            seed = 92100 + seed_index
            result = _run_family(family, seed, args.repeats)
            records.append(
                {
                    "family": family,
                    "seed_index": seed_index,
                    "seed": seed,
                    "calibration_or_holdout": (
                        "calibration" if seed_index < CALIBRATION_SEEDS else "holdout"
                    ),
                    "result": result,
                }
            )
            print(f"{family}: seed {seed_index + 1}/{SEEDS_PER_FAMILY}", flush=True)

    source_paths = [
        ROOT / "benchmarks" / "phase9" / "phase9_operational.py",
        ROOT / "src" / "aether" / "memory" / "patterns.py",
        ROOT / "src" / "aether" / "memory" / "adaptive_storage.py",
        ROOT / "src" / "aether" / "core" / "knowledge" / "persistence.py",
        ROOT / "src" / "aether" / "temporal" / "engine.py",
    ]
    report = {
        "benchmark": "phase9_operational",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_head": _git_head(),
        "environment": _environment_metadata(),
        "configuration": {
            "families": list(FAMILIES),
            "seeds_per_family": SEEDS_PER_FAMILY,
            "calibration_seeds_per_family": CALIBRATION_SEEDS,
            "holdout_seeds_per_family": HOLDOUT_SEEDS,
            "repeats_per_seed": args.repeats,
            "adaptive_selection_used": False,
            "semantic_claim": "operational counts, transitions, persistence and queue behavior only; no general learning or semantic inference",
        },
        "source_sha256": {
            path.relative_to(ROOT).as_posix(): _sha256_bytes(path.read_bytes()) for path in source_paths
        },
        "summary": {
            family: _summarize_family([record for record in records if record["family"] == family])
            for family in FAMILIES
        },
        "runs": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output}")
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
