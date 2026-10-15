"""Download one real model family tree from the Hugging Face Hub into a CSV file.

Usage (from the repository root):
    python src/hf_lineage.py --base HuggingFaceTB/SmolLM2-135M
    python src/hf_lineage.py --base HuggingFaceTB/SmolLM2-135M --max-models 300 --max-depth 4

Output:
    data/hf_tree.csv        one row per model, parents always before their children
    data/hf_tree_meta.json  when and how the tree was pulled (Stage 4: record the data date)

How the tree is found
---------------------
When someone uploads a fine-tune to the Hub they can declare its base model. The Hub
turns that into a tag such as "base_model:finetune:HuggingFaceTB/SmolLM2-135M". The
relation part is one of: finetune, adapter (e.g. LoRA), quantized (smaller-precision
copy) or merge (combination of several models). Starting from the base model we ask
the Hub for every model tagged as its child, then their children, and so on
(breadth-first), until --max-models or --max-depth is reached.

What we record for each model
-----------------------------
weights_hash   SHA-256 manifest of the model's weight files. The Hub publishes the
               SHA-256 of every large (LFS) file, so no weights are downloaded.
               Same scheme as `python src/hash_file.py <folder> --weights-only`.
data_ref_hash  SHA-256 of the *names* of the training datasets declared in the model
               card. This is a reference, not a fingerprint of the data content: the
               Hub does not publish content hashes for datasets. (Limitation.)
status         ok               can be registered
               multi_parent     declares several base models (e.g. merges); our
                                contracts record exactly one parent
               no_weight_files  no weight files with a published SHA-256
               error            the Hub refused or failed the request (private, removed...)

Set HF_TOKEN in a .env file if you hit rate limits; it is optional.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
from collections import deque
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from hash_file import is_weight_file, manifest_hash

RELATIONS = ("finetune", "adapter", "quantized", "merge")


# --------------------------------------------------------------------------- data types


@dataclass
class ModelMeta:
    """What we need to know about one model page, as plain data (easy to fake in tests)."""

    model_id: str
    revision: str  # git commit hash of the repository on the Hub
    created_at: str  # ISO date, "" if unknown
    lfs_files: list[tuple[str, str]]  # (file path, SHA-256) for every large file
    datasets: list[str]  # training datasets declared in the model card
    declared_parents: list[str]  # base models declared in the model card


@dataclass
class Node:
    """One row of data/hf_tree.csv."""

    model_id: str
    parent_id: str  # "" for the base model
    relation: str  # base | finetune | adapter | quantized | merge
    depth: int  # 0 for the base model
    revision: str
    created_at: str
    weights_hash: str  # "0x..." or ""
    data_ref_hash: str  # "0x..." or ""
    n_weight_files: int
    datasets: str  # dataset names joined with ";"
    n_declared_parents: int
    status: str  # ok | multi_parent | no_weight_files | error
    uri: str  # hf://<model_id>@<revision>


CSV_COLUMNS = [f.name for f in fields(Node)]


class Hub(Protocol):
    """Anything that can answer the two questions we ask the Hub."""

    def children(self, model_id: str, relation: str) -> list[str]: ...

    def meta(self, model_id: str) -> ModelMeta: ...


# --------------------------------------------------------------------------- the real Hub


def _as_list(value) -> list[str]:
    """Model cards store some fields as a string or a list; always return a list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


class HfHub:
    """Talks to huggingface.co through the official huggingface_hub library."""

    def __init__(self, token: str | None = None, pause: float = 0.2, list_limit: int = 1000):
        from huggingface_hub import HfApi  # imported here so tests do not need it

        self.api = HfApi(token=token)
        self.pause = pause  # seconds between requests, to stay polite to the Hub
        self.list_limit = list_limit  # max children fetched per (model, relation)

    def children(self, model_id: str, relation: str) -> list[str]:
        time.sleep(self.pause)
        tag = f"base_model:{relation}:{model_id}"
        return [m.id for m in self.api.list_models(filter=tag, limit=self.list_limit)]

    def meta(self, model_id: str) -> ModelMeta:
        time.sleep(self.pause)
        info = self.api.model_info(model_id, files_metadata=True)
        lfs_files = [(s.rfilename, s.lfs.sha256) for s in (info.siblings or []) if s.lfs]
        card = info.card_data
        return ModelMeta(
            model_id=model_id,
            revision=info.sha or "",
            created_at=info.created_at.isoformat() if info.created_at else "",
            lfs_files=lfs_files,
            datasets=_as_list(getattr(card, "datasets", None)) if card else [],
            declared_parents=_as_list(getattr(card, "base_model", None)) if card else [],
        )


# --------------------------------------------------------------------------- building the tree


def data_ref_hash(datasets: list[str]) -> str:
    """SHA-256 of the sorted, de-duplicated dataset names (one per line)."""
    names = sorted(set(datasets))
    return hashlib.sha256("".join(f"{n}\n" for n in names).encode("utf-8")).hexdigest()


def make_node(hub: Hub, model_id: str, parent_id: str, relation: str, depth: int) -> Node:
    """Fetch one model's metadata and turn it into a CSV row."""
    try:
        m = hub.meta(model_id)
    except Exception as exc:  # private, deleted, gated or network failure
        print(f"  ! could not read {model_id}: {type(exc).__name__}")
        return Node(model_id, parent_id, relation, depth, "", "", "", "", 0, "", 0, "error",
                    f"hf://{model_id}")

    weight_files = [(path, sha) for path, sha in m.lfs_files if is_weight_file(path)]
    weights_hash = "0x" + manifest_hash(weight_files) if weight_files else ""
    data_hash = "0x" + data_ref_hash(m.datasets) if m.datasets else ""

    if relation == "merge" or len(m.declared_parents) > 1:
        status = "multi_parent"
    elif not weight_files:
        status = "no_weight_files"
    else:
        status = "ok"

    uri = f"hf://{model_id}@{m.revision}" if m.revision else f"hf://{model_id}"
    return Node(
        model_id=model_id,
        parent_id=parent_id,
        relation=relation,
        depth=depth,
        revision=m.revision,
        created_at=m.created_at,
        weights_hash=weights_hash,
        data_ref_hash=data_hash,
        n_weight_files=len(weight_files),
        datasets=";".join(sorted(set(m.datasets))),
        n_declared_parents=len(m.declared_parents),
        status=status,
        uri=uri,
    )


