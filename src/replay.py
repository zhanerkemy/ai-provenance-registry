"""Register every model of the tree under each design and record the gas.

    python src/replay.py                                    # Anvil, all models
    python src/replay.py --network sepolia --max-models 24 --batch-sizes 1 8

Designs: storage (record in storage), event (record only in the log), merkle (one root
per batch of k models). Each gets a new contract and the same models in the same order;
parents come first, so --max-models never cuts off a parent.

Writes data/results/gas.csv and run_meta.json (on Sepolia: data/results/sepolia/).
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from chain import compiler_version, connect, connect_network, default_sender, deploy, send
from hash_file import hash_file
from hf_lineage import Node, plan_registrations, read_tree_csv
from merkle_tree import ZERO32, MerkleTree, leaf_hash, to_bytes32

GAS_COLUMNS = ["design", "batch_size", "batch_index", "model_id", "depth", "uri_bytes",
               "tx_gas", "gas_per_model", "verify_gas"]


def contract_info(design: str, batch_size: int, registry, receipt) -> dict:
    """Where a contract was deployed; Stage 4 asks for the address and block range."""
    return {"design": design, "batch_size": batch_size, "address": registry.address,
            "deploy_block": receipt["blockNumber"], "deploy_tx": "0x" + receipt["transactionHash"].hex().removeprefix("0x"),
            "deploy_gas": receipt["gasUsed"]}


def replay_per_model(w3, contract_name: str, design: str, plan) -> tuple[list[dict], dict]:
    """Storage and event designs: one registerModel transaction per model."""
    registry, deploy_receipt = deploy(w3, contract_name)
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
    return rows, contract_info(design, 1, registry, deploy_receipt)


def replay_merkle(w3, plan, batch_size: int) -> tuple[list[dict], dict]:
    """Merkle design: one anchorBatch transaction per `batch_size` models."""
    registry, deploy_receipt = deploy(w3, "MerkleRegistry")
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
    return rows, contract_info("merkle", batch_size, registry, deploy_receipt)


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


def check_funds(w3, sample_ids: set[str], args) -> None:
    """Before spending real (test) ETH: estimate the cost from the Anvil run of the same
    transactions, and stop if the wallet cannot pay for it with a 50% margin."""
    anvil_gas = Path("data/results/gas.csv")
    if not anvil_gas.exists():
        print("No Anvil results to estimate cost from; run src/replay.py on Anvil first.")
        return
    with anvil_gas.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["model_id"] in sample_ids
                and r["design"] in args.designs
                and (r["design"] != "merkle" or int(r["batch_size"]) in args.batch_sizes)]
    deploys = 700_000 * (len(args.designs) - 1 + len(args.batch_sizes))  # each deploy < 700k gas
    gas = sum(int(r["tx_gas"]) for r in rows) + deploys
    price = w3.eth.gas_price
    balance = w3.eth.get_balance(default_sender(w3))
    cost = gas * price
    print(f"About {gas:,} gas at {price / 1e9:.2f} gwei = {cost / 1e18:.4f} ETH; "
          f"wallet {default_sender(w3)} has {balance / 1e18:.4f} ETH")
    if balance < 1.5 * cost:
        raise SystemExit("Not enough test ETH (need 1.5x the estimate). Use a faucet, "
                         "or lower --max-models.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a model tree on-chain and record gas.")
    parser.add_argument("--tree", type=Path, default=Path("data/hf_tree.csv"))
    parser.add_argument("--network", choices=["anvil", "sepolia"], default="anvil")
    parser.add_argument("--rpc", help="a different local node (default: Anvil on port 8545)")
    parser.add_argument("--max-models", type=int, help="register only the first N models")
    parser.add_argument("--designs", nargs="+", default=["storage", "event", "merkle"],
                        choices=["storage", "event", "merkle"])
    parser.add_argument("--batch-sizes", nargs="+", type=int, default=[1, 8, 32, 128])
    parser.add_argument("--out", type=Path, help="default data/results[/sepolia]/gas.csv")
    args = parser.parse_args()
    if args.out is None:
        sub = "" if args.network == "anvil" else f"{args.network}/"
        args.out = Path(f"data/results/{sub}gas.csv")

    nodes = read_tree_csv(args.tree)
    plan, excluded = plan_registrations(nodes)
    print(f"{len(nodes)} models in tree, {len(plan)} registrable, {len(excluded)} left out")
    n_registrable = len(plan)
    if args.max_models:
        plan = plan[:args.max_models]  # a prefix: parents always come before children
        print(f"registering the first {len(plan)} only (--max-models)")

    w3 = connect(args.rpc) if args.rpc else connect_network(args.network)
    if args.network != "anvil":
        check_funds(w3, {node.model_id for node, _ in plan}, args)
    first_block = w3.eth.block_number + 1
    rows: list[dict] = []
    contracts: list[dict] = []
    if "storage" in args.designs:
        new_rows, info = replay_per_model(w3, "ModelRegistry", "storage", plan)
        rows += new_rows
        contracts.append(info)
        print("storage done")
    if "event" in args.designs:
        new_rows, info = replay_per_model(w3, "EventRegistry", "event", plan)
        rows += new_rows
        contracts.append(info)
        print("event done")
    if "merkle" in args.designs:
        for k in args.batch_sizes:
            new_rows, info = replay_merkle(w3, plan, k)
            rows += new_rows
            contracts.append(info)
            print(f"merkle k={k} done")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=GAS_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    reasons: dict[str, int] = {}
    for reason in excluded.values():
        reasons[reason] = reasons.get(reason, 0) + 1
    meta = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "network": args.network,
        "chain_id": w3.eth.chain_id,
        # The Sepolia URL contains a private API key, so it is never written to a file.
        "rpc": args.rpc or ("http://127.0.0.1:8545" if args.network == "anvil" else "from .env"),
        "sender": default_sender(w3),
        "block_range": [first_block, w3.eth.block_number],
        "contracts": contracts,
        "solc": compiler_version("ModelRegistry"),
        "tree_file": str(args.tree),
        "tree_file_sha256": hash_file(args.tree),
        "designs": args.designs,
        "batch_sizes": args.batch_sizes,
        "n_models_in_tree": len(nodes),
        "n_registrable": n_registrable,
        "max_models": args.max_models,
        "n_registered": len(plan),
        "excluded_by_reason": reasons,
    }
    meta_path = args.out.with_name("run_meta.json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(rows)} rows to {args.out} and run details to {meta_path}")


if __name__ == "__main__":
    main()
