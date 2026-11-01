"""Consistency checks on the committed results in data/results/.

These tests do not run anything on a blockchain. They read the CSV and JSON files we
committed and check that they agree with each other and with data/hf_tree.csv. If a
result file was produced from an old tree, edited by hand, or cut short, a test fails.
They are skipped until data/results/gas.csv exists.

Run with:  python -m pytest test/test_results.py -v
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hash_file import hash_file  # noqa: E402
from hf_lineage import plan_registrations, read_tree_csv  # noqa: E402

RESULTS = ROOT / "data" / "results"
GAS = RESULTS / "gas.csv"
META = RESULTS / "run_meta.json"
TREE = ROOT / "data" / "hf_tree.csv"

pytestmark = pytest.mark.skipif(not GAS.exists(), reason="no data/results/gas.csv yet")


@pytest.fixture(scope="module")
def rows():
    with GAS.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def meta():
    return json.loads(META.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def groups(rows):
    """Rows split by (design, batch_size), in file order."""
    out = defaultdict(list)
    for r in rows:
        out[(r["design"], int(r["batch_size"]))].append(r)
    return out


def test_results_come_from_the_committed_tree(meta):
    # The replay records the SHA-256 of the tree it read. If the tree changed after the
    # replay, the gas numbers describe a different set of models.
    assert meta["tree_file_sha256"] == hash_file(TREE)


def test_every_design_registered_every_planned_model(groups, meta):
    plan, excluded = plan_registrations(read_tree_csv(TREE))
    assert meta["n_registered"] == len(plan)
    assert sum(meta["excluded_by_reason"].values()) == len(excluded)
    expected = {("storage", 1), ("event", 1)} | {("merkle", k) for k in meta["batch_sizes"]}
    assert set(groups) == expected
    for key, g in groups.items():
        assert len(g) == len(plan), key


def test_same_models_in_same_order_in_every_design(groups):
    orders = {key: [r["model_id"] for r in g] for key, g in groups.items()}
    first = orders[("storage", 1)]
    for key, order in orders.items():
        assert order == first, key


def test_merkle_gas_per_model_is_batch_gas_divided_by_batch_size(groups):
    for (design, k), g in groups.items():
        if design != "merkle":
            continue
        batches = defaultdict(list)
        for r in g:
            batches[int(r["batch_index"])].append(r)
        for b, members in batches.items():
            tx_gas = int(members[0]["tx_gas"])  # the batch's gas is on its first row only
            assert all(int(r["tx_gas"]) == 0 for r in members[1:])
            assert len(members) <= k
            for r in members:
                assert float(r["gas_per_model"]) == pytest.approx(tx_gas / len(members), abs=0.1)


def test_per_model_designs_report_their_own_transaction(groups):
    for key in (("storage", 1), ("event", 1)):
        for r in groups[key]:
            assert int(r["tx_gas"]) == float(r["gas_per_model"]) > 21_000  # base cost of any tx


def test_storage_costs_more_than_event_for_every_model(groups):
    for s, e in zip(groups[("storage", 1)], groups[("event", 1)]):
        assert float(s["gas_per_model"]) > float(e["gas_per_model"]), s["model_id"]


def test_bigger_merkle_batches_are_cheaper_per_model(groups, meta):
    means = []
    for k in sorted(meta["batch_sizes"]):
        g = groups[("merkle", k)]
        means.append(sum(float(r["gas_per_model"]) for r in g) / len(g))
    assert means == sorted(means, reverse=True)
