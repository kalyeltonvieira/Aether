#!/usr/bin/env python3
"""Create accuracy-aware figures from Phase 5 CSV/JSON outputs."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


LABELS = {
    "python_sets": "Python sets",
    "python_compact": "Python compacto",
    "python_csr": "Python CSR",
    "rust_ffi_single": "Rust FFI unitário",
    "rust_ffi_batch": "Rust FFI em lote",
    "feature_policy": "Política por características",
    "online_controller": "Controlador online",
}
COLORS = {
    "python_sets": "#4477AA",
    "python_compact": "#66CCEE",
    "python_csr": "#228833",
    "rust_ffi_single": "#CCBB44",
    "rust_ffi_batch": "#EE6677",
    "feature_policy": "#AA3377",
    "online_controller": "#BBBBBB",
}
DATASET_LABELS = {
    "email-eu-core": "email-Eu-core",
    "wiki-vote": "wiki-Vote",
    "soc-epinions1": "soc-Epinions1",
    "web-google": "web-Google",
}


def _read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        for key, value in list(row.items()):
            if value == "":
                row[key] = None
                continue
            try:
                row[key] = float(value)
            except (TypeError, ValueError):
                pass
    return rows


def _median(rows, key):
    values = [row.get(key) for row in rows if isinstance(row.get(key), (int, float))]
    return statistics.median(values) if values else None


def _save_bars(rows, mode, metric, title, ylabel, output, log=False, allow_missing=True):
    selected = [row for row in rows if row.get("mode") == mode]
    datasets = list(dict.fromkeys(row["dataset_id"] for row in selected))
    methods = list(dict.fromkeys(row["method"] for row in selected))
    if not datasets or not methods:
        return None
    x = np.arange(len(datasets), dtype=float)
    width = 0.82 / max(1, len(methods))
    fig, ax = plt.subplots(figsize=(max(9, 2.25 * len(datasets)), 5.8), constrained_layout=True)
    plotted = False
    for index, method in enumerate(methods):
        values = []
        valid = []
        for dataset in datasets:
            sample = [row for row in selected if row["dataset_id"] == dataset and row["method"] == method]
            value = _median(sample, metric)
            if value is None or (log and value <= 0):
                values.append(0.0)
                valid.append(False)
            else:
                values.append(value)
                valid.append(True)
        if any(valid):
            positions = x + (index - (len(methods) - 1) / 2) * width
            ax.bar(positions, values, width, label=LABELS.get(method, method),
                   color=COLORS.get(method, "#777777"), alpha=0.92)
            plotted = True
    ax.set_xticks(x, [DATASET_LABELS.get(dataset, dataset) for dataset in datasets], rotation=0)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if log:
        ax.set_yscale("log")
    ax.grid(axis="y", which="both", alpha=0.22)
    if plotted:
        ax.legend(loc="best", frameon=False, ncols=2)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return output


def _save_ffi(rows, output):
    batch_rows = [row for row in rows if row.get("method") == "rust_ffi_batch" and row.get("mode") == "static"]
    datasets = list(dict.fromkeys(row["dataset_id"] for row in batch_rows))
    if not datasets:
        return None
    series = [
        ("ffi_batch_real_call_ms", "Lote Rust: chamadas reais"),
        ("ffi_batch_zero_hop_call_ms", "Lote zero-hop: piso de chamada"),
        ("ffi_single_call_sample_ms", "Chamadas FFI unitárias (mesmos pares)"),
    ]
    x = np.arange(len(datasets), dtype=float)
    width = .24
    fig, ax = plt.subplots(figsize=(max(9, 2.4 * len(datasets)), 5.8), constrained_layout=True)
    colors = ("#EE6677", "#4477AA", "#CCBB44")
    for index, (field, label) in enumerate(series):
        values = [_median([row for row in batch_rows if row["dataset_id"] == dataset], field) for dataset in datasets]
        ax.bar(x + (index - 1) * width, [v or 0 for v in values], width, label=label, color=colors[index])
    ax.set_xticks(x, [DATASET_LABELS.get(dataset, dataset) for dataset in datasets])
    ax.set_ylabel("Tempo de uma amostra diagnóstica (ms)")
    ax.set_title("Custo FFI: lote real vs piso zero-hop e chamadas unitárias")
    ax.grid(axis="y", alpha=.22)
    ax.legend(frameon=False)
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, bbox_inches="tight"); plt.close(fig)
    return output


def _save_cache(rows, output):
    selected = [row for row in rows if row.get("mode") == "static"]
    datasets = list(dict.fromkeys(row["dataset_id"] for row in selected))
    methods = list(dict.fromkeys(row["method"] for row in selected))
    x = np.arange(len(datasets), dtype=float)
    width = .82 / max(1, len(methods))
    fig, ax = plt.subplots(figsize=(max(9, 2.25 * len(datasets)), 5.8), constrained_layout=True)
    plotted = False
    for index, method in enumerate(methods):
        values = []
        valid = []
        for dataset in datasets:
            sample = [row for row in selected if row["dataset_id"] == dataset and row["method"] == method]
            value = _median(sample, "cache_two_pass_benefit_pct")
            values.append(value or 0)
            valid.append(value is not None)
        if any(valid):
            ax.bar(x + (index - (len(methods) - 1) / 2) * width, values, width,
                   label=LABELS.get(method, method), color=COLORS.get(method, "#777777"))
            plotted = True
    ax.axhline(0, color="#333333", linewidth=.8)
    ax.set_xticks(x, [DATASET_LABELS.get(dataset, dataset) for dataset in datasets])
    ax.set_ylabel("Economia de tempo em duas passagens (%)")
    ax.set_title("Cache de consultas repetidas: duas passagens cacheadas vs. sem cache")
    ax.grid(axis="y", alpha=.22)
    if plotted:
        ax.legend(frameon=False, ncols=2)
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, bbox_inches="tight"); plt.close(fig)
    return output


def _save_temporal(summary_path, output):
    summary_path = Path(summary_path)
    if not summary_path.exists():
        return None
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    measures = summary["measurements"]
    checkpoints = summary["checkpoints"]
    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(12, 5.4), constrained_layout=True)
    memory_values = [measures["log_plus_current_graph_bytes_estimate"] / 1e6,
                     measures["materialized_snapshots_graph_bytes_estimate"] / 1e6]
    ax0.bar(["Log + estado atual", f"{len(checkpoints)} snapshots"], memory_values,
            color=["#228833", "#EE6677"])
    ax0.set_ylabel("Heap estimado (MB, decimal)")
    ax0.set_title("Memória retida estimada")
    ax0.grid(axis="y", alpha=.22)
    total_events = max(1, measures["event_count"])
    fractions = [row["events_in_state"] / total_events * 100 for row in checkpoints]
    times = [row["reconstruction_ms"] for row in checkpoints]
    ax1.plot(fractions, times, marker="o", color="#4477AA", linewidth=2)
    ax1.set_xlabel("Eventos replayados até o checkpoint (%)")
    ax1.set_ylabel("Tempo para reconstruir estado (ms)")
    ax1.set_title("Latência histórica sem snapshots persistentes")
    ax1.grid(alpha=.22)
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, bbox_inches="tight"); plt.close(fig)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default="results/phase5/real_data/runs.csv")
    parser.add_argument("--temporal", default="results/phase5/temporal_history/summary.json")
    parser.add_argument("--out-dir", default="results/phase5/plots")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    runs_path = Path(args.runs); runs_path = runs_path if runs_path.is_absolute() else root / runs_path
    temporal_path = Path(args.temporal); temporal_path = temporal_path if temporal_path.is_absolute() else root / temporal_path
    out_dir = Path(args.out_dir); out_dir = out_dir if out_dir.is_absolute() else root / out_dir
    rows = _read_csv(runs_path)
    generated = []
    for mode in ("static", "dynamic"):
        result = _save_bars(
            rows, mode, "batch_mean_ms_per_pair",
            f"SNAP real — latência média de consulta por par ({mode})",
            "Milissegundos por par", out_dir / f"real_query_per_pair_{mode}.png", log=True,
        )
        if result: generated.append(str(result))
        result = _save_bars(
            rows, mode, "workload_wall_ms",
            f"SNAP real — build + updates + consultas ({mode})",
            "Milissegundos por workload (build + updates + consultas; parsing excluído)", out_dir / f"real_workload_{mode}.png", log=True,
        )
        if result: generated.append(str(result))
        result = _save_bars(
            rows, mode, "rss_delta_after_build_bytes",
            f"SNAP real — incremento de RSS após construção ({mode})",
            "Bytes", out_dir / f"real_rss_{mode}.png", log=True,
        )
        if result: generated.append(str(result))
    for result in (_save_ffi(rows, out_dir / "ffi_decomposition.png"),
                   _save_cache(rows, out_dir / "query_cache_tradeoff.png"),
                   _save_temporal(temporal_path, out_dir / "temporal_history_tradeoff.png")):
        if result: generated.append(str(result))
    print(json.dumps({"generated": generated}, indent=2))


if __name__ == "__main__":
    main()
