#!/usr/bin/env python3
"""Measure compact temporal-event history versus materialized graph snapshots."""
from __future__ import annotations

from benchmarks._paths import phase5_manifest_path, repository_root

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import math
import statistics
import struct
import time
from pathlib import Path

from aether.graph.dynamic import DynamicGraph
from aether.temporal.events import TemporalEdgeHistory
from benchmarks.phase5.phase5_bench import current_rss_bytes, peak_rss_bytes, sha256_file


def load_temporal_snap(path: Path, entry: dict):
    parse_start = time.perf_counter_ns()
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    raw = []
    external_nodes = set()
    comments = 0
    malformed = []
    timestamp_non_decreasing = True
    previous_timestamp = -1
    with opener(path, "rt", encoding="utf-8", errors="strict") as stream:
        for sequence, line in enumerate(stream):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("#", "%", "//")):
                comments += 1
                continue
            fields = stripped.split()
            if len(fields) != 3:
                malformed.append(sequence + 1)
                continue
            try:
                source, target, timestamp = map(int, fields)
            except ValueError:
                malformed.append(sequence + 1)
                continue
            if source < 0 or target < 0 or timestamp < 0:
                raise ValueError(f"negative ID or timestamp on line {sequence + 1}")
            if timestamp < previous_timestamp:
                timestamp_non_decreasing = False
            previous_timestamp = timestamp
            raw.append((timestamp, sequence, source, target))
            external_nodes.update((source, target))
    parse_ms = (time.perf_counter_ns() - parse_start) / 1e6
    if malformed:
        raise ValueError(f"temporal file must contain SRC DST UNIXTS; malformed rows at {malformed[:10]}")
    if not raw:
        raise ValueError(f"no temporal event records found in {path}")

    sort_start = time.perf_counter_ns()
    if not timestamp_non_decreasing:
        raw.sort(key=lambda event: (event[0], event[1]))
    sort_ms = (time.perf_counter_ns() - sort_start) / 1e6

    declared_nodes = entry.get("nodes")
    declared_nodes = int(declared_nodes) if declared_nodes is not None else None
    identity = declared_nodes is not None and all(0 <= node < declared_nodes for node in external_nodes)
    if identity:
        n = declared_nodes
        mapping = None
        unlisted_isolates = max(0, n - len(external_nodes))
    else:
        ordered = sorted(external_nodes)
        mapping = {external: index for index, external in enumerate(ordered)}
        n = max(len(ordered), declared_nodes or 0)
        unlisted_isolates = max(0, n - len(ordered))
    events = [
        (timestamp, source if mapping is None else mapping[source], target if mapping is None else mapping[target])
        for timestamp, _, source, target in raw
    ]
    unique_pairs = {(source, target) for _, source, target in events}
    times = [timestamp for timestamp, _, _ in events]
    stats = {
        "event_records": len(events),
        "unique_directed_relations": len(unique_pairs),
        "repeated_interaction_events": len(events) - len(unique_pairs),
        "external_node_ids_in_file": len(external_nodes),
        "declared_nodes": declared_nodes,
        "internal_nodes": n,
        "unlisted_nodes_preserved_as_isolates": unlisted_isolates,
        "ids_relabelled_to_dense_range": mapping is not None,
        "comment_lines_skipped": comments,
        "input_timestamps_non_decreasing": timestamp_non_decreasing,
        "events_reordered_by_timestamp": not timestamp_non_decreasing,
        "same_timestamp_tie_order": "original file row order",
        "first_timestamp_unix_seconds": times[0],
        "last_timestamp_unix_seconds": times[-1],
        "observed_window_days": (times[-1] - times[0]) / 86400,
        "official_temporal_event_count": entry.get("temporal_events", entry.get("edges")),
        "official_static_edge_count": entry.get("static_edges"),
    }
    return n, events, stats, parse_ms, sort_ms


def _digest_edges(graph):
    digest = hashlib.sha256()
    count = 0
    for source in range(graph.n):
        for target in sorted(graph.neighbors(source)):
            digest.update(struct.pack("<II", source, target))
            count += 1
    return digest.hexdigest(), count


def _independent_snapshot(n, events, stop_count):
    adjacency = [set() for _ in range(n)]
    for _, source, target in events[:stop_count]:
        adjacency[source].add(target)
    digest = hashlib.sha256()
    count = 0
    for source, neighbors in enumerate(adjacency):
        for target in sorted(neighbors):
            digest.update(struct.pack("<II", source, target))
            count += 1
    return digest.hexdigest(), count


