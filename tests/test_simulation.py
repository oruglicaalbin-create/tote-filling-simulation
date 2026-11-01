"""Sanity checks of the simulation (brief section 8)."""

import math

import numpy as np
import pytest

from src.packing import Item, units_per_tote
from src.simulation import (
    OrderLine, Params, Sku, generate_lines, load_catalogue, run_replication,
    triangular_from_uniform,
)

# Fixed times, no randomness in handling.
FIXED = dict(time_cv=0.0, max_load_kg=15.0)


def cube_sku(params: Params) -> Sku:
    """100 mm cube, 1 kg. In a 560 x 360 x 200 mm, 15 kg tote:
    weight bound 15, grid 5 x 3 x 2 = 30, so n_max = 15 (weight-bound).
    One half of a divided tote (280 x 360 x 200): grid 2 x 3 x 2 = 12, so 12 per half."""
    item = Item(100, 100, 100, 1.0)
    packing = units_per_tote(item, params.tote)
    half = units_per_tote(item, params.half_tote)
    assert (packing.n_max, packing.n_geometry) == (15, 30)
    assert (half.n_max, half.n_geometry) == (12, 12)
    return Sku("CUBE", 1.0, item.volume_mm3, packing.n_max, packing.n_geometry,
               half.n_max, half.n_geometry, 1, 100, 1.0)


def test_deterministic_rule_matches_hand_calculation():
    # One line of 40 cubes: totes 15 + 15 + 10.
    # Busy time = setup 1.5 + 3 x (decide 0.1 + tote 1.0) + 40 units x 5 s
    #           = 1.5 + 3.3 + 3.333 = 8.133 min
    p = Params(filling="rule", dividers=False, **FIXED)
    res = run_replication(p, seed=1, skus=[cube_sku(p)], lines=[OrderLine(0, 0.0, 0, 40)])
    m = res.metrics
    assert m["totes"] == 3
    assert m["overweight_rejections"] == 0
    assert m["finish_min"] == pytest.approx(1.5 + 3 * 1.1 + 40 / 12)
    assert m["units_stored"] == 40
    assert m["lifter_utilisation"] * p.shift_min == pytest.approx(3 * 60 / 400)


def test_deterministic_overfill_is_reworked():
    # Judgement with F fixed at 1.1: the worker puts round(16.5) = 17 cubes = 17 kg
    # in a tote. The conveyor rejects it, 2 units come out (rework 1.5 + 2 x 5 s).
    # Line of 40: 17 -> 15, 17 -> 15, then 10. Three totes, two rejections.
    p = Params(filling="judgement", dividers=False, f_low=1.1, f_mode=1.1, f_high=1.1, **FIXED)
    res = run_replication(p, seed=1, skus=[cube_sku(p)], lines=[OrderLine(0, 0.0, 0, 40)])
    m = res.metrics
    assert m["totes"] == 3
    assert m["overweight_rejections"] == 2
    assert m["rework_min"] == pytest.approx(2 * (1.5 + 2 / 12))
    # setup 1.5 + decide 3 x 0.5 + tote 3 x 1.0 + place 44 units + rework
    assert m["finish_min"] == pytest.approx(1.5 + 1.5 + 3.0 + 44 / 12 + 2 * (1.5 + 2 / 12))
    assert m["units_stored"] == 40


def run_cubes(quantities: list[int], dividers: bool = True) -> dict:
    """Rule, fixed times, one line of cubes every 20 minutes."""
    p = Params(filling="rule", dividers=dividers, **FIXED)
    lines = [OrderLine(i, 20.0 * i, 0, q) for i, q in enumerate(quantities)]
    return run_replication(p, seed=1, skus=[cube_sku(p)], lines=lines).metrics


def test_two_small_lines_share_a_divided_tote():
    # 5 + 5 cubes: each fits in a half (12), together 10 kg <= 15 kg. One tote.
    m = run_cubes([5, 5])
    assert (m["totes"], m["totes_divided"], m["units_stored"]) == (1, 1, 10)


def test_a_divided_tote_has_only_two_halves():
    # 5 + 5 + 5: the first two share a tote, the third starts a new one.
    m = run_cubes([5, 5, 5])
    assert (m["totes"], m["totes_divided"]) == (2, 2)


def test_second_half_must_respect_the_weight_limit():
    # 10 + 10 cubes: each fits in a half, but together 20 kg > 15 kg. Two totes.
    m = run_cubes([10, 10])
    assert (m["totes"], m["overweight_rejections"]) == (2, 0)


