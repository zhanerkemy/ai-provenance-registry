"""Shared pytest setup: a private Anvil chain for tests that need a real blockchain.

Tests that use the `w3` fixture start their own Anvil on a free port (so they never
touch the Anvil you may have open for experiments) and are skipped, not failed,
if Anvil is not installed or the contracts are not compiled (`forge build`).
"""

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def w3():
    if shutil.which("anvil") is None:
        pytest.skip("anvil not installed (install Foundry)")
    if not (ROOT / "out" / "MerkleRegistry.sol" / "MerkleRegistry.json").exists():
        pytest.skip("contracts not compiled (run `forge build`)")

    from chain import connect

    port = _free_port()
    proc = subprocess.Popen(["anvil", "--port", str(port), "--silent"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):  # wait up to 5 s for Anvil to start
            try:
                web3 = connect(f"http://127.0.0.1:{port}")
                break
            except ConnectionError:
                time.sleep(0.1)
        else:
            pytest.fail("anvil did not start")
        yield web3
    finally:
        proc.terminate()
        proc.wait(timeout=10)