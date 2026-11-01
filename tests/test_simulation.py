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


def make_sku(params: Params, sku_id: str, dims: tuple[float, float, float], kg: float) -> Sku:
    """A test SKU with the packing rule applied to the tote and every compartment."""
    item = Item(*dims, kg)
    packing = units_per_tote(item, params.tote)
    compartments = {name: units_per_tote(item, tote)
                    for name, tote in params.compartment_totes().items()}
    return Sku(sku_id, kg, item.volume_mm3, packing.n_max, packing.n_geometry,
               {name: c.n_max for name, c in compartments.items()},
               {name: c.n_geometry for name, c in compartments.items()}, 1, 100, 1.0)


def cube_sku(params: Params) -> Sku:
    """100 mm cube, 1 kg, 15 kg tote of 560 x 360 x 200 mm.
    Whole tote: weight bound 15, grid 5 x 3 x 2 = 30, so n_max = 15 (weight-bound).
    Half across the length (280 x 360): 2 x 3 x 2 = 12.
    Half along the length (560 x 180): 5 x 1 x 2 = 10.
    Quarter (280 x 180): 2 x 1 x 2 = 4."""
    sku = make_sku(params, "CUBE", (100, 100, 100), 1.0)
    assert (sku.n_max, sku.n_geometry) == (15, 30)
    assert sku.compartment_n_max == {"half_length": 12, "half_width": 10, "quarter": 4}
    return sku


def test_deterministic_rule_matches_hand_calculation():
    # One line of 40 cubes: totes 15 + 15 + 10.
    # Busy time = setup 1.5 + 3 x (decide 0.1 + tote 1.0) + 40 units x 5 s
    #           = 1.5 + 3.3 + 3.333 = 8.133 min
    p = Params(filling="rule", dividers="none", **FIXED)
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
    p = Params(filling="judgement", dividers="none", f_low=1.1, f_mode=1.1, f_high=1.1, **FIXED)
    res = run_replication(p, seed=1, skus=[cube_sku(p)], lines=[OrderLine(0, 0.0, 0, 40)])
    m = res.metrics
    assert m["totes"] == 3
    assert m["overweight_rejections"] == 2
    assert m["rework_min"] == pytest.approx(2 * (1.5 + 2 / 12))
    # setup 1.5 + decide 3 x 0.5 + tote 3 x 1.0 + place 44 units + rework
    assert m["finish_min"] == pytest.approx(1.5 + 1.5 + 3.0 + 44 / 12 + 2 * (1.5 + 2 / 12))
    assert m["units_stored"] == 40


def run_cubes(quantities: list[int], dividers: str = "all", waiting_totes: int = 1) -> dict:
    """Rule, fixed times, one line of cubes every 20 minutes."""
    p = Params(filling="rule", dividers=dividers, waiting_totes=waiting_totes, **FIXED)
    lines = [OrderLine(i, 20.0 * i, 0, q) for i, q in enumerate(quantities)]
    return run_replication(p, seed=1, skus=[cube_sku(p)], lines=lines).metrics


def test_two_small_lines_share_a_divided_tote():
    # 5 + 5 cubes: too many for a quarter (4), so the bigger half (12). Together 10 kg. One tote.
    m = run_cubes([5, 5])
    assert (m["totes"], m["totes_half_length"], m["units_stored"]) == (1, 1, 10)
    assert m["empty_compartments"] == 0


def test_a_halved_tote_has_only_two_halves():
    # 5 + 5 + 5: the first two share a tote, the third starts a new one (one half left empty).
    m = run_cubes([5, 5, 5])
    assert (m["totes"], m["totes_divided"], m["empty_compartments"]) == (2, 2, 1)


def test_four_small_lines_share_a_quarter_tote():
    # 3 cubes fit in a quarter (4). Four lines of 3 = 12 kg <= 15 kg. One tote.
    m = run_cubes([3, 3, 3, 3])
    assert (m["totes"], m["totes_quarter"], m["empty_compartments"]) == (1, 1, 0)


def test_leftover_that_does_not_fit_sends_the_waiting_tote():
    # 3 cubes open a quarter tote. 5 do not fit a quarter, so the quarter tote leaves
    # with 3 empty quarters and a new half tote starts. It leaves at the end, one half empty.
    m = run_cubes([3, 5])
    assert (m["totes"], m["totes_quarter"], m["totes_half_length"]) == (2, 1, 1)
    assert m["empty_compartments"] == 3 + 1


def test_second_compartment_must_respect_the_weight_limit():
    # 10 + 10 cubes: each fits in a half, but together 20 kg > 15 kg. Two totes.
    m = run_cubes([10, 10])
    assert (m["totes"], m["overweight_rejections"]) == (2, 0)


