"""Regenerate every result, table and number, and check that nothing changed.

    python src/reproduce.py            # about 8 minutes
    python src/reproduce.py --quick    # about 1 minute, reuses the committed gas.csv

Runs README steps 1 and 3 to 10 on its own Anvil (on a free port), using the committed
tree, then compares the files with git. Exit code 0 means everything came out the same.
run_meta.json (run time, blocks) and the PNGs (fonts differ per system) may change.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TO_DIFFER = {"data/results/run_meta.json"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)


def start_anvil(port: int) -> subprocess.Popen:
    anvil = subprocess.Popen(["anvil", "--port", str(port), "--silent"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return anvil
        except OSError:
            time.sleep(0.2)
    anvil.kill()
    raise RuntimeError("Anvil did not start")


def git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    return out.splitlines()


def changed_files() -> list[str]:
    """Files in data/ or figures/ whose content differs from the last commit, plus new ones.
    `git diff` compares content; `git status` alone can call a rewritten but identical file
    modified on Windows."""
    tracked = git("diff", "--name-only", "HEAD", "--", "data", "figures")
    new = git("ls-files", "--others", "--exclude-standard", "--", "data", "figures")
    return sorted(set(tracked) | set(new))


def verdict(changed: list[str]) -> tuple[list[str], list[str]]:
    """Split changed files into (unexpected, expected) changes."""
    expected = [f for f in changed if f in EXPECTED_TO_DIFFER or f.endswith(".png")]
    return [f for f in changed if f not in expected], expected


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate all results and compare.")
    parser.add_argument("--quick", action="store_true", help="skip the 7-minute replay.py")
    args = parser.parse_args()

    for tool in ("forge", "anvil", "git"):
        if shutil.which(tool) is None:
            print(f"{tool} not found: install it first (see README, Setup)")
            return 2
    if changed_files():
        print("data/ or figures/ already has uncommitted changes; commit or restore them first,")
        print("otherwise the comparison below would not mean anything.")
        return 2

    py, rpc_port = sys.executable, free_port()
    rpc = f"http://127.0.0.1:{rpc_port}"
    run(["forge", "build"])
    anvil = start_anvil(rpc_port)
    try:
        run([py, "src/tree_stats.py"])
        if not args.quick:
            run([py, "src/replay.py", "--rpc", rpc])
        run([py, "src/gas_model.py"])
        run([py, "src/verify_gas.py", "--rpc", rpc])
        run([py, "src/audit_checks.py", "--rpc", rpc])
    finally:
        anvil.terminate()
        anvil.wait()
    run([py, "src/make_figures.py"])
    run([py, "src/make_tables.py"])
    run([py, "src/make_numbers.py"])

    unexpected, expected = verdict(changed_files())
    for f in expected:
        print(f"  changed, as expected: {f}")
    if unexpected:
        print("These generated files differ from the committed ones:")
        for f in unexpected:
            print(f"  {f}")
        print("See what changed with: git diff -- <file>")
        return 1
    print("All results, tables and numbers regenerated identically.")
    print("Undo the expected changes with: git restore data figures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
