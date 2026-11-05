# Phase 9 operational benchmarks

`benchmarks/phase9/phase9_operational.py` measures the operational paths already implemented in AETHER. It is intentionally separate from the phase 9 join-planner benchmark and does not select, train, or promote an adaptive strategy.

## Scope

The harness has three independent workload families, each with 30 deterministic seeds. Seed indices `0..19` are labelled **calibration** and `20..29` are labelled **holdout**. The labels make the split visible for later analysis; this benchmark does not use calibration results to choose a strategy and therefore makes no adaptive generalization claim.

- **memory** uses `AdaptiveMemory` with a SQLite cold tier. It measures puts, gets, resident eviction, restart/open, post-restart recovery, persistence writes, and the maximum observed resident bytes. It also measures 2,048 bounded pattern observations per repeat. Every recovered payload is compared with an independently generated payload map, and the resident budgets check is made against the largest observed `stats()["resident_bytes"]` value; the pattern budget check covers keys, kinds, transition sources, edges, and total observations.
- **persistence** uses `KnowledgeStore.save` and `KnowledgeStore.load`. It measures atomic snapshot save, checksum-verified load/restart, history scans before and after load, rejection of a deliberately tampered snapshot, and rejection of a checksum-valid but unsupported schema version. The oracle compares typed fact identities, including `None`, `bool`, `int`, `float`, strings, `0.0`, and `-0.0`; Python equality alone is not used.
- **events** uses the SQLite-backed `EventEngine`. It measures enqueue, a claimed-but-interrupted lease, restart, lease recovery, FIFO processing, replay, and checkpoint save/load. Event IDs are enqueued twice to exercise duplicate suppression. Timestamps are intentionally out of order relative to enqueue sequence. The independent oracle applies the edge operations in FIFO enqueue order, and the processed event-ID sequence is compared with replay through SHA-256 hashes.

All measured operations report wall-clock nanoseconds and process CPU nanoseconds. The report records process peak RSS when the host exposes `resource.getrusage`; that value is process-wide, not attributed to an individual operation. Rust metadata is recorded as available or unavailable from the actual host; this benchmark does not invent a Rust runtime or compare an unexecuted native path.

## Bounded operational pattern learner

`IncrementalPatternLearner` retains only observable operational counters and adjacent transitions. It does not infer meaning, truth, relevance, or a semantic relation. `events_seen` is the total number of accepted observations; frequencies returned by `key_frequency`, `kind_frequency`, `hot_keys`, and transition methods describe only entries currently resident in bounded counters.

The historical `max_transition_targets` option remains supported. The learner now also accepts positive integer limits:

- `max_keys=4096`
- `max_kinds=64`
- `max_transition_sources=4096`

When a resident set exceeds its limit, the least frequent entry is evicted. Ties are broken lexically (`key`, or `(kind, key)` for transition sources and targets), so eviction and eviction counters are deterministic for a fixed input stream. `stats()` reports the configured limits and separate `key_evictions`, `kind_evictions`, `transition_source_evictions`, and `transition_target_evictions` counters. The global transition edge count is bounded by `max_transition_sources * max_transition_targets`.

An evicted counter is not silently treated as historical truth: querying it returns zero unless it has been observed again and is currently resident. This is bounded operational frequency bookkeeping, not general learning.

## Reproduction

Run from the repository root with the supplied baseline environment:

```bash
/tmp/aether-baseline-venv/bin/python benchmarks/phase9/phase9_operational.py \
  --repeats 3 \
  --output results/evolution/phase9_operational.json
```

The script refuses to replace an existing result unless `--force` is supplied. Use a new filename for a new run when preserving every historical record is required. A smaller smoke run can call the module helpers directly, but it is not a 30-seed report.

The JSON report contains the actual UTC generation time, Git head, Python executable/version, platform and machine data, CPU count, process peak RSS, Rust availability/version/source hash, source hashes for the benchmark and exercised modules, per-seed calibration/holdout labels, per-repeat samples, medians, checks, and summary p50/p95-observed values. Historical results are not edited by this harness.

## Limitations

The workload sizes are operational fixtures, not production capacity claims. Nanosecond timings are host- and load-dependent and should only be compared with runs from compatible environments. The process-wide RSS value cannot be attributed to one family or operation. The benchmark validates the implemented FIFO, retry/recovery, persistence, and bounded-storage contracts; it does not claim exactly-once delivery, semantic understanding, or a learned policy. Rust is reported but not benchmarked when the host lacks a Rust toolchain.
