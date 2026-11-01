"""Run the audit checks of the measurement plan against every design, and record what
the chain actually does. Answers sub-question 4: which guarantees does each design keep?

Usage (from the repository root, with `anvil` running and `forge build` done):
    python src/audit_checks.py

Output:
    data/results/guarantees.csv  one row per check per design

Each check deploys fresh contracts, uses real records from data/hf_tree.csv (the base
model and its first registrable child), tries the thing, and writes down the outcome:

    yes             the contract enforces or supports it by itself
    with proof      works only if the auditor also has the record and its Merkle proof
    off-chain only  possible by reading event logs from a node, but no contract can do it
    no              the chain accepts the bad input, or the operation does not exist

Nothing in the result column is typed by hand: every value comes from a transaction
or a call made in this run. test/test_audit_checks.py checks the expected table.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from web3 import Web3
from web3.exceptions import ContractCustomError, ContractLogicError

from chain import connect, deploy, send
from hf_lineage import plan_registrations, read_tree_csv
from merkle_tree import ZERO32, MerkleTree, leaf_hash, to_bytes32

COLUMNS = ["check_id", "check", "design", "result", "evidence"]
DESIGNS = ["storage", "event", "merkle"]

CHECKS = {
    1: "A tampered weights hash is detected",
    2: "Registering the same weights twice is refused",
    3: "A record whose parent was never registered is refused",
    4: "An empty (zero) weights hash is refused",
    5: "Another contract can check a record",
    6: "A model's lineage can be followed on-chain",
    7: "The owner of one model can hand it to another account",
}


# --------------------------------------------------------------------------- helpers


def flip(h: bytes) -> bytes:
    """The same hash with its last bit changed: what a tampered file would hash to."""
    return h[:-1] + bytes([h[-1] ^ 1])


def error_name(contract, exc: Exception) -> str:
    """Name of the custom Solidity error inside a revert, e.g. 'AlreadyRegistered'."""
    data = str(getattr(exc, "data", "") or exc)
    for item in contract.abi:
        if item["type"] == "error":
            signature = f"{item['name']}({','.join(i['type'] for i in item['inputs'])})"
            selector = Web3.keccak(text=signature)[:4].hex().removeprefix("0x")
            if selector in data:
                return item["name"]
    return type(exc).__name__


def try_send(w3, contract, call, sender=None) -> tuple[bool, str]:
    """Send a transaction. Returns (accepted, evidence)."""
    try:
        send(w3, call, sender)
        return True, "accepted"  # no block number: it changes between runs
    except (ContractCustomError, ContractLogicError) as exc:
        return False, f"reverted with {error_name(contract, exc)}"


def has_function(contract, name: str) -> bool:
    return any(i["type"] == "function" and i["name"] == name for i in contract.abi)


def record_readers(contract) -> list[str]:
    """View functions that return something about a registered model (not just a count)."""
    return [i["name"] for i in contract.abi
            if i["type"] == "function" and i["stateMutability"] in ("view", "pure")
            and i["name"] not in ("modelCount", "batchCount", "leafHash")]


class Records:
    """The base model and its first registrable child, as on-chain values."""

    def __init__(self, tree: Path):
        plan, _ = plan_registrations(read_tree_csv(tree))
        base = plan[0][0]
        child = next(n for n, parent in plan if parent == base.model_id)
        self.base_w, self.base_d, self.base_uri = (
            to_bytes32(base.weights_hash), to_bytes32(base.data_ref_hash), base.uri)
        self.child_w, self.child_d, self.child_uri = (
            to_bytes32(child.weights_hash), to_bytes32(child.data_ref_hash), child.uri)

    def merkle_base(self):
        return (self.base_w, self.base_d, ZERO32, self.base_uri)

    def merkle_child(self):
        return (self.child_w, self.child_d, self.base_w, self.child_uri)


def anchor(w3, registry, records: list[tuple], sender=None) -> tuple[int, MerkleTree]:
    tree = MerkleTree([leaf_hash(*r) for r in records])
    send(w3, registry.functions.anchorBatch(tree.root, len(records), "audit-batch"), sender)
    return registry.functions.batchCount().call(), tree


def merkle_verifies(registry, batch_id: int, record: tuple, proof: list[bytes]) -> bool:
    return registry.functions.verifyRecord(batch_id, *record, proof).call()


# --------------------------------------------------------------------------- the checks
# Each function returns {design: (result, evidence)} for one check.


def check_tamper(w3, r: Records, probe) -> dict:
    out = {}
    reg, _ = deploy(w3, "ModelRegistry")
    send(w3, reg.functions.registerModel(r.base_w, r.base_d, 0, r.base_uri))
    good = reg.functions.verifyWeights(1, r.base_w).call()
    bad = reg.functions.verifyWeights(1, flip(r.base_w)).call()
    out["storage"] = ("yes" if good and not bad else "no",
                      f"verifyWeights: real hash -> {good}, tampered -> {bad}")

    reg, _ = deploy(w3, "EventRegistry")
    receipt = send(w3, reg.functions.registerModel(r.base_w, r.base_d, 0, r.base_uri))
    log = reg.events.ModelRegistered().get_logs(from_block=receipt["blockNumber"])[0]
    logged = bytes(log["args"]["weightsHash"])
    detected = logged == r.base_w and logged != flip(r.base_w)
    out["event"] = ("off-chain only" if detected and not record_readers(reg) else "no",
                    "tampered hash differs from the log entry read with eth_getLogs; "
                    f"contract read functions: {record_readers(reg) or 'none'}")

    reg, _ = deploy(w3, "MerkleRegistry")
    batch, tree = anchor(w3, reg, [r.merkle_base(), r.merkle_child()])
    good = merkle_verifies(reg, batch, r.merkle_base(), tree.proof(0))
    bad = merkle_verifies(reg, batch, (flip(r.base_w), *r.merkle_base()[1:]), tree.proof(0))
    no_proof = merkle_verifies(reg, batch, r.merkle_base(), [])
    out["merkle"] = ("with proof" if good and not bad and not no_proof else "no",
                     f"verifyRecord: real -> {good}, tampered -> {bad}, "
                     f"real without its proof -> {no_proof}")
    return out


def check_duplicate(w3, r: Records, probe) -> dict:
    out = {}
    for design, name in (("storage", "ModelRegistry"), ("event", "EventRegistry")):
        reg, _ = deploy(w3, name)
        send(w3, reg.functions.registerModel(r.base_w, r.base_d, 0, r.base_uri))
        accepted, evidence = try_send(w3, reg, reg.functions.registerModel(
            r.base_w, r.base_d, 0, r.base_uri), sender=w3.eth.accounts[1])
        out[design] = ("no" if accepted else "yes",
                       f"second registration by another account: {evidence}")

    reg, _ = deploy(w3, "MerkleRegistry")
    b1, t1 = anchor(w3, reg, [r.merkle_base()])
    b2, t2 = anchor(w3, reg, [r.merkle_base()], sender=w3.eth.accounts[1])
    both = merkle_verifies(reg, b1, r.merkle_base(), t1.proof(0)) and \
        merkle_verifies(reg, b2, r.merkle_base(), t2.proof(0))
    out["merkle"] = ("no" if both else "yes",
                     f"same record anchored in batches {b1} and {b2} by two accounts; "
                     f"verifies in both: {both}")
    return out


def check_missing_parent(w3, r: Records, probe) -> dict:
    out = {}
    for design, name in (("storage", "ModelRegistry"), ("event", "EventRegistry")):
        reg, _ = deploy(w3, name)
        send(w3, reg.functions.registerModel(r.base_w, r.base_d, 0, r.base_uri))
        accepted, evidence = try_send(w3, reg, reg.functions.registerModel(
            r.child_w, r.child_d, 99, r.child_uri))
        out[design] = ("no" if accepted else "yes", f"child with parentId 99: {evidence}")

    reg, _ = deploy(w3, "MerkleRegistry")
    orphan = (r.child_w, r.child_d, Web3.keccak(text="never registered"), r.child_uri)
    batch, tree = anchor(w3, reg, [orphan])
    ok = merkle_verifies(reg, batch, orphan, tree.proof(0))
    out["merkle"] = ("no" if ok else "yes",
                     f"record pointing to an unknown parent anchored; verifies: {ok}")
    return out


def check_zero_hash(w3, r: Records, probe) -> dict:
    out = {}
    for design, name in (("storage", "ModelRegistry"), ("event", "EventRegistry")):
        reg, _ = deploy(w3, name)
        accepted, evidence = try_send(w3, reg, reg.functions.registerModel(
            ZERO32, r.base_d, 0, r.base_uri))
        out[design] = ("no" if accepted else "yes", f"zero weights hash: {evidence}")

    reg, _ = deploy(w3, "MerkleRegistry")
    empty = (ZERO32, r.base_d, ZERO32, r.base_uri)
    batch, tree = anchor(w3, reg, [empty])
    ok = merkle_verifies(reg, batch, empty, tree.proof(0))
    out["merkle"] = ("no" if ok else "yes",
                     f"record with zero weights anchored (its leaf is not zero); verifies: {ok}")
    return out


def check_contract_can_verify(w3, r: Records, probe) -> dict:
    out = {}
    reg, _ = deploy(w3, "ModelRegistry")
    send(w3, reg.functions.registerModel(r.base_w, r.base_d, 0, r.base_uri))
    ok, gas = probe.functions.probeVerifyWeights(reg.address, 1, r.base_w).call()
    out["storage"] = ("yes" if ok else "no", f"VerifyProbe -> {ok}, {gas} gas")

    reg, _ = deploy(w3, "EventRegistry")
    readers = record_readers(reg)
    out["event"] = ("no" if not readers else "yes",
                    f"read functions: {readers or 'none'}; contracts cannot read event logs")

    reg, _ = deploy(w3, "MerkleRegistry")
    batch, tree = anchor(w3, reg, [r.merkle_base(), r.merkle_child()])
    ok, gas = probe.functions.probeVerifyRecord(
        reg.address, batch, *r.merkle_base(), tree.proof(0)).call()
    out["merkle"] = ("with proof" if ok else "no",
                     f"VerifyProbe with the proof -> {ok}, {gas} gas")
    return out


def check_lineage(w3, r: Records, probe) -> dict:
    out = {}
    reg, _ = deploy(w3, "ModelRegistry")
    send(w3, reg.functions.registerModel(r.base_w, r.base_d, 0, r.base_uri))
    send(w3, reg.functions.registerModel(r.child_w, r.child_d, 1, r.child_uri))
    lineage = reg.functions.getLineage(2).call()
    out["storage"] = ("yes" if lineage == [2, 1] else "no", f"getLineage(2) -> {lineage}")

    reg, _ = deploy(w3, "EventRegistry")
    first = send(w3, reg.functions.registerModel(r.base_w, r.base_d, 0, r.base_uri))
    send(w3, reg.functions.registerModel(r.child_w, r.child_d, 1, r.child_uri))
    logs = {e["args"]["id"]: e["args"]["parentId"]
            for e in reg.events.ModelRegistered().get_logs(from_block=first["blockNumber"])}
    walk, cur = [], 2
    while cur:
        walk.append(cur)
        cur = logs[cur]
    out["event"] = ("off-chain only" if walk == [2, 1] and not record_readers(reg) else "no",
                    f"parent links rebuilt from eth_getLogs: {walk}; no contract function")

    reg, _ = deploy(w3, "MerkleRegistry")
    batch, tree = anchor(w3, reg, [r.merkle_base(), r.merkle_child()])
    child_ok = merkle_verifies(reg, batch, r.merkle_child(), tree.proof(1))
    parent_ok = merkle_verifies(reg, batch, r.merkle_base(), tree.proof(0))
    links = r.merkle_child()[2] == r.merkle_base()[0]  # child's parent = base's weights
    out["merkle"] = ("with proof" if child_ok and parent_ok and links else "no",
                     f"child verifies: {child_ok}, its parent's record verifies: {parent_ok}, "
                     "each step needs that record and its proof")
    return out


def check_ownership(w3, r: Records, probe) -> dict:
    out = {}
    owner, new_owner, stranger = w3.eth.accounts[:3]
    reg, _ = deploy(w3, "ModelRegistry")
    send(w3, reg.functions.registerModel(r.base_w, r.base_d, 0, r.base_uri), owner)
    stolen, why = try_send(w3, reg, reg.functions.transferOwnership(1, stranger), stranger)
    moved, _ = try_send(w3, reg, reg.functions.transferOwnership(1, new_owner), owner)
    now = reg.functions.getModel(1).call()[0]
    out["storage"] = ("yes" if moved and not stolen and now == new_owner else "no",
                      f"owner's transfer accepted: {moved}; stranger's attempt {why}")

    reg, _ = deploy(w3, "EventRegistry")
    out["event"] = ("no" if not has_function(reg, "transferOwnership") else "yes",
                    "no transferOwnership function and no stored owner")

    reg, _ = deploy(w3, "MerkleRegistry")
    batch, _ = anchor(w3, reg, [r.merkle_base(), r.merkle_child()], sender=owner)
    submitter = reg.functions.getBatch(batch).call()[0]
    out["merkle"] = ("no" if not has_function(reg, "transferOwnership") else "yes",
                     f"no transfer function; the only owner is the batch submitter "
                     f"({'matches' if submitter == owner else 'differs from'} the sender)")
    return out


CHECK_FUNCTIONS = {1: check_tamper, 2: check_duplicate, 3: check_missing_parent,
                   4: check_zero_hash, 5: check_contract_can_verify, 6: check_lineage,
                   7: check_ownership}


def run_all(w3, records: Records) -> list[dict]:
    probe, _ = deploy(w3, "VerifyProbe")
    rows = []
    for check_id, fn in CHECK_FUNCTIONS.items():
        results = fn(w3, records, probe)
        for design in DESIGNS:
            result, evidence = results[design]
            rows.append({"check_id": check_id, "check": CHECKS[check_id], "design": design,
                         "result": result, "evidence": evidence})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the audit checks on every design.")
    parser.add_argument("--tree", type=Path, default=Path("data/hf_tree.csv"))
    parser.add_argument("--rpc", default="http://127.0.0.1:8545")
    parser.add_argument("--out", type=Path, default=Path("data/results/guarantees.csv"))
    args = parser.parse_args()

    rows = run_all(connect(args.rpc), Records(args.tree))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    width = max(len(c) for c in CHECKS.values())
    print(f"{'check':{width}}  " + "  ".join(f"{d:14}" for d in DESIGNS))
    for check_id, text in CHECKS.items():
        cells = [next(r["result"] for r in rows if r["check_id"] == check_id and r["design"] == d)
                 for d in DESIGNS]
        print(f"{text:{width}}  " + "  ".join(f"{c:14}" for c in cells))
    print(f"\nWrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
