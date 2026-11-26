"""Single-column versions of the six figures, for the paper's two-column IEEE layout.

Same data files, selection rules (plan_registrations), colours and encodings as
src/make_figures.py, whose helpers it imports. Only the layout differs: a 3.5-inch
canvas (one IEEE column), 7-8 pt text at print size, and shorter axis labels (the detail
moves to the captions). The verification figure stacks its two panels vertically.

Usage (from the repository root):
    python src/make_column_figures.py

Reads   data/hf_tree.csv and data/results/{gas.csv, gas_model.json, verify_gas.csv,
        chain_check.json}
Writes  figures/column/{tree_by_depth, tree_registrability, gas_per_model,
        storage_gas_breakdown, verify_gas, sepolia_vs_anvil}.png
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402

W = 3.5
DPI = 300


def main() -> None:
    p = argparse.ArgumentParser(description="Single-column figures for the paper.")
    p.add_argument("--data", type=Path, default=Path("data"))
    p.add_argument("--results", type=Path, default=Path("data/results"))
    p.add_argument("--out-dir", type=Path, default=Path("figures/column"))
    a = p.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import make_figures as mf
    from hf_lineage import plan_registrations, read_tree_csv

    a.out = a.out_dir
    a.out.mkdir(parents=True, exist_ok=True)
    nodes = read_tree_csv(a.data / "hf_tree.csv")
    res = a.results
    gas = mf.read_csv(res / "gas.csv")
    fmt = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}")

    def style(ax):
        mf.style_axes(ax)
        ax.tick_params(labelsize=7)

    # ---- registrability -------------------------------------------------------------
    plan, excluded = plan_registrations(nodes)
    counts = Counter(excluded.values())
    rows = [("registrable", len(plan))] + sorted(counts.items(), key=lambda kv: -kv[1])
    short = {"registrable": "Registrable", "ancestor_not_registered": "Ancestor excluded",
             "multi_parent": "Several parents", "duplicate_weights": "Exact re-upload",
             "no_weight_files": "No weight hashes", "error": "Unreadable"}
    fig, ax = plt.subplots(figsize=(W, 1.75), dpi=DPI)
    y = list(range(len(rows)))[::-1]
    vals = [v for _, v in rows]
    ax.barh(y, vals, height=0.6, edgecolor=mf.SURFACE, linewidth=1,
            color=[mf.REGISTRABLE if k == "registrable" else mf.EXCLUDED for k, _ in rows])
    for yi, v in zip(y, vals):
        ax.annotate(f"{v:,} ({v / len(nodes):.0%})", (v, yi), xytext=(3, 0),
                    textcoords="offset points", va="center", fontsize=7, color=mf.TEXT)
    style(ax)
    ax.xaxis.grid(True, color=mf.GRID, linewidth=0.6)
    ax.set_yticks(y, [short[k] for k, _ in rows], color=mf.TEXT, fontsize=7)
    ax.set_xlim(0, max(vals) * 1.35)
    ax.set_xlabel(f"Models (of {len(nodes):,} in the tree)", color=mf.TEXT_MUTED, fontsize=7)
    fig.tight_layout(pad=0.3)
    fig.savefig(a.out / "tree_registrability.png", facecolor=mf.SURFACE)
    plt.close(fig)

    # ---- gas per model --------------------------------------------------------------
    groups = defaultdict(list)
    for r in gas:
        groups[(r["design"], int(r["batch_size"]))].append(float(r["gas_per_model"]))
    order = [("storage", 1), ("event", 1)] + sorted(k for k in groups if k[0] == "merkle")
    means = [sum(groups[k]) / len(groups[k]) for k in order]
    lows = [min(groups[k]) for k in order]
    highs = [max(groups[k]) for k in order]
    fig, ax = plt.subplots(figsize=(W, 2.0), dpi=DPI)
    y = list(range(len(order)))[::-1]
    ax.hlines(y, lows, highs, color=mf.TEXT_MUTED, linewidth=1, zorder=2)
    ax.scatter(means, y, s=28, color=[mf.DESIGN_COLORS[d] for d, _ in order],
               edgecolor=mf.SURFACE, linewidth=1, zorder=3)
    for yi, m, h in zip(y, means, highs):
        ax.annotate(f"{m:,.0f}", (h, yi), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=7, color=mf.TEXT)
    style(ax)
    ax.set_xscale("log")
    ax.xaxis.grid(True, which="major", color=mf.GRID, linewidth=0.6)
    ax.xaxis.set_major_formatter(fmt)
    ax.set_xlim(min(lows) / 2, max(highs) * 6)
    ax.set_ylim(-0.6, len(order) - 0.4)
    ax.set_yticks(y, [mf.design_label(d, k) for d, k in order], color=mf.TEXT, fontsize=7)
    ax.set_xlabel("Gas per registered model (log scale)", color=mf.TEXT_MUTED, fontsize=7)
    fig.tight_layout(pad=0.3)
    fig.savefig(a.out / "gas_per_model.png", facecolor=mf.SURFACE)
    plt.close(fig)

    # ---- storage breakdown ----------------------------------------------------------
    model = json.loads((res / "gas_model.json").read_text(encoding="utf-8"))
    coef = model["storage"]["coefficients"]
    has_data = {n.model_id: bool(n.data_ref_hash) for n in nodes}
    srows = [r for r in gas if r["design"] == "storage"]
    color = mf.DESIGN_COLORS["storage"]
    fig, ax = plt.subplots(figsize=(W, 2.2), dpi=DPI)
    for declared, face, label in ((True, color, "data hash declared"),
                                  (False, "none", "no data hash")):
        pts = [r for r in srows if has_data[r["model_id"]] == declared]
        ax.scatter([int(r["uri_bytes"]) for r in pts], [float(r["gas_per_model"]) / 1000 for r in pts],
                   s=7, facecolors=face, edgecolors=color, linewidths=0.6, alpha=0.6,
                   label=f"{label} ({len(pts)})", zorder=3)
        xs = range(min(int(r["uri_bytes"]) for r in pts), max(int(r["uri_bytes"]) for r in pts) + 1)
        ys = [(coef["intercept"] + coef["uri_words"] * math.ceil(x / 32)
               + coef["has_data"] * declared) / 1000 for x in xs]
        ax.plot(list(xs), ys, color=mf.TEXT_MUTED, linewidth=0.8,
                linestyle="-" if declared else "--", zorder=2)
    style(ax)
    ax.yaxis.grid(True, color=mf.GRID, linewidth=0.6)
    ax.set_xlabel("URI length (bytes)", color=mf.TEXT_MUTED, fontsize=7)
    ax.set_ylabel("Storage registration gas (thousands)", color=mf.TEXT_MUTED, fontsize=7)
    ax.legend(frameon=False, fontsize=6.5, loc="lower right", labelcolor=mf.TEXT)
    fig.tight_layout(pad=0.3)
    fig.savefig(a.out / "storage_gas_breakdown.png", facecolor=mf.SURFACE)
    plt.close(fig)

    # ---- Sepolia vs Anvil -----------------------------------------------------------
    check = json.loads((res / "chain_check.json").read_text(encoding="utf-8"))
    rows = check["by_design"]
    fig, ax = plt.subplots(figsize=(W, 1.75), dpi=DPI)
    y = list(range(len(rows)))[::-1]
    for yi, r in zip(y, rows):
        av, sv = r["anvil_mean_gas_per_model"], r["sepolia_mean_gas_per_model"]
        c = mf.DESIGN_COLORS[r["design"]]
        ax.hlines(yi, av, sv, color=c, linewidth=1.6, alpha=0.5, zorder=2)
        ax.scatter([av], [yi], s=28, facecolor=mf.SURFACE, edgecolor=c, linewidth=1.3, zorder=3)
        ax.scatter([sv], [yi], s=28, color=c, edgecolor=mf.SURFACE, linewidth=1, zorder=3)
        ax.annotate(f"×{r['ratio']:.2f}", (sv, yi), xytext=(5, 0), textcoords="offset points",
                    va="center", fontsize=7, color=mf.TEXT)
    style(ax)
    ax.set_xscale("log")
    ax.xaxis.grid(True, which="major", color=mf.GRID, linewidth=0.6)
    ax.xaxis.set_major_formatter(fmt)
    lo = min(r["anvil_mean_gas_per_model"] for r in rows)
    hi = max(r["sepolia_mean_gas_per_model"] for r in rows)
    ax.set_xlim(lo / 2, hi * 4)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_yticks(y, [mf.design_label(r["design"], r["batch_size"]) for r in rows],
                  color=mf.TEXT, fontsize=7)
    ax.scatter([], [], s=20, facecolor=mf.SURFACE, edgecolor=mf.TEXT_MUTED, label="Anvil")
    ax.scatter([], [], s=20, color=mf.TEXT_MUTED, label="Sepolia")
    ax.legend(loc="upper left", fontsize=6.5, frameon=False, labelcolor=mf.TEXT_MUTED,
              ncol=2, bbox_to_anchor=(0.0, 1.12))
    ax.set_xlabel("Mean gas per model, same 24 models (log scale)", color=mf.TEXT_MUTED, fontsize=7)
    fig.tight_layout(pad=0.3)
    fig.savefig(a.out / "sepolia_vs_anvil.png", facecolor=mf.SURFACE)
    plt.close(fig)
    # ---- verification: (a) one record, (b) whole lineage, stacked ------------------
    ver = mf.read_csv(res / "verify_gas.csv")
    vg = defaultdict(list)
    for r in ver:
        vg[(r["design"], int(r["batch_size"]))].append(r)
    order = [("storage", 1)] + sorted(k for k in vg if k[0] == "merkle")
    fig, (ax_a, ax_b) = plt.subplots(2, 1, figsize=(W, 3.6), dpi=DPI,
                                     gridspec_kw={"height_ratios": [1, 1.15]})
    vm = [sum(int(r["verify_gas"]) for r in vg[k]) / len(vg[k]) for k in order]
    pm = [sum(int(r["proof_len"]) for r in vg[k]) / len(vg[k]) for k in order]
    x = list(range(len(order)))
    ax_a.bar(x, vm, width=0.6, color=[mf.DESIGN_COLORS[d] for d, _ in order],
             edgecolor=mf.SURFACE, linewidth=1)
    for xi, m in zip(x, vm):
        ax_a.annotate(f"{m:,.0f}", (xi, m), xytext=(0, 2), textcoords="offset points",
                      ha="center", fontsize=6.5, color=mf.TEXT)
    ax_a.set_xticks(x, ["Storage"] + [f"k={k}\n({p:.1f})" for (_, k), p in
                                      zip(order[1:], pm[1:])], fontsize=6.5, color=mf.TEXT)
    ax_a.set_ylabel("Gas, one record", color=mf.TEXT_MUTED, fontsize=7)
    ax_a.set_title("(a) One record; Merkle bars show k (mean proof hashes)", loc="left",
                   fontsize=7, color=mf.TEXT)
    for design, k, ls, mk in [("storage", 1, "-", "o"), ("merkle", 8, "--", "s"),
                              ("merkle", 128, "-", "^")]:
        by_len = defaultdict(list)
        for r in vg[(design, k)]:
            by_len[int(r["lineage_len"])].append(int(r["lineage_gas"]))
        xs = sorted(by_len)
        ys = [sum(by_len[n]) / len(by_len[n]) for n in xs]
        ax_b.plot(xs, ys, linestyle=ls, marker=mk, markersize=3.5, linewidth=1.4,
                  color=mf.DESIGN_COLORS[design], markeredgecolor=mf.SURFACE)
        ax_b.annotate(mf.design_label(design, k), (xs[-1], ys[-1]), xytext=(4, 0),
                      textcoords="offset points", va="center", fontsize=6.5, color=mf.TEXT)
    ax_b.set_xlim(0.7, 6.6)
    ax_b.set_xticks(range(1, 6))
    ax_b.set_xlabel("Generations checked (model, parent, ..., base)", color=mf.TEXT_MUTED,
                    fontsize=7)
    ax_b.set_ylabel("Gas, whole lineage", color=mf.TEXT_MUTED, fontsize=7)
    ax_b.set_title("(b) Whole lineage", loc="left", fontsize=7, color=mf.TEXT)
    for ax in (ax_a, ax_b):
        style(ax)
        ax.yaxis.grid(True, color=mf.GRID, linewidth=0.6)
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_formatter(fmt)
    ax_a.set_ylim(0, max(vm) * 1.18)
    fig.tight_layout(pad=0.3, h_pad=0.6)
    fig.savefig(a.out / "verify_gas.png", facecolor=mf.SURFACE)
    plt.close(fig)
    # ---- tree by depth ---------------------------------------------------------------
    depths = sorted({n.depth for n in nodes})
    cnt = Counter((n.depth, n.relation) for n in nodes)
    rels = [r for r in mf.RELATION_COLORS if any(n.relation == r for n in nodes)]
    fig, ax = plt.subplots(figsize=(W, 1.9), dpi=DPI)
    bottom = [0] * len(depths)
    for rel in rels:
        hs = [cnt[(d, rel)] for d in depths]
        ax.bar(depths, hs, bottom=bottom, width=0.62, color=mf.RELATION_COLORS[rel],
               edgecolor=mf.SURFACE, linewidth=0.8, label=rel)
        bottom = [b + h for b, h in zip(bottom, hs)]
    for d, tot in zip(depths, bottom):
        ax.annotate(f"{tot:,}", (d, tot), xytext=(0, 2), textcoords="offset points",
                    ha="center", fontsize=6.5, color=mf.TEXT)
    style(ax)
    ax.yaxis.grid(True, color=mf.GRID, linewidth=0.6)
    ax.set_xticks(depths)
    ax.set_ylim(0, max(bottom) * 1.15)
    ax.set_xlabel("Depth in the family tree (0 = base model)", color=mf.TEXT_MUTED, fontsize=7)
    ax.set_ylabel("Models", color=mf.TEXT_MUTED, fontsize=7)
    ax.legend(frameon=False, fontsize=6.5, loc="upper right", labelcolor=mf.TEXT, ncol=1)
    fig.tight_layout(pad=0.3)
    fig.savefig(a.out / "tree_by_depth.png", facecolor=mf.SURFACE)
    plt.close(fig)

    print(f"Single-column figures written to {a.out}/")


if __name__ == "__main__":
    main()
