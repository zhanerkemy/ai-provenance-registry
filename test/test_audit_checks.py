"""Runs src/audit_checks.py on a private Anvil chain and checks the guarantee table.

If someone changes a contract and a guarantee appears or disappears, this test fails,
so the table in the paper can never silently disagree with the code. Uses the `w3`
fixture from test/conftest.py: skipped if Foundry is missing or `forge build` was not run.

Run with:  python -m pytest test/test_audit_checks.py -v
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# What we expect each design to do (measurement plan, "Guarantee checks").
EXPECTED = {
    #  check                 storage   event             merkle
    1: ("tamper",            "yes",    "off-chain only", "with proof"),
    2: ("duplicate",         "yes",    "no",             "no"),
    3: ("missing parent",    "yes",    "yes",            "no"),
    4: ("zero hash",         "yes",    "yes",            "no"),
    5: ("contract can check", "yes",   "no",             "with proof"),
    6: ("lineage on-chain",  "yes",    "off-chain only", "with proof"),
    7: ("ownership transfer", "yes",   "no",             "no"),
}


@pytest.fixture(scope="module")
def rows(w3):
    if not (ROOT / "out" / "VerifyProbe.sol" / "VerifyProbe.json").exists():
        pytest.skip("VerifyProbe not compiled (run `forge build`)")
    from audit_checks import Records, run_all

    return run_all(w3, Records(ROOT / "data" / "hf_tree.csv"))


def test_every_check_ran_for_every_design(rows):
    assert len(rows) == len(EXPECTED) * 3
    assert {(r["check_id"], r["design"]) for r in rows} == {
        (c, d) for c in EXPECTED for d in ("storage", "event", "merkle")}


@pytest.mark.parametrize("check_id", sorted(EXPECTED))
def test_guarantee_table(rows, check_id):
    _, storage, event, merkle = EXPECTED[check_id]
    got = {r["design"]: r["result"] for r in rows if r["check_id"] == check_id}
    assert got == {"storage": storage, "event": event, "merkle": merkle}, \
        [r["evidence"] for r in rows if r["check_id"] == check_id]


def test_storage_keeps_every_guarantee(rows):
    # Our baseline: if this fails, ModelRegistry lost a check it is supposed to have.
    assert all(r["result"] == "yes" for r in rows if r["design"] == "storage")


def test_evidence_is_recorded(rows):
    assert all(r["evidence"] for r in rows)
