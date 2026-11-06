"""Tests for src/reproduce.py: which regenerated files count as a real change."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reproduce import verdict  # noqa: E402


def test_nothing_changed():
    assert verdict([]) == ([], [])


def test_run_details_and_figures_are_expected_to_change():
    changed = ["data/results/run_meta.json", "figures/gas_per_model.png"]
    assert verdict(changed) == ([], changed)


def test_a_changed_result_is_a_failure():
    unexpected, expected = verdict(["data/results/gas.csv", "figures/verify_gas.png"])
    assert unexpected == ["data/results/gas.csv"]
    assert expected == ["figures/verify_gas.png"]


def test_tables_and_numbers_must_never_change():
    changed = ["figures/tables/gas_summary.tex", "figures/tables/numbers.tex"]
    assert verdict(changed) == (changed, [])
