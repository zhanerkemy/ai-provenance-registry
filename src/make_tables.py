"""Write the paper's tables as LaTeX, straight from the results files. Like the figures,
tables are never typed by hand: a number in the paper must come from a script (Stage 4).

Usage (from the repository root):
    python src/make_tables.py

Reads   data/results/{gas.csv, run_meta.json, verify_gas.csv, guarantees.csv}
Writes  figures/tables/gas_summary.tex   cost of registering and of checking, by design
        figures/tables/guarantees.tex    which audit checks each design keeps

In the paper (IEEEtran), with \\usepackage{booktabs} in the preamble:
    \\begin{table}[t]
      \\caption{...}\\label{tab:gas}
      \\input{tables/gas_summary.tex}
    \\end{table}
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

DESIGN_NAMES = {"storage": "Storage", "event": "Event-only", "merkle": "Merkle"}

# Short row names, so the guarantees table fits one column of an IEEE page.
# The full wording of each check is in data/results/guarantees.csv.
SHORT_CHECKS = {
    1: "Detects tampered weights",
    2: "Refuses duplicate weights",
    3: "Refuses unknown parent",
    4: "Refuses zero weights hash",
    5: "Checkable by a contract",
    6: "Lineage readable on-chain",
    7: "Per-model ownership transfer",
}
SHORT_RESULTS = {"off-chain only": "off-chain"}


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(x: float) -> str:
    """12345.6 -> '12{,}346' (thousands separator that LaTeX does not space oddly)."""
    return f"{x:,.0f}".replace(",", "{,}")


def label(design: str, k: int) -> str:
    return DESIGN_NAMES[design] if design != "merkle" else f"Merkle, $k={k}$"


def gas_summary(gas_rows: list[dict], verify_rows: list[dict], meta: dict) -> str:
    reg: dict[tuple[str, int], list[float]] = defaultdict(list)
    for r in gas_rows:
        reg[(r["design"], int(r["batch_size"]))].append(float(r["gas_per_model"]))
    check: dict[tuple[str, int], list[int]] = defaultdict(list)
    lineage: dict[tuple[str, int], dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in verify_rows:
        key = (r["design"], int(r["batch_size"]))
        check[key].append(int(r["verify_gas"]))
        lineage[key][int(r["lineage_len"])].append(int(r["lineage_gas"]))
    longest = max(int(r["lineage_len"]) for r in verify_rows)
    deploy = {(c["design"], c["batch_size"]): c["deploy_gas"] for c in meta.get("contracts", [])}

    order = [("storage", 1), ("event", 1)] + sorted(k for k in reg if k[0] == "merkle")
    lines = [
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r" & \multicolumn{2}{c}{Registration, gas per model} & Deployment"
        r" & \multicolumn{2}{c}{Check by a contract, gas} \\",
        r"\cmidrule(lr){2-3}\cmidrule(lr){5-6}",
        rf"Design & Mean & Range & gas & One record & {longest} generations \\",
        r"\midrule",
    ]
    for key in order:
        g = reg[key]
        if key in check:
            one = num(sum(check[key]) / len(check[key]))
            deep = lineage[key].get(longest)
            whole = num(sum(deep) / len(deep)) if deep else "--"
        else:
            one = whole = "not possible"
        dep = num(deploy[key]) if key in deploy else "--"
        lines.append(f"{label(*key)} & {num(sum(g) / len(g))} & {num(min(g))}--{num(max(g))}"
                     f" & {dep} & {one} & {whole} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def guarantees(rows: list[dict]) -> str:
    designs = ["storage", "event", "merkle"]
    checks: dict[int, str] = {}
    result: dict[tuple[int, str], str] = {}
    for r in rows:
        checks[int(r["check_id"])] = r["check"]
        result[(int(r["check_id"]), r["design"])] = r["result"]
    lines = [
        r"\setlength{\tabcolsep}{4pt}% tighter columns: fits one IEEE column at \footnotesize",
        r"\begin{tabular}{lccc}",
        r"\toprule",
        "Audit check & " + " & ".join(DESIGN_NAMES[d] for d in designs) + r" \\",
        r"\midrule",
    ]
    for cid in sorted(checks):
        cells = " & ".join(SHORT_RESULTS.get(result[(cid, d)], result[(cid, d)]) for d in designs)
        lines.append(f"{SHORT_CHECKS.get(cid, checks[cid])} & {cells} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the paper's LaTeX tables.")
    parser.add_argument("--results", type=Path, default=Path("data/results"))
    parser.add_argument("--out-dir", type=Path, default=Path("figures/tables"))
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    r = args.results
    (args.out_dir / "gas_summary.tex").write_text(gas_summary(
        read_csv(r / "gas.csv"), read_csv(r / "verify_gas.csv"),
        json.loads((r / "run_meta.json").read_text(encoding="utf-8"))), encoding="utf-8")
    (args.out_dir / "guarantees.tex").write_text(
        guarantees(read_csv(r / "guarantees.csv")), encoding="utf-8")
    print(f"Tables written to {args.out_dir}/")


if __name__ == "__main__":
    main()
