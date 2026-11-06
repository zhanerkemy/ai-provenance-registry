"""Tests for src/make_numbers.py: the in-text numbers agree with the results and the tables."""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from make_numbers import collect, to_latex  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA, RESULTS = ROOT / "data", ROOT / "data" / "results"


def test_committed_numbers_match_the_results():
    """numbers.tex must be regenerated whenever a results file changes."""
    committed = (ROOT / "figures" / "tables" / "numbers.tex").read_text(encoding="utf-8")
    assert committed == to_latex(collect(DATA, RESULTS)), \
        "figures/tables/numbers.tex is stale: run python src/make_numbers.py"


def test_text_and_gas_table_quote_the_same_numbers():
    table = (ROOT / "figures" / "tables" / "gas_summary.tex").read_text(encoding="utf-8")
    values = collect(DATA, RESULTS)
    for key in ["gas.storage", "gas.event", "gas.merkle.1", "gas.merkle.128",
                "verify.storage", "lineage.storage", "lineage.merkle.128"]:
        assert values[key] in table, key


def test_counts_add_up():
    values = collect(DATA, RESULTS)
    as_int = {k: int(v.replace("{,}", "")) for k, v in values.items()
              if v.replace("{,}", "").isdigit()}
    assert as_int["tree.registrable"] + as_int["tree.excluded"] == as_int["tree.models"]
    excluded = sum(v for k, v in as_int.items() if k.startswith("excluded."))
    assert excluded == as_int["tree.excluded"]
    assert as_int["blocker.blocked"] <= as_int["excluded.ancestornotregistered"]


def test_sepolia_numbers_appear_only_after_the_sepolia_check(tmp_path):
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    (results / "chain_check.json").unlink(missing_ok=True)
    assert not any(k.startswith("sepolia.") for k in collect(DATA, results))

    (results / "chain_check.json").write_text(json.dumps(
        {"transactions_compared": 75, "transactions_identical": 75}), encoding="utf-8")
    values = collect(DATA, results)
    assert values["sepolia.compared"] == values["sepolia.identical"] == "75"


def test_unknown_key_is_visible_in_the_pdf():
    tex = to_latex({"gas.storage": "1"})
    assert r"\textbf{??#1}" in tex
    assert r"\csname res:gas.storage\endcsname{1}" in tex
