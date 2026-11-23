"""Offline tests for src/compare_chains.py, with small made-up result files."""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compare_chains import (by_design, compare, deployments_markdown,  # noqa: E402
                            read_all_rows, read_rows)

ROOT = Path(__file__).resolve().parents[1]

COLUMNS = ["design", "batch_size", "batch_index", "model_id", "tx_gas", "gas_per_model"]


def write_gas(path: Path, rows: list[tuple]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    return path


def meta(contracts):
    return {"run_at_utc": "2026-10-30T10:00:00+00:00", "block_range": [100, 180],
            "tree_file_sha256": "abc", "solc": "0.8.24", "chain_id": 11155111,
            "sender": "0x" + "11" * 20, "n_registered": 2, "n_registrable": 1071,
            "contracts": contracts}


CONTRACT = {"design": "storage", "batch_size": 1, "address": "0x" + "22" * 20,
            "deploy_block": 100, "deploy_tx": "0x" + "33" * 32, "deploy_gas": 645733}

ANVIL = [("storage", 1, 0, "a", 210000, 210000), ("storage", 1, 1, "b", 213000, 213000),
         ("merkle", 8, 0, "a", 75700, 37850), ("merkle", 8, 0, "b", 0, 37850)]


def test_identical_runs_have_no_differences(tmp_path):
    anvil = read_rows(write_gas(tmp_path / "anvil.csv", ANVIL))
    public = read_rows(write_gas(tmp_path / "public.csv", ANVIL))
    result = compare(anvil, public, meta([CONTRACT]), meta([CONTRACT]))
    assert result["transactions_compared"] == 3  # the merkle batch counts once
    assert result["transactions_identical"] == 3
    assert result["differences"] == []
    assert result["deployments"][0]["identical"]


def test_a_difference_is_reported_not_hidden(tmp_path):
    changed = [list(r) for r in ANVIL]
    changed[1][4] = changed[1][5] = 213100  # model b cost 100 gas more on the public chain
    anvil = read_rows(write_gas(tmp_path / "anvil.csv", ANVIL))
    public = read_rows(write_gas(tmp_path / "public.csv", changed))
    result = compare(anvil, public, meta([CONTRACT]), meta([CONTRACT]))
    assert result["transactions_identical"] == 2
    assert result["differences"] == [{"design": "storage", "batch_size": 1, "model_id": "b",
                                      "anvil_gas": 213000, "sepolia_gas": 213100,
                                      "difference": 100}]


def test_deployments_page_links_every_contract():
    page = deployments_markdown(meta([CONTRACT]))
    assert CONTRACT["address"] in page
    assert f"https://sepolia.etherscan.io/tx/{CONTRACT['deploy_tx']}" in page
    assert "100 to 180" in page


def test_by_design_compares_the_same_models(tmp_path):
    """The Sepolia sample has fewer models than Anvil: the Anvil mean must be taken over
    the sample's models only (here a and b, not c)."""
    anvil = ANVIL + [("storage", 1, 2, "c", 900000, 900000)]
    public = [("storage", 1, 0, "a", 420000, 420000), ("storage", 1, 1, "b", 426000, 426000),
              ("merkle", 8, 0, "a", 151400, 75700), ("merkle", 8, 0, "b", 0, 75700)]
    rows = by_design(read_all_rows(write_gas(tmp_path / "anvil.csv", anvil)),
                     read_all_rows(write_gas(tmp_path / "public.csv", public)))
    assert rows == [
        {"design": "storage", "batch_size": 1, "models": 2, "anvil_mean_gas_per_model": 211500,
         "sepolia_mean_gas_per_model": 423000, "ratio": 2.0},
        {"design": "merkle", "batch_size": 8, "models": 2, "anvil_mean_gas_per_model": 37850,
         "sepolia_mean_gas_per_model": 75700, "ratio": 2.0},
    ]


def test_committed_chain_check_is_current():
    """data/results/chain_check.json must be regenerated whenever its inputs change."""
    results = ROOT / "data" / "results"
    committed = results / "chain_check.json"
    if not (results / "sepolia" / "gas.csv").exists():
        return
    anvil_meta = json.loads((results / "run_meta.json").read_text(encoding="utf-8"))
    public_meta = json.loads((results / "sepolia" / "run_meta.json").read_text(encoding="utf-8"))
    expected = compare(read_rows(results / "gas.csv"), read_rows(results / "sepolia" / "gas.csv"),
                       anvil_meta, public_meta)
    expected["by_design"] = by_design(read_all_rows(results / "gas.csv"),
                                      read_all_rows(results / "sepolia" / "gas.csv"))
    assert json.loads(committed.read_text(encoding="utf-8")) == expected, \
        "data/results/chain_check.json is stale: run python src/compare_chains.py"
