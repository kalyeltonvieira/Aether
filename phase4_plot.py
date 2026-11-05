#!/usr/bin/env python3
"""Create phase-4 latency/memory plots from phase4_bench.py summary.json."""
import argparse
import json
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

LABELS = {
    "python_current": "Python sets",
    "python_optimized": "Python compact",
    "rust_ffi": "Rust FFI",
    "legacy_controller": "Controlador legado",
    "new_policy": "Política nova",
    "python_csr": "Python CSR",
    "python_rebuild": "Rebuild compact",
}
COLORS = {
    "python_current": "#52677d", "python_optimized": "#2d8a78", "rust_ffi": "#a64f55",
    "legacy_controller": "#d28d38", "new_policy": "#775da6", "python_csr": "#5696b0",
    "python_rebuild": "#986c45",
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--summary", default="results/phase4/final/summary.json")
    p.add_argument("--out-dir", default="results/phase4")
    args = p.parse_args()
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    groups = summary["summary"]
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)

    candidates = [("1000|churn", "1k · churn"), ("10000|churn", "10k · churn"),
                  ("100000|churn", "100k · churn"), ("100000|prolonged", "100k · prolongada")]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for ax, (key, title) in zip(axes.flat, candidates):
        data = groups.get(key, {})
        methods = [m for m in LABELS if m in data and m != "python_csr"]
        if not methods:
            ax.set_visible(False); continue
        values = [data[m]["e2e_wall_ms_including_worker_startup"] for m in methods]
        bars = ax.bar(range(len(methods)), values, color=[COLORS[m] for m in methods])
        ax.bar_label(bars, fmt="%.1f", fontsize=8, padding=2)
        ax.set_xticks(range(len(methods)), [LABELS[m] for m in methods], rotation=22, ha="right")
        ax.set_ylabel("ms, mediana")
        ax.set_title(title)
        ax.grid(axis="y", alpha=.2)
    fig.suptitle("Aether Fase 4 — ponta a ponta (inclui startup do worker; exclui oracle)", fontsize=14, weight="bold")
    fig.tight_layout(rect=(0, 0, 1, .95))
    latency_path = out / "phase4_latency.png"
    fig.savefig(latency_path, dpi=180, bbox_inches="tight"); plt.close(fig)

    sizes = [1000, 10000, 100000, 500000, 1000000]
    methods = ["python_current", "python_optimized", "rust_ffi", "legacy_controller", "new_policy", "python_rebuild"]
    fig, (ax_heap, ax_rss) = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [1.1, 1]})
    width = .13; x = np.arange(len(sizes))
    for i, method in enumerate(methods):
        heap = []; rss = []; mask = []
        for n in sizes:
            d = groups.get(f"{n}|churn", {}).get(method)
            if d:
                heap.append(d["retained_graph_bytes_estimate"] / 1e6)
                rss.append(d["rss_delta_after_build_bytes"] / 1e6); mask.append(True)
            else:
                heap.append(np.nan); rss.append(np.nan); mask.append(False)
        ax_heap.bar(x + (i - 2.5) * width, heap, width, label=LABELS[method], color=COLORS[method])
        ax_rss.bar(x + (i - 2.5) * width, rss, width, label=LABELS[method], color=COLORS[method])
    for ax in (ax_heap, ax_rss):
        ax.set_xticks(x, [f"{n:,}".replace(",", " ") for n in sizes])
        ax.set_yscale("log"); ax.grid(axis="y", which="both", alpha=.2)
    ax_heap.set_title("Heap retido estimado · MB"); ax_heap.set_ylabel("MB, escala log")
    ax_rss.set_title("Delta RSS após construção · MB"); ax_rss.set_ylabel("MB, escala log")
    ax_heap.legend(fontsize=8, loc="upper left")
    fig.suptitle("Memória do grafo por escala (churn; valores medidos/estimados conforme a métrica)", fontsize=13, weight="bold")
    fig.tight_layout(rect=(0, 0, 1, .94))
    memory_path = out / "phase4_memory.png"
    fig.savefig(memory_path, dpi=180, bbox_inches="tight"); plt.close(fig)

    qh = groups.get("1000|query_heavy", {})
    if qh:
        methods_q = [m for m in LABELS if m in qh]
        fig, (ax_time, ax_mem) = plt.subplots(1, 2, figsize=(12, 5.5))
        for ax, metric, title, units in ((ax_time, "workload_wall_ms", "Carga completa estática", "ms"),
                                         (ax_mem, "retained_graph_bytes_estimate", "Estrutura retida", "bytes")):
            vals = [qh[m][metric] for m in methods_q]
            bars = ax.bar(range(len(methods_q)), vals, color=[COLORS[m] for m in methods_q])
            ax.bar_label(bars, fmt="%.2g", fontsize=8, padding=2)
            ax.set_xticks(range(len(methods_q)), [LABELS[m] for m in methods_q], rotation=22, ha="right")
            ax.set_ylabel(units); ax.set_title(title); ax.grid(axis="y", alpha=.2)
        fig.suptitle("1k nós · 3.000 consultas · Python CSR economiza RAM, mas pode custar latência", fontsize=12, weight="bold")
        fig.tight_layout(rect=(0, 0, 1, .92))
        qh_path = out / "phase4_queryheavy.png"
        fig.savefig(qh_path, dpi=180, bbox_inches="tight"); plt.close(fig)
    else:
        qh_path = None
    print(json.dumps({"latency": str(latency_path), "memory": str(memory_path),
                      "query_heavy": str(qh_path) if qh_path else None}, indent=2))


if __name__ == "__main__":
    main()