def test_leftover_too_big_for_a_half_gets_its_own_tote():
    # 13 cubes do not fit in any compartment (best half 12), so they fill a single-SKU tote.
    m = run_cubes([13, 5])
    assert (m["totes"], m["totes_divided"]) == (2, 1)


def test_two_waiting_totes_let_small_leftovers_pair_up():
    # Lines 3, 5, 3, 5 cubes.
    # One waiting tote: quarter(3) leaves with 3 empty quarters when 5 arrive. Half(5) takes
    # the next 3 in its free half and leaves full. The last 5 start a new half tote. 3 totes.
    one = run_cubes([3, 5, 3, 5], waiting_totes=1)
    assert (one["totes"], one["empty_compartments"]) == (3, 3 + 1)
    # Two waiting totes: the quarter tote and the half tote wait side by side. The second 3
    # goes into the quarter tote (smallest compartment that fits), the second 5 fills the
    # half tote. 2 totes.
    two = run_cubes([3, 5, 3, 5], waiting_totes=2)
    assert (two["totes"], two["empty_compartments"]) == (2, 2)


def test_full_desk_sends_the_tote_with_fewest_empty_compartments():
    # Two waiting totes. 3 -> quarter tote A. 5 -> half tote B. 3 -> A (2 of 4 used).
    # 11 needs a half, B's free half would make 16 kg > 15, so a new tote is needed and the
    # desk is full. B has 1 empty compartment, A has 2, so B leaves. 11 start half tote C.
    # At the end A and C leave. Empty compartments: B 1 + A 2 + C 1 = 4.
    m = run_cubes([3, 5, 3, 11], waiting_totes=2)
    assert (m["totes"], m["totes_quarter"], m["totes_half_length"]) == (3, 1, 2)
    assert m["empty_compartments"] == 4


def test_without_dividers_each_leftover_gets_its_own_tote():
    assert run_cubes([5, 5], dividers="none")["totes"] == 2


def test_halves_only_cannot_use_quarters():
    m = run_cubes([3, 3, 3, 3], dividers="halves")
    assert (m["totes"], m["totes_quarter"]) == (2, 0)


def test_long_item_uses_the_half_along_the_length():
    # 500 x 80 x 80 mm, 1 kg. It is longer than 360 mm, so it fits neither a quarter
    # (280 x 180) nor a half across the length (280 x 360). It fits the half along the
    # length (560 x 180): 1 x 2 x 2 = 4. Whole tote: 1 x 4 x 2 = 8.
    p = Params(filling="rule", **FIXED)
    sku = make_sku(p, "LONG", (500, 80, 80), 1.0)
    assert sku.compartment_n_max == {"half_length": 0, "half_width": 4, "quarter": 0}
    m = run_replication(p, seed=1, skus=[sku], lines=[OrderLine(0, 0.0, 0, 3)]).metrics
    assert (m["totes"], m["totes_half_width"]) == (1, 1)


@pytest.mark.parametrize("filling", ["rule", "judgement"])
@pytest.mark.parametrize("dividers", ["none", "halves", "all"])
@pytest.mark.parametrize("n_workers", [1, 2])
@pytest.mark.parametrize("waiting_totes", [1, 2])
def test_units_in_equal_units_stored(filling, dividers, n_workers, waiting_totes):
    p = Params(filling=filling, dividers=dividers, n_workers=n_workers,
               waiting_totes=waiting_totes, arrival_rate_per_h=6.0)
    skus = load_catalogue(p)
    for seed in range(5):
        m = run_replication(p, seed, skus).metrics
        assert m["units_in"] == m["units_stored"]
        assert m["share_idle"] >= -1e-9  # busy time fits inside the measured window


def test_no_tote_over_the_limit_reaches_storage():
    p = Params(filling="judgement", dividers="all", f_mode=1.05, f_low=0.9, f_high=1.3)
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
    p = Params(filling="rule", dividers="none", arrival_rate_per_h=1.0)
    skus = load_catalogue(p)
    offered = p.arrival_rate_per_h / 60 * expected_work_per_line(p, skus)
    measured = np.mean([run_replication(p, s, skus).metrics["worker_utilisation"]
                        for s in range(500)])
    assert measured == pytest.approx(offered, rel=0.05)


def test_littles_law():
    # Time-average number of lines in the system L = arrival rate x mean time in system.
    p = Params(filling="judgement", dividers="all", arrival_rate_per_h=6.0, sample_dt=0.1)
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
