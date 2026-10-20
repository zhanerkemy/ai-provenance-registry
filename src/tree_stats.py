"""Summarise the downloaded model family tree: how much of it can actually go on-chain?

Usage (from the repository root):
    python src/tree_stats.py
    python src/tree_stats.py --tree data/hf_tree.csv --out data/results/tree_stats.json

This answers the "real data" half of our research question before any gas is spent:
of all the models in a real family tree, how many have weight hashes, declare their
training data, have a single parent, and can therefore be registered by our contracts?
"""

from __future__ import annotations
import argparse
import json
from collections import Counter
from pathlib import Path

from hf_lineage import Node, plan_registrations, read_tree_csv


def share(part: int, whole: int) -> float:
    """Fraction rounded to 4 decimals; 0.0 if there is nothing to divide by."""
    return round(part / whole, 4) if whole else 0.0


def tree_stats(nodes: list[Node]) -> dict:
    n = len(nodes)
    plan, excluded = plan_registrations(nodes)
    children = Counter(node.parent_id for node in nodes if node.parent_id)

    return {
        "n_models": n,
        "max_depth": max((node.depth for node in nodes), default=0),
        "models_per_depth": dict(sorted(Counter(node.depth for node in nodes).items())),
        "models_per_relation": dict(Counter(node.relation for node in nodes).most_common()),
        "models_per_status": dict(Counter(node.status for node in nodes).most_common()),
        "share_with_weights_hash": share(sum(1 for x in nodes if x.weights_hash), n),
        "share_declaring_datasets": share(sum(1 for x in nodes if x.datasets), n),
        "mean_children_of_parents": round(sum(children.values()) / len(children), 2)
        if children else 0.0,
        "n_registrable": len(plan),
        "share_registrable": share(len(plan), n),
        "excluded_by_reason": dict(Counter(excluded.values()).most_common()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Statistics of a model family tree CSV.")
    parser.add_argument("--tree", type=Path, default=Path("data/hf_tree.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/results/tree_stats.json"))
    args = parser.parse_args()

    stats = tree_stats(read_tree_csv(args.tree))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
