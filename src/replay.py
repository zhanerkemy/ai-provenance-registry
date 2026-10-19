"""Replay the model tree on a local chain under each registry design and record the gas.

Run from the repo root (start `anvil` and run `forge build` first):
    python src/replay.py
    python src/replay.py --tree data/hf_tree.csv --batch-sizes 1 8 32 128

Each design gets a fresh contract and the same models in the same order:
    storage - ModelRegistry, one tx per model, record saved in storage
    event   - EventRegistry, one tx per model, record only in the event log
    merkle  - MerkleRegistry, one tx per batch of k models, only the root saved

Writes data/results/gas.csv (one row per model per design) and
data/results/run_meta.json (chain id, blocks, compiler, input file hash, skipped models).
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from chain import compiler_version, connect, deploy, send
from hash_file import hash_file
from hf_lineage import Node, plan_registrations, read_tree_csv
from merkle_tree import ZERO32, MerkleTree, leaf_hash, to_bytes32

GAS_COLUMNS = ["design", "batch_size", "batch_index", "model_id", "depth", "uri_bytes",
               "tx_gas", "gas_per_model", "verify_gas"]


def replay_per_model(w3, contract_name: str, design: str, plan) -> list[dict]:
    """Storage and event designs: one registerModel transaction per model."""
    registry, _ = deploy(w3, contract_name)
    onchain_id: dict[str, int] = {}
    rows = []
    for node, parent in plan:
        parent_id = onchain_id[parent] if parent else 0
        receipt = send(w3, registry.functions.registerModel(
            to_bytes32(node.weights_hash), to_bytes32(node.data_ref_hash), parent_id, node.uri))
        event = registry.events.ModelRegistered().process_receipt(receipt)[0]
        onchain_id[node.model_id] = event["args"]["id"]
        rows.append(_row(design, 1, len(rows), node, receipt["gasUsed"], receipt["gasUsed"]))

    if design == "storage" and plan:  # cost for another contract to verify one model
        first = plan[0][0]
        rows[0]["verify_gas"] = registry.functions.verifyWeights(
            1, to_bytes32(first.weights_hash)).estimate_gas()
    return rows


def replay_merkle(w3, plan, batch_size: int) -> list[dict]:
    """Merkle design: one anchorBatch transaction per `batch_size` models."""
    registry, _ = deploy(w3, "MerkleRegistry")
    weights_of = {node.model_id: node.weights_hash for node, _ in plan}
    rows = []
    for b, start in enumerate(range(0, len(plan), batch_size)):
        chunk = plan[start:start + batch_size]
        records = [(to_bytes32(n.weights_hash), to_bytes32(n.data_ref_hash),
                    to_bytes32(weights_of[p]) if p else ZERO32, n.uri) for n, p in chunk]
        tree = MerkleTree([leaf_hash(*r) for r in records])

        receipt = send(w3, registry.functions.anchorBatch(tree.root, len(chunk), f"batch-{b + 1}"))
        batch_id = b + 1

        # Correctness check on-chain: the first record of every batch must verify.
        args = (batch_id, *records[0], tree.proof(0))
        if not registry.functions.verifyRecord(*args).call():
            raise AssertionError(f"batch {batch_id}: proof did not verify on-chain")
        verify_gas = registry.functions.verifyRecord(*args).estimate_gas()

        per_model = receipt["gasUsed"] / len(chunk)
        for i, (node, _) in enumerate(chunk):
            rows.append(_row("merkle", batch_size, b, node, receipt["gasUsed"] if i == 0 else 0,
                             per_model, verify_gas if i == 0 else ""))
    return rows


def _row(design, batch_size, batch_index, node: Node, tx_gas, gas_per_model, verify_gas=""):
    return {
        "design": design,
        "batch_size": batch_size,
        "batch_index": batch_index,
        "model_id": node.model_id,
        "depth": node.depth,
        "uri_bytes": len(node.uri.encode("utf-8")),
        "tx_gas": tx_gas,  # whole transaction; for merkle only on the batch's first row
        "gas_per_model": round(gas_per_model, 1),
        "verify_gas": verify_gas,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a model tree on-chain and record gas.")
    parser.add_argument("--tree", type=Path, default=Path("data/hf_tree.csv"))
    parser.add_argument("--rpc", default="http://127.0.0.1:8545")
    parser.add_argument("--designs", nargs="+", default=["storage", "event", "merkle"],
                        choices=["storage", "event", "merkle"])
    parser.add_argument("--batch-sizes", nargs="+", type=int, default=[1, 8, 32, 128])
    parser.add_argument("--out", type=Path, default=Path("data/results/gas.csv"))
    args = parser.parse_args()

    nodes = read_tree_csv(args.tree)
    plan, excluded = plan_registrations(nodes)
    print(f"{len(nodes)} models in tree, {len(plan)} registrable, {len(excluded)} left out")

    w3 = connect(args.rpc)
    first_block = w3.eth.block_number + 1
    rows: list[dict] = []
    if "storage" in args.designs:
        rows += replay_per_model(w3, "ModelRegistry", "storage", plan)
        print("storage done")
    if "event" in args.designs:
        rows += replay_per_model(w3, "EventRegistry", "event", plan)
        print("event done")
    if "merkle" in args.designs:
        for k in args.batch_sizes:
            rows += replay_merkle(w3, plan, k)
            print(f"merkle k={k} done")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=GAS_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    reasons: dict[str, int] = {}
    for reason in excluded.values():
        reasons[reason] = reasons.get(reason, 0) + 1
    meta = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chain_id": w3.eth.chain_id,
        "rpc": args.rpc,
        "block_range": [first_block, w3.eth.block_number],
        "solc": compiler_version("ModelRegistry"),
        "tree_file": str(args.tree),
        "tree_file_sha256": hash_file(args.tree),
        "designs": args.designs,
        "batch_sizes": args.batch_sizes,
        "n_models_in_tree": len(nodes),
        "n_registered": len(plan),
        "excluded_by_reason": reasons,
    }
    meta_path = args.out.with_name("run_meta.json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} rows to {args.out} and run details to {meta_path}")


if __name__ == "__main__":
    main()
