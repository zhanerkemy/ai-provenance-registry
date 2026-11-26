"""Tests for src/make_extra_numbers.py: the paper's derived numbers and tables are current
and agree with each other and with the main results."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from make_extra_numbers import (collect, depth_table, sepolia_levels_table,  # noqa: E402
                                to_latex)

ROOT = Path(__file__).resolve().parents[1]
DATA, RESULTS, TABLES = ROOT / "data", ROOT / "data" / "results", ROOT / "figures" / "tables"


def as_number(text: str) -> float:
    return float(text.replace("{,}", "").replace("\\%", ""))


def test_committed_files_match_the_results():
    """Regenerate whenever a results file changes: python src/make_extra_numbers.py"""
    values, depth_rows, level_rows = collect(DATA, RESULTS)
    for name, text in [("extra_numbers.tex", to_latex(values)),
                       ("depth_table.tex", depth_table(depth_rows)),
                       ("sepolia_levels.tex", sepolia_levels_table(level_rows))]:
        assert (TABLES / name).read_text(encoding="utf-8") == text, f"{name} is stale"


def test_depth_table_adds_up_to_the_tree():
    stats = json.loads((RESULTS / "tree_stats.json").read_text(encoding="utf-8"))
    _, rows, _ = collect(DATA, RESULTS)
    assert sum(r["models"] for r in rows) == stats["n_models"]
    assert sum(r["registrable"] for r in rows) == stats["n_registrable"]


def test_sepolia_levels_cover_every_compared_transaction():
    check = json.loads((RESULTS / "chain_check.json").read_text(encoding="utf-8"))
    _, _, rows = collect(DATA, RESULTS)
    assert sum(n for _, _, n in rows) == check["transactions_compared"]


def test_first_transaction_premium_is_the_same_in_both_designs():
    """The finding the paper relies on: the first event registration and the first Merkle
    batch, the only transactions that write the counter from zero, pay the same extra gas."""
    values, _, _ = collect(DATA, RESULTS)
    assert values["sep.event.premium"] == values["sep.merkle.premium"]


def test_break_even_follows_from_its_parts():
    values, _, _ = collect(DATA, RESULTS)
    saving = as_number(values["regsaving.m128"])
    assert round(saving / as_number(values["extra.record.m128"])) == as_number(values["breakeven.record"])
    assert abs(saving / as_number(values["extra.lineage.m128"])
               - as_number(values["breakeven.lineage"])) < 0.05


def test_savings_agree_with_the_main_numbers():
    values, _, _ = collect(DATA, RESULTS)
    main = dict(re.findall(r"csname res:([^\\]+)\\endcsname\{(.*)\}$",
                           (TABLES / "numbers.tex").read_text(encoding="utf-8"), re.M))
    storage, event = as_number(main["gas.storage"]), as_number(main["gas.event"])
    assert abs(100 * (1 - event / storage) - as_number(values["save.event.vs.storage"])) < 0.1
