"""Offline tests for src/gas_model.py: the fit must recover coefficients we chose ourselves."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gas_model import add_features, fit, merkle_summary  # noqa: E402


def make_rows(a, b, c, d):
    """Fake gas.csv rows whose gas follows a + b*uri_words + c*has_data + d*is_base exactly."""
    rows, has_data = [], {}
    for i, (uri_bytes, data) in enumerate([(70, False), (72, True), (96, False), (100, True),
                                           (128, False), (130, True), (64, False)]):
        model = f"m{i}"
        has_data[model] = data
        words = -(-uri_bytes // 32)  # ceiling division
        gas = a + b * words + c * data + d * (i == 0)
        rows.append({"model_id": model, "depth": str(0 if i == 0 else 1), "batch_index": str(i),
                     "uri_bytes": str(uri_bytes), "gas_per_model": str(gas)})
    return rows, has_data


def test_fit_recovers_known_coefficients():
    rows, has_data = make_rows(a=145_000, b=22_800, c=20_200, d=-3_000)
    result = fit(add_features(rows, has_data), ["uri_words", "has_data", "is_base"])
    assert result["coefficients"] == pytest.approx(
        {"intercept": 145_000, "uri_words": 22_800, "has_data": 20_200, "is_base": -3_000}, abs=0.5)
    assert result["r_squared"] == pytest.approx(1.0)
    assert result["max_abs_residual"] == pytest.approx(0, abs=0.5)


def test_uri_words_rounds_up():
    rows, has_data = make_rows(1, 1, 1, 1)
    words = {r["uri_bytes"]: r["uri_words"] for r in add_features(rows, has_data)}
    assert words["64"] == 2 and words["70"] == 3 and words["96"] == 3 and words["100"] == 4


def test_merkle_break_even_and_partial_last_batch():
    # k = 1: three batches of 75,000. k = 8: one full batch (76,000) and a partial one.
    rows = [{"design": "merkle", "batch_size": "1", "batch_index": str(i), "tx_gas": "75000"}
            for i in range(3)]
    rows += [{"design": "merkle", "batch_size": "8", "batch_index": "0", "tx_gas": "76000"},
             {"design": "merkle", "batch_size": "8", "batch_index": "1", "tx_gas": "70000"}]
    out = merkle_summary(rows, event_mean=33_000)
    assert out["by_batch_size"]["8"]["mean_full_batch_gas"] == 76_000  # partial batch ignored
    assert out["by_batch_size"]["8"]["gas_per_model"] == 9_500
    assert out["cheaper_than_event_from_k"] == 3  # 75,000 / 2 > 33,000 but 75,000 / 3 < 33,000
