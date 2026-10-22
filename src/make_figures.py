"""Draw the paper's figures from the data files. Never edit a figure by hand (Stage 4).

Usage (from the repository root):
    python src/make_figures.py

Reads   data/hf_tree.csv
Writes  figures/tree_by_depth.png        models at each depth, split by relation
        figures/tree_registrability.png  how many models can go on-chain, and why not

Gas figures are added here once data/results/gas.csv exists (week 2).
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to files, no window needed
import matplotlib.pyplot as plt  # noqa: E402

from hf_lineage import plan_registrations, read_tree_csv  # noqa: E402

# Colours: a validated colour-blind-safe palette. Each relation keeps the same colour
# in every figure. Text stays dark grey, never the series colour.
RELATION_COLORS = {
    "base": "#2a78d6",
    "finetune": "#eb6834",
    "adapter": "#1baf7a",
    "quantized": "#eda100",
    "merge": "#e87ba4",
}
REGISTRABLE = "#2a78d6"
EXCLUDED = "#a3a29c"
TEXT = "#0b0b0b"
TEXT_MUTED = "#52514e"
GRID = "#e4e3df"
SURFACE = "#ffffff"

REASON_LABELS = {
    "registrable": "Registrable",
    "multi_parent": "Several parents (merge)",
    "no_weight_files": "No weight hashes on Hub",
    "error": "Unreadable (private/removed)",
    "ancestor_not_registered": "Ancestor not registrable",
    "duplicate_weights": "Exact re-upload of another model",
}


def style_axes(ax) -> None:
    """Recessive axes: no box, light horizontal grid behind the bars."""
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(TEXT_MUTED)
    ax.tick_params(colors=TEXT_MUTED, length=0, labelsize=8)
    ax.set_axisbelow(True)


def plot_depth(nodes, out: Path) -> None:
    depths = sorted({n.depth for n in nodes})
    counts = Counter((n.depth, n.relation) for n in nodes)
    relations = [r for r in RELATION_COLORS if any(n.relation == r for n in nodes)]

    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=200)
    bottom = [0] * len(depths)
    for rel in relations:
        heights = [counts[(d, rel)] for d in depths]
        ax.bar(depths, heights, bottom=bottom, width=0.6, color=RELATION_COLORS[rel],
               edgecolor=SURFACE, linewidth=1.5, label=rel)
        bottom = [b + h for b, h in zip(bottom, heights)]
    for d, total in zip(depths, bottom):  # total on top of each bar
        ax.annotate(f"{total}", (d, total), xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=8, color=TEXT)

    style_axes(ax)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_xticks(depths)
    ax.set_xlabel("Depth in the family tree (0 = base model)", color=TEXT_MUTED, fontsize=9)
    ax.set_ylabel("Number of models", color=TEXT_MUTED, fontsize=9)
    ax.legend(title="Relation to parent", frameon=False, fontsize=8, title_fontsize=8,
              labelcolor=TEXT)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def plot_registrability(nodes, out: Path) -> None:
    plan, excluded = plan_registrations(nodes)
    counts = Counter(excluded.values())
    rows = [("registrable", len(plan))] + sorted(counts.items(), key=lambda kv: -kv[1])
    labels = [REASON_LABELS.get(k, k) for k, _ in rows]
    values = [v for _, v in rows]
    colors = [REGISTRABLE if k == "registrable" else EXCLUDED for k, _ in rows]

    fig, ax = plt.subplots(figsize=(6.4, 0.45 * len(rows) + 1.0), dpi=200)
    y = list(range(len(rows)))[::-1]  # first row at the top
    ax.barh(y, values, height=0.6, color=colors, edgecolor=SURFACE, linewidth=1.5)
    total = len(nodes)
    for yi, v in zip(y, values):
        ax.annotate(f"{v}  ({v / total:.0%})", (v, yi), xytext=(4, 0),
                    textcoords="offset points", va="center", fontsize=8, color=TEXT)

    style_axes(ax)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_yticks(y, labels, color=TEXT, fontsize=8)
    ax.set_xlim(0, max(values) * 1.25)
    ax.set_xlabel(f"Number of models (of {total} in the tree)", color=TEXT_MUTED, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the paper's figures.")
    parser.add_argument("--tree", type=Path, default=Path("data/hf_tree.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("figures"))
    args = parser.parse_args()

    nodes = read_tree_csv(args.tree)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    plot_depth(nodes, args.out_dir / "tree_by_depth.png")
    plot_registrability(nodes, args.out_dir / "tree_registrability.png")
    print(f"Figures written to {args.out_dir}/")


if __name__ == "__main__":
    main()
