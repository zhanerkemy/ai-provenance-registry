"""Write every number the paper's text quotes as a LaTeX macro, straight from the results.

Figures and tables already come from scripts. This does the same for the numbers inside
sentences ("1,071 of 1,369 models", "Merkle is cheaper from k = 3"), so that no number
in the paper is typed by hand (Stage 4: every claim must come from the repository).

Usage (from the repository root):
    python src/make_numbers.py

Reads   data/hf_tree_meta.json
        data/results/{tree_stats.json, gas.csv, gas_model.json, verify_gas.csv,
                      guarantees.csv, run_meta.json, chain_check.json (if present)}
Writes  figures/tables/numbers.tex

In the paper, once in the preamble:
    \\input{tables/numbers.tex}
and then in the text:
    Of the \\result{tree.models} models, \\result{tree.registrable} can be registered.

A key that does not exist prints as a bold "??key" in the PDF instead of failing
silently, so a renamed key is easy to spot. The keys are listed in numbers.tex itself.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def num(x: float, digits: int = 0) -> str:
    """12345.6 -> '12{,}346'. Same format as make_tables.py, so text and tables agree."""
    return f"{x:,.{digits}f}".replace(",", "{,}")


def pct(share: float) -> str:
    """0.7823 -> '78.2\\%'."""
    return f"{100 * share:.1f}\\%"


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def tree_numbers(meta: dict, stats: dict) -> dict[str, str]:
    excluded = stats["excluded_by_reason"]
    top = stats["ancestor_not_registered_root_causes"]["top_blocking_models"][0]
    out = {
        "tree.base": r"\texttt{" + meta["base_model"] + "}",
        "tree.pulled": meta["pulled_at_utc"][:10],
        "tree.models": num(stats["n_models"]),
        "tree.maxdepth": str(stats["max_depth"]),
        "tree.registrable": num(stats["n_registrable"]),
        "tree.registrable.pct": pct(stats["share_registrable"]),
        "tree.weightshash.pct": pct(stats["share_with_weights_hash"]),
        "tree.datasets.pct": pct(stats["share_declaring_datasets"]),
        "tree.children.mean": f"{stats['mean_children_of_parents']:.1f}",
        "tree.excluded": num(sum(excluded.values())),
        "blocker.model": r"\texttt{" + top["model_id"] + "}",
        "blocker.blocked": num(top["descendants_blocked"]),
    }
    for reason, n in excluded.items():
        out["excluded." + reason.replace("_", "")] = num(n)
    for relation, n in stats["models_per_relation"].items():
        out["relation." + relation] = num(n)
    return out


def gas_numbers(gas_rows: list[dict], model: dict) -> dict[str, str]:
    per_model: dict[tuple[str, int], list[float]] = defaultdict(list)
    for r in gas_rows:
        per_model[(r["design"], int(r["batch_size"]))].append(float(r["gas_per_model"]))
    storage, event = mean(per_model[("storage", 1)]), mean(per_model[("event", 1)])
    out = {"gas.storage": num(storage), "gas.event": num(event),
           "ratio.storage.event": f"{storage / event:.1f}"}
    ks = sorted(k for d, k in per_model if d == "merkle")
    for k in ks:
        out[f"gas.merkle.{k}"] = num(mean(per_model[("merkle", k)]))
    out["merkle.kmax"] = str(ks[-1])
    out["ratio.storage.merklekmax"] = num(storage / mean(per_model[("merkle", ks[-1])]))

    fit = model["storage"]
    out.update({
        "fit.uriword": num(fit["coefficients"]["uri_words"]),
        "fit.datahash": num(fit["coefficients"]["has_data"]),
        "fit.rsquared": f"{fit['r_squared']:.4f}",
        "fit.maxresidual": num(fit["max_abs_residual"]),
        "evm.newslot": num(model["evm_reference"]["new_storage_slot"]),
        "merkle.cheaperfrom": str(model["merkle"]["cheaper_than_event_from_k"]),
    })
    return out


def verify_numbers(rows: list[dict]) -> dict[str, str]:
    one: dict[tuple[str, int], list[int]] = defaultdict(list)
    lineage: dict[tuple[str, int, int], list[int]] = defaultdict(list)
    for r in rows:
        key = (r["design"], int(r["batch_size"]))
        one[key].append(int(r["verify_gas"]))
        lineage[(*key, int(r["lineage_len"]))].append(int(r["lineage_gas"]))
    longest = max(n for _, _, n in lineage)
    out = {"lineage.longest": str(longest)}
    for (design, k), values in one.items():
        name = "storage" if design == "storage" else f"merkle.{k}"
        out[f"verify.{name}"] = num(mean(values))
        out[f"lineage.{name}"] = num(mean(lineage[(design, k, longest)]))
    kmax = max(k for d, k in one if d == "merkle")
    ratio = mean(lineage[("merkle", kmax, longest)]) / mean(lineage[("storage", 1, longest)])
    out["ratio.lineage.merklekmax.storage"] = f"{ratio:.1f}"
    return out


def guarantee_numbers(rows: list[dict]) -> dict[str, str]:
    """How many of the audit checks each design passes outright ("yes")."""
    total = len({r["check_id"] for r in rows})
    out = {"checks.total": str(total)}
    for design in sorted({r["design"] for r in rows}):
        out[f"checks.{design}.yes"] = str(sum(r["design"] == design and r["result"] == "yes"
                                              for r in rows))
    return out


def run_numbers(meta: dict, chain_check: dict | None) -> dict[str, str]:
    out = {"run.solc": meta["solc"].split("+")[0],
           "run.blocks": f"{meta['block_range'][0]}--{meta['block_range'][1]}"}
    if chain_check is not None:
        out["sepolia.compared"] = num(chain_check["transactions_compared"])
        out["sepolia.identical"] = num(chain_check["transactions_identical"])
    return out


def to_latex(values: dict[str, str]) -> str:
    lines = [
        "% Generated by src/make_numbers.py from data/results. Do not edit by hand.",
        "% Use in the text as \\result{key}; an unknown key prints as ??key.",
        r"\providecommand{\result}[1]{\ifcsname res:#1\endcsname"
        r"\csname res:#1\endcsname\else\textbf{??#1}\fi}",
    ]
    for key in sorted(values):
        lines.append(rf"\expandafter\def\csname res:{key}\endcsname{{{values[key]}}}")
    return "\n".join(lines) + "\n"


def collect(data: Path, results: Path) -> dict[str, str]:
    check_path = results / "chain_check.json"
    values = {}
    values.update(tree_numbers(read_json(data / "hf_tree_meta.json"),
                               read_json(results / "tree_stats.json")))
    values.update(gas_numbers(read_csv(results / "gas.csv"), read_json(results / "gas_model.json")))
    values.update(verify_numbers(read_csv(results / "verify_gas.csv")))
    values.update(guarantee_numbers(read_csv(results / "guarantees.csv")))
    values.update(run_numbers(read_json(results / "run_meta.json"),
                              read_json(check_path) if check_path.exists() else None))
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the paper's in-text numbers as LaTeX.")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--results", type=Path, default=Path("data/results"))
    parser.add_argument("--out", type=Path, default=Path("figures/tables/numbers.tex"))
    args = parser.parse_args()

    values = collect(args.data, args.results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(to_latex(values), encoding="utf-8", newline="\n")
    width = max(map(len, values))
    for key in sorted(values):
        print(f"  {key:<{width}}  {values[key]}")
    print(f"{len(values)} numbers written to {args.out}")


if __name__ == "__main__":
    main()