def walk_tree(
    hub: Hub,
    base_id: str,
    relations: tuple[str, ...] = RELATIONS,
    max_models: int = 300,
    max_depth: int = 4,
) -> tuple[list[Node], dict]:
    """Breadth-first walk from the base model. Returns (nodes, info about the walk).

    Breadth-first means every parent is listed before its children, which is the order
    the contracts need (a parent must be registered before its child).
    """
    nodes: list[Node] = []
    seen = {base_id}
    queue = deque([(base_id, "", "base", 0)])
    list_errors = 0
    reached_twice = 0  # children listed under more than one parent

    while queue and len(nodes) < max_models:
        model_id, parent_id, relation, depth = queue.popleft()
        nodes.append(make_node(hub, model_id, parent_id, relation, depth))
        print(f"[{len(nodes):4d}] depth {depth} {relation:9s} {model_id}")
        if depth >= max_depth:
            continue
        for rel in relations:
            try:
                kids = sorted(hub.children(model_id, rel))  # sorted: same order every run
            except Exception as exc:
                print(f"  ! could not list {rel} children of {model_id}: {type(exc).__name__}")
                list_errors += 1
                continue
            for child in kids:
                if child in seen:
                    reached_twice += 1
                    continue
                seen.add(child)
                queue.append((child, model_id, rel, depth + 1))

    info = {
        "truncated": bool(queue),  # True if --max-models stopped the walk early
        "not_visited": len(queue),
        "list_errors": list_errors,
        "children_reached_twice": reached_twice,
    }
    return nodes, info


# --------------------------------------------------------------------------- reading and writing


def write_tree_csv(nodes: list[Node], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for n in nodes:
            writer.writerow(asdict(n))


def read_tree_csv(path: Path) -> list[Node]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [
        Node(**{**r, "depth": int(r["depth"]), "n_weight_files": int(r["n_weight_files"]),
                "n_declared_parents": int(r["n_declared_parents"])})
        for r in rows
    ]


def plan_registrations(nodes: list[Node]) -> tuple[list[tuple[Node, str]], dict[str, str]]:
    """Decide which models can go on-chain, and which earlier model is each one's parent.

    Used by src/tree_stats.py and src/replay.py so both count exactly the same models.
    Returns (plan, excluded):
      plan      list of (node, parent_model_id) in registration order; parent "" = base
      excluded  {model_id: reason} for every model left out

    Rules, applied in breadth-first order:
      * status must be "ok"
      * its parent must already be in the plan (otherwise "ancestor_not_registered")
      * if another model with identical weights is already in the plan, this one is an
        exact re-upload ("duplicate_weights"); its children attach to that first copy,
        because the same weights are the same model
    """
    stands_for: dict[str, str] = {}  # model_id -> model_id whose on-chain record it uses
    first_with_weights: dict[str, str] = {}  # weights_hash -> first model_id
    plan: list[tuple[Node, str]] = []
    excluded: dict[str, str] = {}

    for n in nodes:
        if n.status != "ok":
            excluded[n.model_id] = n.status
            continue
        parent = ""
        if n.parent_id:
            parent = stands_for.get(n.parent_id, "")
            if not parent:
                excluded[n.model_id] = "ancestor_not_registered"
                continue
        original = first_with_weights.get(n.weights_hash)
        if original:
            excluded[n.model_id] = "duplicate_weights"
            stands_for[n.model_id] = original
            continue
        first_with_weights[n.weights_hash] = n.model_id
        stands_for[n.model_id] = n.model_id
        plan.append((n, parent))

    return plan, excluded


def write_meta(path: Path, base: str, args: argparse.Namespace, nodes: list[Node], info: dict) -> None:
    import huggingface_hub

    meta = {
        "base_model": base,
        "pulled_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "max_models": args.max_models,
        "max_depth": args.max_depth,
        "relations": list(args.relations),
        "huggingface_hub_version": huggingface_hub.__version__,
        "n_models": len(nodes),
        **info,
    }
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download a model family tree from the Hub.")
    parser.add_argument("--base", required=True, help="base model id, e.g. org/model")
    parser.add_argument("--max-models", type=int, default=300)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--relations", nargs="+", default=list(RELATIONS), choices=RELATIONS)
    parser.add_argument("--out", type=Path, default=Path("data/hf_tree.csv"))
    args = parser.parse_args()

    try:  # optional: read HF_TOKEN from a .env file
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    hub = HfHub(token=os.getenv("HF_TOKEN"))
    nodes, info = walk_tree(hub, args.base, tuple(args.relations), args.max_models, args.max_depth)
    write_tree_csv(nodes, args.out)
    write_meta(args.out.with_name(args.out.stem + "_meta.json"), args.base, args, nodes, info)

    plan, excluded = plan_registrations(nodes)
    print(f"\n{len(nodes)} models written to {args.out}; {len(plan)} can be registered on-chain.")
    if info["truncated"]:
        print(f"Stopped at --max-models; {info['not_visited']} more models were not visited.")


if __name__ == "__main__":
    main()