def test_leftover_too_big_for_a_half_gets_its_own_tote():
    # 13 cubes do not fit in a half (12), so they fill a single-SKU tote.
    m = run_cubes([13, 5])
    assert (m["totes"], m["totes_divided"]) == (2, 1)


def test_without_dividers_each_leftover_gets_its_own_tote():
    assert run_cubes([5, 5], dividers=False)["totes"] == 2


@pytest.mark.parametrize("filling", ["rule", "judgement"])
@pytest.mark.parametrize("dividers", [False, True])
@pytest.mark.parametrize("n_workers", [1, 2])
def test_units_in_equal_units_stored(filling, dividers, n_workers):
    p = Params(filling=filling, dividers=dividers, n_workers=n_workers, arrival_rate_per_h=6.0)
    skus = load_catalogue(p)
    for seed in range(5):
        m = run_replication(p, seed, skus).metrics
        assert m["units_in"] == m["units_stored"]


def test_no_tote_over_the_limit_reaches_storage():
    p = Params(filling="judgement", dividers=True, f_mode=1.05, f_low=0.9, f_high=1.3)
    skus = load_catalogue(p)
    m = run_replication(p, 3, skus).metrics
    assert m["overweight_rejections"] > 0
    assert m["fill_weight_max"] <= 1.0 + 1e-9


def expected_work_per_line(p: Params, skus: list[Sku]) -> float:
    """Mean worker minutes per line for the rule without dividers, by hand."""
    total = 0.0
    for s in skus:
        qs = range(s.qty_min, s.qty_max + 1)
        totes = np.mean([math.ceil(q / s.n_max) for q in qs])
        units = np.mean(list(qs))
        total += s.share * (p.t_line_setup + totes * (p.t_decide_rule + p.t_tote) + units * p.t_unit)
    return total


def test_utilisation_matches_offered_load_at_low_load():
    # Utilisation should be close to (lines per minute) x (work per line).
    # One shift at 1 line/h has only ~8 lines, so many replications are needed.
    p = Params(filling="rule", dividers=False, arrival_rate_per_h=1.0)
    skus = load_catalogue(p)
    offered = p.arrival_rate_per_h / 60 * expected_work_per_line(p, skus)
    measured = np.mean([run_replication(p, s, skus).metrics["worker_utilisation"]
                        for s in range(500)])
    assert measured == pytest.approx(offered, rel=0.05)


def test_littles_law():
    # Time-average number of lines in the system L = arrival rate x mean time in system.
    p = Params(filling="judgement", dividers=True, arrival_rate_per_h=6.0, sample_dt=0.1)
    skus = load_catalogue(p)
    for seed in range(3):
        res = run_replication(p, seed, skus)
        m = res.metrics
        ts = res.timeseries[res.timeseries["t_min"] < m["finish_min"]]
        L = ts["lines_in_system"].mean()
        lam = m["lines"] / m["finish_min"]
        assert L == pytest.approx(lam * m["lead_mean_min"], rel=0.03)


def test_common_random_numbers():
    rule = Params(filling="rule")
    judgement = Params(filling="judgement")
    skus = load_catalogue(rule)
    assert generate_lines(skus, rule, 7) == generate_lines(skus, judgement, 7)
    # A higher arrival rate keeps the same SKU and quantity for each line.
    normal = generate_lines(skus, Params(arrival_rate_per_h=4.0), 7)
    peak = generate_lines(skus, Params(arrival_rate_per_h=6.0), 7)
    assert [(x.sku, x.quantity) for x in normal] == [(x.sku, x.quantity) for x in peak[:len(normal)]]


def test_triangular_inverse_cdf():
    assert triangular_from_uniform(0.0, 0.6, 0.8, 1.1) == pytest.approx(0.6)
    assert triangular_from_uniform(1.0, 0.6, 0.8, 1.1) == pytest.approx(1.1)
    assert triangular_from_uniform(0.4, 0.6, 0.8, 1.1) == pytest.approx(0.8)  # cut = 0.2 / 0.5
    draws = [triangular_from_uniform(u, 0.6, 0.8, 1.1) for u in np.linspace(0, 1, 100001)]
    assert np.mean(draws) == pytest.approx((0.6 + 0.8 + 1.1) / 3, abs=1e-3)
