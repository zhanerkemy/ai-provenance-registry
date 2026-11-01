"""Measure what it costs ANOTHER CONTRACT to verify a model record, and a whole lineage,
under the storage and Merkle designs. Answers sub-question 3 of the measurement plan.

Usage (from the repository root, with `anvil` running and `forge build` done):
    python src/verify_gas.py
    python src/verify_gas.py --per-depth 5 --seed 435 --batch-sizes 1 8 32 128

Output:
    data/results/verify_gas.csv  one row per sampled model per design (and batch size)

How it works
------------
Verification gas does not depend on how many models are registered; it depends on the
model's depth (how many generations to read) and, for Merkle, on the batch size (how
long the proof is). So we do not need to register all 1,071 models again. We take a
random sample (fixed seed) of up to --per-depth models at every depth, add their
ancestors, and register only those, in the same order as src/replay.py.

Each check is sent through src/VerifyProbe.sol as an eth_call. That gives the gas of the
check itself, without the 21,000 base cost and call data cost that estimate_gas adds
(see docs/measurement_plan.md, "Why two verification numbers"). Every eth_call starts
cold, so each number is the cost of the first check in a transaction.

The event-only design does not appear: a contract cannot read event logs, so on-chain
verification is not possible there (src/audit_checks.py records that as a result).
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

from chain import connect, deploy, send
from hf_lineage import Node, plan_registrations, read_tree_csv
from merkle_tree import ZERO32, MerkleTree, leaf_hash, to_bytes32

COLUMNS = ["design", "batch_size", "model_id", "depth", "proof_len", "verify_gas",
           "lineage_len", "lineage_gas"]
# depth        depth in the Hugging Face tree
# lineage_len  generations on-chain (model, parent, ..., base); usually depth + 1


def sample_models(plan, per_depth: int, seed: int) -> list[str]:
    """Up to `per_depth` random registrable models at each depth, in plan order."""
    by_depth: dict[int, list[str]] = defaultdict(list)
    for node, _ in plan:
        by_depth[node.depth].append(node.model_id)
    rng = random.Random(seed)
    chosen = set()
    for depth in sorted(by_depth):
        ids = by_depth[depth]
        chosen.update(rng.sample(ids, min(per_depth, len(ids))))
    return [node.model_id for node, _ in plan if node.model_id in chosen]


def ancestors(model_id: str, parent_of: dict[str, str]) -> list[str]:
    """[model, parent, grandparent, ..., base] using the on-chain parents from the plan."""
    chain = [model_id]
    while parent_of[chain[-1]]:
        chain.append(parent_of[chain[-1]])
    return chain


def measure_storage(w3, probe, plan, sample, parent_of) -> list[dict]:
    """Register the sample and its ancestors in ModelRegistry; probe each sampled model."""
    registry, _ = deploy(w3, "ModelRegistry")
    needed = {a for m in sample for a in ancestors(m, parent_of)}
    onchain_id: dict[str, int] = {}
    node_of: dict[str, Node] = {}
    for node, parent in plan:  # plan order: parents always first
        if node.model_id not in needed:
            continue
        receipt = send(w3, registry.functions.registerModel(
            to_bytes32(node.weights_hash), to_bytes32(node.data_ref_hash),
            onchain_id[parent] if parent else 0, node.uri))
        onchain_id[node.model_id] = registry.events.ModelRegistered().process_receipt(receipt)[0]["args"]["id"]
        node_of[node.model_id] = node

    rows = []
    for m in sample:
        node = node_of[m]
        ok, gas = probe.functions.probeVerifyWeights(
            registry.address, onchain_id[m], to_bytes32(node.weights_hash)).call()
        length, lineage_gas = probe.functions.probeLineage(registry.address, onchain_id[m]).call()
        # On-chain generations can differ from the tree depth: a child of an exact re-upload
        # is attached to the first copy (plan_registrations), which may sit at another depth.
        if not ok or length != len(ancestors(m, parent_of)):
            raise AssertionError(f"storage check failed for {m}")
        rows.append({"design": "storage", "batch_size": 1, "model_id": m, "depth": node.depth,
                     "proof_len": 0, "verify_gas": gas, "lineage_len": length,
                     "lineage_gas": lineage_gas})
    return rows


def measure_merkle(w3, probe, plan, sample, parent_of, batch_size: int) -> list[dict]:
    """Cut batches exactly as src/replay.py does, anchor only the batches we need, and
    probe each sampled model and every record of its lineage."""
    registry, _ = deploy(w3, "MerkleRegistry")
    weights_of = {node.model_id: node.weights_hash for node, _ in plan}
    needed = {a for m in sample for a in ancestors(m, parent_of)}

    # where[model] = (batch id on this chain, record tuple, proof)
    where: dict[str, tuple[int, tuple, list[bytes]]] = {}
    depth_of: dict[str, int] = {}
    batch_id = 0
    for b, start in enumerate(range(0, len(plan), batch_size)):
        chunk = plan[start:start + batch_size]
        if not any(node.model_id in needed for node, _ in chunk):
            continue  # skipping a batch does not change any proof in the batches we keep
        records = [(to_bytes32(n.weights_hash), to_bytes32(n.data_ref_hash),
                    to_bytes32(weights_of[p]) if p else ZERO32, n.uri) for n, p in chunk]
        tree = MerkleTree([leaf_hash(*r) for r in records])
        send(w3, registry.functions.anchorBatch(tree.root, len(chunk), f"batch-{b + 1}"))
        batch_id += 1
        for i, (node, _) in enumerate(chunk):
            if node.model_id in needed:
                where[node.model_id] = (batch_id, records[i], tree.proof(i))
                depth_of[node.model_id] = node.depth

    def probe_one(model_id: str) -> tuple[int, int]:
        bid, record, proof = where[model_id]
        ok, gas = probe.functions.probeVerifyRecord(registry.address, bid, *record, proof).call()
        if not ok:
            raise AssertionError(f"merkle k={batch_size}: {model_id} did not verify")
        return gas, len(proof)

    rows = []
    for m in sample:
        gas, proof_len = probe_one(m)
        lineage = ancestors(m, parent_of)
        lineage_gas = sum(probe_one(a)[0] for a in lineage)  # one check per generation
        rows.append({"design": "merkle", "batch_size": batch_size, "model_id": m,
                     "depth": depth_of[m], "proof_len": proof_len, "verify_gas": gas,
                     "lineage_len": len(lineage), "lineage_gas": lineage_gas})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Gas for a contract to verify records.")
    parser.add_argument("--tree", type=Path, default=Path("data/hf_tree.csv"))
    parser.add_argument("--rpc", default="http://127.0.0.1:8545")
    parser.add_argument("--per-depth", type=int, default=5)
    parser.add_argument("--seed", type=int, default=435)
    parser.add_argument("--batch-sizes", nargs="+", type=int, default=[1, 8, 32, 128])
    parser.add_argument("--out", type=Path, default=Path("data/results/verify_gas.csv"))
    args = parser.parse_args()

    plan, _ = plan_registrations(read_tree_csv(args.tree))
    parent_of = {node.model_id: parent for node, parent in plan}
    sample = sample_models(plan, args.per_depth, args.seed)
    print(f"{len(sample)} sampled models (seed {args.seed}, up to {args.per_depth} per depth)")

    w3 = connect(args.rpc)
    probe, _ = deploy(w3, "VerifyProbe")
    rows = measure_storage(w3, probe, plan, sample, parent_of)
    print("storage done")
    for k in args.batch_sizes:
        rows += measure_merkle(w3, probe, plan, sample, parent_of, k)
        print(f"merkle k={k} done")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
