"""Checks of the statistics in src/scenarios.py."""

import numpy as np
import pandas as pd
import pytest

from src.scenarios import SCENARIOS, confidence_interval, paired_differences, run_all
from src.simulation import Params, load_catalogue, run_replication


def test_confidence_interval_by_hand():
    # 1..5: mean 3, s = sqrt(2.5) = 1.5811, t(0.975, 4) = 2.7764.
    # Half-width = 2.7764 * 1.5811 / sqrt(5) = 1.9632.
    mean, low, high = confidence_interval(np.array([1, 2, 3, 4, 5]))
    assert mean == 3
    assert (high - low) / 2 == pytest.approx(1.9632, abs=1e-4)


def test_paired_difference_matches_seeds():
    # B is always A + 2, but the seeds are listed in a different order.
    reps = pd.DataFrame({
        "scenario": ["A"] * 3 + ["B"] * 3,
        "seed": [1, 2, 3, 3, 1, 2],
        "x": [10.0, 20.0, 30.0, 32.0, 12.0, 22.0],
    })
    diff = paired_differences(reps, [("B", "A")], ["x"]).iloc[0]
    assert diff["mean_diff"] == pytest.approx(2.0)
    assert diff["paired_half_width"] == pytest.approx(0.0)  # same difference every seed
    assert diff["unpaired_half_width"] > 10                 # the seeds vary a lot


def test_common_random_numbers_narrow_the_interval():
    reps = run_all(seeds=list(range(1, 11)),
                   scenarios={k: SCENARIOS[k] for k in ("S1 judgement", "S2 rule")})
    d = paired_differences(reps, [("S2 rule", "S1 judgement")], ["totes_per_1000_units"]).iloc[0]
    assert d["mean_diff"] < 0                                # the rule uses fewer totes
    assert d["paired_half_width"] < d["unpaired_half_width"]


def test_split_by_binding_adds_up_to_the_total():
    p = Params(filling="judgement")
    skus = load_catalogue(p)
    res = run_replication(p, 5, skus)
    m = res.metrics
    weight_bound = {s.sku_id for s in skus if s.n_max < s.n_geometry}
    lines = res.lines
    units_w = lines.loc[lines["sku_id"].isin(weight_bound), "quantity"].sum()
    units_v = lines["quantity"].sum() - units_w
    combined = (m["totes_per_1000_units_weight_bound"] * units_w
                + m["totes_per_1000_units_volume_bound"] * units_v) / (units_w + units_v)
    assert combined == pytest.approx(m["totes_per_1000_units"])
