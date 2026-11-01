"""Fits gas = a + b*uri_words + c*has_data + d*is_base to the storage and event results
in data/results/gas.csv and compares the coefficients with EVM gas prices.
For Merkle it reports the gas per model for each batch size and the smallest k where
Merkle is cheaper than event logging. Run after src/replay.py: python src/gas_model.py
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

# EVM prices (gas), from the Ethereum specification; see the docstring.
SSTORE_SET = 20_000  # zero -> non-zero storage write (EIP-2200)
COLD_SLOT = 2_100  # first access to a storage slot in a transaction (EIP-2929)
WARM_NOOP = 100  # writing the value a slot already holds, once the slot is warm
SSTORE_RESET = 2_900  # non-zero -> different non-zero write (5,000 - 2,100), e.g. counter 1 -> 2
CALLDATA_NONZERO = 16  # per non-zero byte of call data
CALLDATA_ZERO = 4  # per zero byte of call data


def fit(rows: list[dict], features: list[str]) -> dict:
    """Least-squares fit of gas_per_model on an intercept plus `features`."""
    X = np.array([[1.0] + [float(r[f]) for f in features] for r in rows])
    y = np.array([float(r["gas_per_model"]) for r in rows])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coef
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return {
        "n": len(rows),
        "coefficients": {name: round(float(c), 1) for name, c in zip(["intercept"] + features, coef)},
        "r_squared": round(1 - ss_res / ss_tot, 6) if ss_tot else 1.0,
        "max_abs_residual": round(float(np.abs(y - pred).max()), 1),
    }


def add_features(rows: list[dict], has_data: dict[str, bool]) -> list[dict]:
    out = []
    for r in rows:
        out.append({**r,
                    "uri_words": math.ceil(int(r["uri_bytes"]) / 32),
                    "has_data": int(has_data[r["model_id"]]),
                    "is_base": int(int(r["depth"]) == 0)})
    return out


def merkle_summary(rows: list[dict], event_mean: float) -> dict:
    """Mean gas of a full batch for each k, cost per model, and the break-even k."""
    by_k: dict[int, list[int]] = {}
    for r in rows:
        if r["design"] == "merkle" and int(r["tx_gas"]) > 0:  # first row of each batch
            k = int(r["batch_size"])
            by_k.setdefault(k, []).append((int(r["batch_index"]), int(r["tx_gas"])))
    summary = {}
    for k, batches in sorted(by_k.items()):
        full = [gas for _, gas in sorted(batches)[:-1]] or [batches[0][1]]  # last batch may be partial
        mean_batch = sum(full) / len(full)
        summary[str(k)] = {"batches": len(batches), "mean_full_batch_gas": round(mean_batch, 1),
                           "gas_per_model": round(mean_batch / k, 1)}
    # Batch gas is nearly constant, so per-model cost is batch_gas / k. Use the k = 1 batch
    # as the single-record batch cost to find where it drops below the event design.
    single = summary.get("1", next(iter(summary.values())))["mean_full_batch_gas"]
    break_even = math.floor(single / event_mean) + 1
    return {"by_batch_size": summary,
            "cheaper_than_event_from_k": break_even,
            "note": "smallest k with (single-record batch gas) / k < mean event gas per model"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Decompose registration gas.")
    parser.add_argument("--gas", type=Path, default=Path("data/results/gas.csv"))
    parser.add_argument("--tree", type=Path, default=Path("data/hf_tree.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/results/gas_model.json"))
    args = parser.parse_args()

    with args.tree.open(newline="", encoding="utf-8") as f:
        has_data = {r["model_id"]: bool(r["data_ref_hash"]) for r in csv.DictReader(f)}
    with args.gas.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    storage = add_features([r for r in rows if r["design"] == "storage"], has_data)
    event = add_features([r for r in rows if r["design"] == "event"], has_data)
    event_mean = sum(float(r["gas_per_model"]) for r in event) / len(event)
    features = ["uri_words", "has_data", "is_base"]

    result = {
        "model": "gas = intercept + uri_words*b + has_data*c + is_base*d (least squares)",
        "storage": fit(storage, features),
        "event": fit(event, features),
        "merkle": merkle_summary(rows, event_mean),
        "evm_reference": {
            "new_storage_slot": SSTORE_SET + COLD_SLOT,
            "expected_has_data_storage": SSTORE_SET + COLD_SLOT - (COLD_SLOT + WARM_NOOP)
            + 32 * (CALLDATA_NONZERO - CALLDATA_ZERO),
            "expected_is_base_storage": (SSTORE_SET - SSTORE_RESET) - (SSTORE_SET + COLD_SLOT - (COLD_SLOT + WARM_NOOP)),
            "expected_is_base_event": SSTORE_SET - SSTORE_RESET,
            "note": "uri_words should cost about one new slot (22,100) plus 32 bytes of "
                    "call data (512) plus memory copying",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
