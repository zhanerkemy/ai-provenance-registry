"""Small helpers for talking to an Ethereum node from Python (web3.py).

This week everything runs on Anvil, Foundry's local blockchain: free, instant, and
it starts with 10 accounts already holding test ETH. In one terminal run
    anvil
and leave it open. Anvil listens on http://127.0.0.1:8545 by default.

The contracts must be compiled first (`forge build`); this module reads the compiled
ABI (the list of functions) and bytecode from the out/ folder that forge creates.

Anvil's accounts are "unlocked", so no private key is needed here.
"""

from __future__ import annotations

import json
from pathlib import Path

from web3 import Web3
from web3.contract import Contract

DEFAULT_RPC = "http://127.0.0.1:8545"
OUT_DIR = Path(__file__).resolve().parents[1] / "out"


def connect(rpc: str = DEFAULT_RPC) -> Web3:
    w3 = Web3(Web3.HTTPProvider(rpc))
    if not w3.is_connected():
        raise ConnectionError(f"No Ethereum node at {rpc}. Start one with: anvil")
    return w3


def load_artifact(name: str) -> dict:
    """Compiled contract produced by `forge build`, e.g. load_artifact("ModelRegistry")."""
    path = OUT_DIR / f"{name}.sol" / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run `forge build` first.")
    return json.loads(path.read_text(encoding="utf-8"))


def compiler_version(name: str) -> str:
    """Exact solc version the artifact was built with (recorded for reproducibility)."""
    return load_artifact(name)["metadata"]["compiler"]["version"]


def deploy(w3: Web3, name: str, sender: str | None = None) -> tuple[Contract, dict]:
    """Deploy a fresh copy of a contract. Returns (contract, receipt)."""
    art = load_artifact(name)
    factory = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]["object"])
    tx_hash = factory.constructor().transact({"from": sender or w3.eth.accounts[0]})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if receipt["status"] != 1:
        raise RuntimeError(f"deploying {name} failed")
    return w3.eth.contract(address=receipt["contractAddress"], abi=art["abi"]), receipt


def send(w3: Web3, call, sender: str | None = None) -> dict:
    """Send a state-changing call, e.g. send(w3, registry.functions.registerModel(...)).

    Returns the receipt; receipt["gasUsed"] is the gas this transaction really cost.
    """
    tx_hash = call.transact({"from": sender or w3.eth.accounts[0]})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if receipt["status"] != 1:
        raise RuntimeError(f"transaction {tx_hash.hex()} reverted")
    return receipt