def run_temporal_experiment(path: Path, entry: dict, archive_sha256: str):
    wall_start = time.perf_counter_ns()
    n, events, parse_stats, parse_ms, sort_ms = load_temporal_snap(path, entry)
    current_rss_before = current_rss_bytes()
    ingest_start = time.perf_counter_ns()
    history = TemporalEdgeHistory(n)
    changed_events = 0
    for timestamp, source, target in events:
        changed_events += history.append(timestamp, "add", source, target)
    ingest_ms = (time.perf_counter_ns() - ingest_start) / 1e6
    live_digest, live_edge_count = _digest_edges(history.current)
    expected_live_digest, expected_live_count = _independent_snapshot(n, events, len(events))
    if live_digest != expected_live_digest or live_edge_count != expected_live_count:
        raise AssertionError("incremental current graph differs from independent replay")

    timestamps = [event[0] for event in events]
    fractions = (0.10, 0.25, 0.50, 0.75, 1.0)
    candidate_times = []
    for fraction in fractions:
        index = max(1, min(len(events), math.ceil(len(events) * fraction)))
        candidate_times.append(timestamps[index - 1])
    checkpoint_times = sorted(set(candidate_times))

    rows = []
    retained_snapshots = []
    replay_latencies = []
    for timestamp in checkpoint_times:
        stop_count = bisect.bisect_right(timestamps, timestamp)
        replay_start = time.perf_counter_ns()
        snapshot = history.state_at_timestamp(timestamp)
        replay_ms = (time.perf_counter_ns() - replay_start) / 1e6
        digest, edge_count = _digest_edges(snapshot)
        oracle_start = time.perf_counter_ns()
        expected_digest, expected_count = _independent_snapshot(n, events, stop_count)
        oracle_ms = (time.perf_counter_ns() - oracle_start) / 1e6
        exact = digest == expected_digest and edge_count == expected_count
        if not exact:
            raise AssertionError(f"historical snapshot mismatch at timestamp {timestamp}")
        retained_snapshots.append(snapshot)
        replay_latencies.append(replay_ms)
        rows.append({
            "timestamp_unix_seconds": timestamp,
            "events_in_state": stop_count,
            "directed_edges_in_state": edge_count,
            "reconstruction_ms": replay_ms,
            "independent_oracle_ms_excluded": oracle_ms,
            "materialized_snapshot_bytes_estimate": snapshot.memory_bytes(),
            "edge_sha256": digest,
            "exact_vs_independent_replay": exact,
        })

    materialized_graph_bytes = sum(snapshot.memory_bytes() for snapshot in retained_snapshots)
    materialized_container_bytes = sum(__import__("sys").getsizeof(snapshot) for snapshot in retained_snapshots)
    compact_history_total_bytes = history.memory_bytes()
    history_log_bytes = history.log_memory_bytes
    current_graph_bytes = history.current.memory_bytes()
    final_rss = current_rss_bytes()
    peak_rss = peak_rss_bytes()
    elapsed_ms = (time.perf_counter_ns() - wall_start) / 1e6
    report = {
        "title": "AETHER Phase 5 — temporal event-log prototype",
        "dataset": {
            "id": entry["id"],
            "name": entry.get("name", entry["id"]),
            "snap_page": entry["snap_page"],
            "download_url": entry["download_url"],
            "license_or_terms": entry.get("license_or_terms", "not stated"),
            "archive_sha256": archive_sha256,
            "archive_bytes": path.stat().st_size,
            "official_nodes": entry.get("nodes"),
            "official_temporal_events": entry.get("temporal_events", entry.get("edges")),
            "official_static_edges": entry.get("static_edges"),
            "direction": "directed; original event arcs are preserved; no reverse arcs are added",
            "official_event_semantics": entry.get("event_semantics", "not stated"),
        },
        "parsed": parse_stats,
        "transforms": [
            "each raw event remains a distinct log row, including repeated interactions",
            "event application is directed and uses operation='add'; repeated edge events are no-op graph updates but remain in history",
            "internal node IDs are relabelled only if original IDs fall outside the declared 0..n-1 range; this is recorded in parsed metadata",
            "if input timestamps are not non-decreasing, events are stably sorted by (timestamp, original row order)",
            "the public dataset contains interaction events, not relation deletions; removal support is tested separately by the prototype tests",
        ],
        "architecture": {
            "live_state": "one mutable compact Python adjacency graph",
            "event_log": "parallel arrays: uint64 timestamp, uint32 source, uint32 target, uint8 operation; sequence index is array position",
            "historical_state": "reconstructed on demand by replay through the selected timestamp; no historical graph snapshots are cached",
            "cache_count": history.cached_snapshots,
            "same_timestamp_order": "stable original input order",
        },
        "measurements": {
            "n": n,
            "event_count": history.event_count,
            "new_unique_relation_events": changed_events,
            "repeated_or_noop_events": history.event_count - changed_events,
            "current_unique_directed_edges": history.edge_count,
            "current_exact_vs_independent_replay": True,
            "ingest_ms": ingest_ms,
            "parse_ms": parse_ms,
            "sort_ms": sort_ms,
            "end_to_end_ms_including_parse_sort_and_ingest": elapsed_ms,
            "history_log_bytes_estimate": history_log_bytes,
            "current_graph_bytes_estimate": current_graph_bytes,
            "log_plus_current_graph_bytes_estimate": compact_history_total_bytes,
            "materialized_snapshots_count": len(retained_snapshots),
            "materialized_snapshots_graph_bytes_estimate": materialized_graph_bytes,
            "materialized_snapshots_container_bytes_estimate": materialized_container_bytes,
            "log_plus_current_vs_snapshots_only_bytes_ratio": (
                compact_history_total_bytes / materialized_graph_bytes
                if materialized_graph_bytes else None
            ),
            "historical_reconstruction_median_ms": statistics.median(replay_latencies) if replay_latencies else None,
            "historical_reconstruction_max_ms": max(replay_latencies) if replay_latencies else None,
            "rss_before_ingest_bytes": current_rss_before,
            "rss_after_experiment_bytes": final_rss,
            "process_peak_rss_bytes": peak_rss,
        },
        "checkpoints": rows,
        "limitations": [
            "The event log supports add and remove records, but the selected SNAP temporal dataset supplies interaction/add events only; its timestamped events are not observed deletions.",
            "Historical reconstruction is O(number of events up to the queried time); without checkpoints, old-state queries can become expensive.",
            "The memory figures use Python sys.getsizeof estimates for adjacency and array capacities; allocator fragmentation and process RSS are reported separately.",
            "Snapshot comparison keeps five selected reconstructed graph objects simultaneously to estimate the cost of materializing history; it does not retain these snapshots in the prototype itself.",
            "The source pages do not publish dataset-specific license terms; unknown status is preserved rather than inferring the software SNAP BSD license for the data.",
        ],
    }
    return report, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(phase5_manifest_path()))
    parser.add_argument("--dataset", default="sx-askubuntu")
    parser.add_argument("--data-dir", default="data/phase5_snap")
    parser.add_argument("--out", default="results/phase5/temporal_history")
    args = parser.parse_args()
    root = repository_root()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute(): manifest_path = root / manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {item["id"]: item for item in manifest["datasets"]}
    if args.dataset not in entries:
        parser.error(f"temporal dataset {args.dataset!r} missing from manifest")
    entry = entries[args.dataset]
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute(): data_dir = root / data_dir
    path = data_dir / args.dataset / (entry.get("filename") or entry["download_url"].rsplit("/", 1)[-1])
    if not path.exists():
        raise FileNotFoundError(f"dataset archive missing: {path}; download it only after reviewing the recorded SNAP conditions")
    digest = sha256_file(path)
    if entry.get("sha256") and digest.lower() != entry["sha256"].lower():
        raise ValueError("dataset archive SHA-256 differs from manifest")
    output_dir = Path(args.out)
    if not output_dir.is_absolute(): output_dir = root / output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite prior results in {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    report, rows = run_temporal_experiment(path, entry, digest)
    csv_path = output_dir / "temporal_checkpoints.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    report["checkpoint_csv"] = str(csv_path)
    report["archive_sha256"] = digest
    (output_dir / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_dir), "events": report["measurements"]["event_count"],
                      "current_edges": report["measurements"]["current_unique_directed_edges"],
                      "log_bytes": report["measurements"]["history_log_bytes_estimate"],
                      "snapshot_count": report["measurements"]["materialized_snapshots_count"]}, indent=2))


if __name__ == "__main__":
    main()
