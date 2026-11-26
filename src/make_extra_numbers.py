"""Derived numbers and two tables that the paper quotes but src/make_numbers.py does not
produce: savings and ratios, totals, partial batches, amortised deployment, per-generation
lineage slopes, the verification break-even, the arrival rate of new models, the Sepolia
step pattern, and a worked example. Nothing is typed by hand: every value is computed
from the committed files in data/ (Stage 4: every claim must come from the repository).

Usage (from the repository root):
    python src/make_extra_numbers.py

Reads   data/hf_tree.csv, data/hf_tree_meta.json and data/results/{gas.csv,
        verify_gas.csv, run_meta.json, tree_stats.json, chain_check.json}
Writes  figures/tables/extra_numbers.tex    macros, used in the text as \\xres{key}
        figures/tables/depth_table.tex      Table: tree composition and registrability by depth
        figures/tables/sepolia_levels.tex   Table: Sepolia minus Anvil gas per transaction

In the paper, after \\input{tables/numbers.tex}, add \\input{tables/extra_numbers.tex}.
An unknown key prints as a bold ??key, like \\result{key}.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(x: float, digits: int = 0) -> str:
    return f"{x:,.{digits}f}".replace(",", "{,}")


def pct(x: float, digits: int = 1) -> str:
    return f"{100 * x:.{digits}f}\\%"


def mean(v):
    v = list(v)
    return sum(v) / len(v)


def ols_slope(xs, ys):
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    return my - b * mx, b


def depth_table(rows: list[dict]) -> str:
    lines = [r"\begin{tabular}{rrrrrr}", r"\toprule",
             r"Depth & Models & With weight hashes & Registrable & Share & With data hash \\",
             r"\midrule"]
    for r in rows:
        lines.append(f"{r['depth']} & {num(r['models'])} & {num(r['hashes'])} & "
                     f"{num(r['registrable'])} & {r['share']}\\% & {num(r['with_data'])} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def sepolia_levels_table(rows: list[tuple[str, int, int]]) -> str:
    lines = [r"\begin{tabular}{lrr}", r"\toprule",
             r"Transaction & Difference (gas) & Count \\", r"\midrule"]
    for label, diff, n in rows:
        lines.append(f"{label} & {num(diff)} & {n} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def sepolia_levels(diffs: list[dict], gas: list[dict], by_id: dict) -> list[tuple[str, int, int]]:
    """Group the per-transaction differences into labelled levels. Merkle k = 1 and k = 8
    are combined (they showed identical differences). Storage rows are labelled by what
    decides how many new slots a record writes: base model or not, data hash declared
    or not, and the number of 32-byte URI words."""
    uri = {r["model_id"]: int(r["uri_bytes"]) for r in gas if r["design"] == "storage"}
    first = {(r["design"], int(r["batch_size"])): r["model_id"]   # the row carrying the gas
             for r in gas if r["batch_index"] == "0" and int(r["tx_gas"]) > 0}
    groups: dict[tuple, Counter] = defaultdict(Counter)
    for d in diffs:
        m = d["model_id"]
        if d["design"] == "storage":
            if not by_id[m]["parent_id"]:
                label = "Storage, base model"
            else:
                data = "data hash" if by_id[m]["data_ref_hash"] else "no data hash"
                label = f"Storage, {data}, {math.ceil(uri[m] / 32)}-word URI"
        else:
            is_first = first[(d["design"], int(d["batch_size"]))] == m
            label = {("event", False): "Event-only, later registrations",
                     ("event", True): "Event-only, first registration",
                     ("merkle", False): "Merkle batch, later",
                     ("merkle", True): "Merkle batch, first"}[(d["design"], is_first)]
        groups[label][d["difference"]] += 1
    rows = []
    for label, counts in groups.items():
        if len(counts) != 1:
            raise ValueError(f"{label}: transactions in one group differ ({dict(counts)}); "
                             "the grouping no longer explains the differences")
        (diff, n), = counts.items()
        rows.append((label, diff, n))
    order = ["Event-only", "Merkle", "Storage"]   # as in the paper's table, then by size
    return sorted(rows, key=lambda r: (order.index(r[0].split()[0].rstrip(",")), r[1]))


def collect(data: Path, results: Path) -> tuple[dict[str, str], list[dict], list[tuple]]:
    res = results
    gas = read_csv(res / "gas.csv")
    ver = read_csv(res / "verify_gas.csv")
    tree = read_csv(data / "hf_tree.csv")
    meta = json.loads((res / "run_meta.json").read_text(encoding="utf-8"))
    tmeta = json.loads((data / "hf_tree_meta.json").read_text(encoding="utf-8"))
    chk = json.loads((res / "chain_check.json").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    diffs = chk["differences"]

    # ---- registration: means are total gas / registered models (row-weighted) -------
    per: dict[tuple, list[float]] = defaultdict(list)
    txg: dict[tuple, int] = defaultdict(int)
    ntx: dict[tuple, int] = defaultdict(int)
    for r in gas:
        key = (r["design"], int(r["batch_size"]))
        per[key].append(float(r["gas_per_model"]))
        txg[key] += int(r["tx_gas"])
        ntx[key] += int(r["tx_gas"]) > 0
    n_models = len(per[("storage", 1)])
    tot = {k: txg[k] / n_models for k in txg}  # total gas / models
    S, E = tot[("storage", 1)], tot[("event", 1)]
    M = {k: tot[("merkle", k)] for k in (1, 8, 32, 128)}
    out["save.event.vs.storage"] = pct(1 - E / S)
    out["save.m128.vs.storage"] = pct(1 - M[128] / S, 2)
    out["save.m128.vs.event"] = pct(1 - M[128] / E)
    out["save.m8.vs.event"] = pct(1 - M[8] / E)
    out["save.m32.vs.event"] = pct(1 - M[32] / E)
    out["ratio.m1.vs.event"] = f"{M[1] / E:.2f}"
    out["ratio.storage.m8"] = f"{S / M[8]:.1f}"
    for k in (1, 8, 32, 128):
        out[f"ntx.m{k}"] = num(ntx[("merkle", k)])
    out["ntx.perdesign"] = num(ntx[("storage", 1)])
    out["total.storage"] = num(txg[("storage", 1)])
    out["total.event"] = num(txg[("event", 1)])
    out["total.m128"] = num(txg[("merkle", 128)])

    # last (partial) batch occupancy
    for k in (8, 32, 128):
        occ = Counter(int(r["batch_index"]) for r in gas
                      if r["design"] == "merkle" and int(r["batch_size"]) == k)
        out[f"lastbatch.m{k}"] = str(occ[max(occ)])

    # steady-state batch gas (all batches except the first, any k)
    later, first = [], []
    for r in gas:
        if r["design"] == "merkle" and int(r["tx_gas"]) > 0:
            (first if int(r["batch_index"]) == 0 else later).append(int(r["tx_gas"]))
    out["batch.later.min"] = num(min(later))
    out["batch.later.max"] = num(max(later))
    out["batch.first.min"] = num(min(first))
    out["batch.first.max"] = num(max(first))
    out["m128.fullbatch.permodel"] = num(max(later) / 128)

    # deployment, amortised over the registered models
    dep = {(c["design"], c["batch_size"]): c["deploy_gas"] for c in meta["contracts"]}
    out["deploy.amort.storage"] = num(dep[("storage", 1)] / n_models)
    out["deploy.amort.event"] = num(dep[("event", 1)] / n_models)
    out["deploy.amort.merkle"] = num(dep[("merkle", 128)] / n_models)
    out["m128.with.deploy"] = num(M[128] + dep[("merkle", 128)] / n_models)

    # ---- dataset ----------------------------------------------------------------------
    by_id = {r["model_id"]: r for r in tree}
    reg_ids = [r["model_id"] for r in gas if r["design"] == "storage"]
    with_data = sum(1 for m in reg_ids if by_id[m]["data_ref_hash"])
    out["reg.withdata"] = num(with_data)
    out["reg.withdata.pct"] = pct(with_data / len(reg_ids))
    out["reg.descendants"] = num(len(reg_ids) - 1)
    children = Counter(r["parent_id"] for r in tree if r["parent_id"])
    top, top_n = children.most_common(1)[0]
    out["children.max"] = num(top_n)
    out["children.max.model"] = r"\texttt{" + top + "}"
    out["reached.twice"] = str(tmeta["children_reached_twice"])
    uri = [int(r["uri_bytes"]) for r in gas if r["design"] == "storage"]
    out["uri.min"], out["uri.max"] = str(min(uri)), str(max(uri))
    out["uri.median"] = num(sorted(uri)[len(uri) // 2])
    depth_reg = Counter(int(r["depth"]) for r in gas if r["design"] == "storage")
    out["reg.depth4"] = num(depth_reg[4])
    out["tree.depth4"] = num(sum(1 for r in tree if r["depth"] == "4"))
    mp_rel = Counter(r["relation"] for r in tree if r["status"] == "multi_parent")
    out["multiparent.nonmerge"] = num(sum(v for k, v in mp_rel.items() if k != "merge"))

    # ---- verification -----------------------------------------------------------------
    out["verify.sample"] = num(len({r["model_id"] for r in ver}))
    mk = [r for r in ver if r["design"] == "merkle"]
    _, slope = ols_slope([int(r["proof_len"]) for r in mk], [int(r["verify_gas"]) for r in mk])
    out["verify.perproofhash"] = num(slope)
    st = [r for r in ver if r["design"] == "storage"]
    b0, b1 = ols_slope([int(r["lineage_len"]) for r in st], [int(r["lineage_gas"]) for r in st])
    out["lineage.storage.pergen"] = num(b1)
    out["lineage.storage.len1"] = num(mean(int(r["lineage_gas"]) for r in st if r["lineage_len"] == "1"))
    for k in (1, 128):
        rows = [r for r in mk if int(r["batch_size"]) == k]
        _, s = ols_slope([int(r["lineage_len"]) for r in rows], [int(r["lineage_gas"]) for r in rows])
        out[f"lineage.m{k}.pergen"] = num(s)
    pl = [int(r["proof_len"]) for r in mk if int(r["batch_size"]) == 128]
    out["prooflen.m128.min"], out["prooflen.m128.max"] = str(min(pl)), str(max(pl))

    # transaction-level estimate_gas of a direct verification call (gas.csv)
    est = defaultdict(list)
    for r in gas:
        if r["verify_gas"]:
            est[(r["design"], int(r["batch_size"]))].append(int(r["verify_gas"]))
    out["est.storage"] = num(mean(est[("storage", 1)]))
    out["est.storage.n"] = str(len(est[("storage", 1)]))
    for k in (1, 8, 32, 128):
        out[f"est.m{k}"] = num(mean(est[("merkle", k)]))

    # indicative break-even (probe-level; see caveats in the paper)
    v_s = mean(int(r["verify_gas"]) for r in st)
    v_m = mean(int(r["verify_gas"]) for r in mk if int(r["batch_size"]) == 128)
    longest = max(int(r["lineage_len"]) for r in ver)
    l_s = mean(int(r["lineage_gas"]) for r in st if int(r["lineage_len"]) == longest)
    l_m = mean(int(r["lineage_gas"]) for r in mk
               if int(r["batch_size"]) == 128 and int(r["lineage_len"]) == longest)
    gap = S - M[128]
    out["regsaving.m128"] = num(gap)
    out["breakeven.record"] = num(gap / (v_m - v_s))
    out["breakeven.lineage"] = f"{gap / (l_m - l_s):.1f}"
    out["extra.record.m128"] = num(v_m - v_s)
    out["extra.lineage.m128"] = num(l_m - l_s)

    # ---- Sepolia step structure ------------------------------------------------------
    ev = sorted(d["difference"] for d in diffs if d["design"] == "event")
    out["sep.event.later"] = num(min(ev))
    out["sep.event.first"] = num(max(ev))
    out["sep.event.premium"] = num(max(ev) - min(ev))
    mdf = sorted(d["difference"] for d in diffs if d["design"] == "merkle")
    out["sep.merkle.later"] = num(min(mdf))
    out["sep.merkle.first"] = num(max(mdf))
    out["sep.merkle.premium"] = num(max(mdf) - min(mdf))
    sdf = sorted({d["difference"] for d in diffs if d["design"] == "storage"})
    out["sep.storage.levels"] = ", ".join(num(x) for x in sdf)
    steps = [b - a for a, b in zip(sdf[1:], sdf[2:])]  # skip the base-model level
    out["sep.storage.step.min"] = num(min(steps))
    out["sep.storage.step.max"] = num(max(steps))
    out["eip8037.setdelta"] = num(97_920 - 20_000)
    out["sep.compared"] = str(chk["transactions_compared"])
    out["sep.blocks"] = f"{chk['sepolia_block_range'][0]}--{chk['sepolia_block_range'][1]}"
    out["sep.runat"] = chk["sepolia_run_at_utc"][:10]
    out["anvil.runat"] = chk["anvil_run_at_utc"][:10]

    # arrival rate of registrable models (creation dates on the Hub), last 365 days
    snap = datetime.fromisoformat(tmeta["pulled_at_utc"])
    created = [datetime.fromisoformat(by_id[m]["created_at"]) for m in reg_ids if by_id[m]["created_at"]]
    n365 = sum(1 for d in created if (snap - d).days < 365)
    rate = n365 / 365
    out["arrivals.365"] = num(n365)
    out["arrivals.perday"] = f"{rate:.2f}"
    for k in (8, 32, 128):
        out[f"fill.days.m{k}"] = num(k / rate)
    out["created.first"] = min(created).date().isoformat()

    # worked example: first sampled model (file order) with four on-chain generations
    ex = next(r for r in ver if r["design"] == "storage" and r["lineage_len"] == "4")
    mid = ex["model_id"]
    g = {(r["design"], int(r["batch_size"])): r for r in gas if r["model_id"] == mid}
    v32 = next(r for r in ver if r["design"] == "merkle" and r["batch_size"] == "32" and r["model_id"] == mid)
    out["ex.model"] = r"\texttt{" + mid + "}"
    out["ex.depth"] = ex["depth"]
    out["ex.relation"] = by_id[mid]["relation"]
    out["ex.uribytes"] = g[("storage", 1)]["uri_bytes"]
    out["ex.hasdata"] = "declares" if by_id[mid]["data_ref_hash"] else "does not declare"
    out["ex.storage"] = num(float(g[("storage", 1)]["gas_per_model"]))
    out["ex.event"] = num(float(g[("event", 1)]["gas_per_model"]))
    out["ex.m32"] = num(float(g[("merkle", 32)]["gas_per_model"]))
    out["ex.verify.storage"] = num(int(ex["verify_gas"]))
    out["ex.lineage.storage"] = num(int(ex["lineage_gas"]))
    out["ex.verify.m32"] = num(int(v32["verify_gas"]))
    out["ex.proof.m32"] = v32["proof_len"]
    out["ex.lineage.m32"] = num(int(v32["lineage_gas"]))

    # per-depth table
    plan_ids = set(reg_ids)
    rows_d = []
    for d in sorted({int(r["depth"]) for r in tree}):
        at = [r for r in tree if int(r["depth"]) == d]
        reg = [r for r in at if r["model_id"] in plan_ids]
        rows_d.append({"depth": d, "models": len(at), "registrable": len(reg),
                       "share": f"{100 * len(reg) / len(at):.0f}",
                       "with_data": sum(1 for r in reg if r["data_ref_hash"]),
                       "hashes": sum(1 for r in at if r["weights_hash"])})
    return out, rows_d, sepolia_levels(diffs, gas, by_id)


def to_latex(values: dict[str, str]) -> str:
    lines = ["% Generated by src/make_extra_numbers.py from data/results. Do not edit by hand.",
             "% Use in the text as \\xres{key}; an unknown key prints as ??key.",
             r"\providecommand{\xres}[1]{\ifcsname xres:#1\endcsname"
             r"\csname xres:#1\endcsname\else\textbf{??#1}\fi}"]
    for k in sorted(values):
        lines.append(rf"\expandafter\def\csname xres:{k}\endcsname{{{values[k]}}}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the paper's derived numbers and tables.")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--results", type=Path, default=Path("data/results"))
    parser.add_argument("--out-dir", type=Path, default=Path("figures/tables"))
    args = parser.parse_args()

    values, depth_rows, level_rows = collect(args.data, args.results)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in [("extra_numbers.tex", to_latex(values)),
                       ("depth_table.tex", depth_table(depth_rows)),
                       ("sepolia_levels.tex", sepolia_levels_table(level_rows))]:
        (args.out_dir / name).write_text(text, encoding="utf-8", newline="\n")
    width = max(map(len, values))
    for key in sorted(values):
        print(f"  {key:<{width}}  {values[key]}")
    print(f"{len(values)} numbers, depth_table.tex and sepolia_levels.tex written to {args.out_dir}/")


if __name__ == "__main__":
    main()
