"""Helpers to connect to a chain, deploy our contracts and send transactions (web3.py).

    anvil    local chain (run `anvil`); its accounts are unlocked, no key needed
    sepolia  public test chain; transactions are signed with the key from .env

Run `forge build` first: the compiled contracts are read from out/.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from eth_account import Account
from web3 import Web3
from web3.contract import Contract
from web3.middleware import SignAndSendRawMiddlewareBuilder

DEFAULT_RPC = "http://127.0.0.1:8545"
OUT_DIR = Path(__file__).resolve().parents[1] / "out"
RECEIPT_TIMEOUT = 300  # seconds; a Sepolia block comes every 12 s, but it can be slow


def connect(rpc: str = DEFAULT_RPC, private_key: str | None = None) -> Web3:
    """Connect to a node. With a private key, every transaction is signed locally (the
    key never leaves this computer) and sent from that key's address."""
    w3 = Web3(Web3.HTTPProvider(rpc))
    if not w3.is_connected():
        raise ConnectionError(f"No Ethereum node at {rpc}. Start one with: anvil")
    if private_key:
        account = Account.from_key(private_key)
        w3.middleware_onion.inject(SignAndSendRawMiddlewareBuilder.build(account), layer=0)
        w3.eth.default_account = account.address
    return w3


def connect_network(network: str) -> Web3:
    """connect() for "anvil" (no key) or "sepolia" (RPC URL and key from .env)."""
    if network == "anvil":
        return connect(DEFAULT_RPC)
    if network != "sepolia":
        raise ValueError(f"unknown network {network!r}")
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    rpc, key = os.getenv("SEPOLIA_RPC_URL"), os.getenv("PRIVATE_KEY")
    if not rpc or not key:
        raise RuntimeError("Set SEPOLIA_RPC_URL and PRIVATE_KEY in .env (copy .env.example)")
    w3 = connect(rpc, key)
    if w3.eth.chain_id != 11155111:  # Sepolia's chain id
        raise RuntimeError(f"{rpc} is chain {w3.eth.chain_id}, not Sepolia (11155111)")
    return w3


def default_sender(w3: Web3) -> str:
    """The signing key's address if connect() was given one, else Anvil's first account."""
    if isinstance(w3.eth.default_account, str):
        return w3.eth.default_account
    return w3.eth.accounts[0]


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
    tx_hash = factory.constructor().transact({"from": sender or default_sender(w3)})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=RECEIPT_TIMEOUT)
    if receipt["status"] != 1:
        raise RuntimeError(f"deploying {name} failed")
    return w3.eth.contract(address=receipt["contractAddress"], abi=art["abi"]), receipt


def send(w3: Web3, call, sender: str | None = None) -> dict:
    """Send a state-changing call, e.g. send(w3, registry.functions.registerModel(...)).

    Returns the receipt; receipt["gasUsed"] is the gas this transaction really cost.
    """
    tx_hash = call.transact({"from": sender or default_sender(w3)})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=RECEIPT_TIMEOUT)
    if receipt["status"] != 1:
        raise RuntimeError(f"transaction {tx_hash.hex()} reverted")
    return receipt
