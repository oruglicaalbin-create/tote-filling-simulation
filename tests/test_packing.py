"""Hand-calculated checks of the packing rule.

All cases use the assumed standard tote: inner 560 x 360 x 200 mm, 35 kg.
The arithmetic for each case is written out in the comments.
"""

import pytest

from src.packing import (
    Item,
    Tote,
    fill_ratios,
    split_into_totes,
    totes_needed,
    units_per_tote,
)

TOTE = Tote(inner_length_mm=560, inner_width_mm=360, inner_height_mm=200, max_load_kg=35)


def test_volume_bound_lamp_box():
    # Lamp box 100 x 100 x 120 mm, 0.15 kg.
    # Weight: floor(35 / 0.15) = 233.
    # Upright (100,100,120): 5 * 3 * 1 = 15
    # On its side (100,120,100): 5 * 3 * 2 = 30   <- best
    # (120,100,100): 4 * 3 * 2 = 24
    r = units_per_tote(Item(100, 100, 120, 0.15), TOTE)
    assert r.n_weight == 233
    assert r.n_geometry == 30
    assert r.n_max == 30
    assert r.binding == "volume"


def test_weight_bound_screw_box():
    # Screw box 160 x 110 x 60 mm, 1.4 kg.
    # Weight: floor(35 / 1.4) = 25.
    # Best grid: (110,160,60) gives 5 * 2 * 3 = 30, as does (110,60,160) = 5 * 6 * 1.
    r = units_per_tote(Item(160, 110, 60, 1.4), TOTE)
    assert r.n_weight == 25
    assert r.n_geometry == 30
    assert r.n_max == 25
    assert r.binding == "weight"


def test_weight_bound_cable_coil():
    # Cable coil 200 x 200 x 100 mm, 8 kg.
    # Weight: floor(35 / 8) = 4.
    # (200,200,100): 2 * 1 * 2 = 4, (200,100,200): 2 * 3 * 1 = 6 <- best, (100,200,200): 5 * 1 * 1 = 5.
    r = units_per_tote(Item(200, 200, 100, 8.0), TOTE)
    assert r.n_geometry == 6
    assert r.n_max == 4
    assert r.binding == "weight"


def test_both_bounds_equal():
    # Box 280 x 180 x 100 mm, 4.375 kg.
    # Grid: 2 * 2 * 2 = 8. Weight: 35 / 4.375 = 8 exactly.
    r = units_per_tote(Item(280, 180, 100, 4.375), TOTE)
    assert (r.n_weight, r.n_geometry, r.n_max) == (8, 8, 8)
    assert r.binding == "both"


def test_item_too_large_is_flagged():
    # 600 mm is longer than every tote dimension, so every orientation gives 0.
    r = units_per_tote(Item(600, 100, 100, 1.0), TOTE)
    assert r.n_geometry == 0
    assert r.n_max == 0
    assert not r.fits
    assert r.binding == "does_not_fit"


def test_best_orientation_is_not_the_default():
    # Slim box 300 x 50 x 50 mm, 0.1 kg, given with its long side along the tote length.
    # As given (300,50,50): 1 * 7 * 4 = 28.
    # Turned (50,300,50): 11 * 1 * 4 = 44   <- best
    # Standing (50,50,300): 0 layers, too tall.
    r = units_per_tote(Item(300, 50, 50, 0.1), TOTE)
    assert r.n_geometry == 44
    assert r.orientation == (50, 300, 50)


def test_height_margin_reduces_capacity():
    # Same lamp box as above, but goods must stay 20 mm below the rim: usable height 180.
    # (100,120,100) now gives 5 * 3 * 1 = 15, and no orientation does better.
    tote = Tote(560, 360, 200, 35, height_margin_mm=20)
    r = units_per_tote(Item(100, 100, 120, 0.15), tote)
    assert r.n_geometry == 15


def test_weight_bound_survives_floating_point():
    # 35 / 0.35 may come out as 99.999... in floating point. It must count as 100.
    r = units_per_tote(Item(10, 10, 10, 0.35), TOTE)
    assert r.n_weight == 100


def test_totes_needed_zero_quantity():
    assert totes_needed(0, 30) == 0
    assert split_into_totes(0, 30) == []


def test_totes_needed_exact_multiple():
    assert totes_needed(90, 30) == 3
    assert split_into_totes(90, 30) == [30, 30, 30]


def test_totes_needed_with_partial_last_tote():
    assert totes_needed(100, 30) == 4
    assert split_into_totes(100, 30) == [30, 30, 30, 10]


def test_totes_needed_when_item_does_not_fit():
    with pytest.raises(ValueError):
        totes_needed(10, 0)


def test_fill_ratios():
    # 25 screw boxes of 1.4 kg = 35 kg, so the weight fill is exactly 1.
    item = Item(160, 110, 60, 1.4)
    by_weight, by_volume = fill_ratios(25, item, TOTE)
    assert by_weight == pytest.approx(1.0)
    assert by_volume == pytest.approx(25 * 160 * 110 * 60 / (560 * 360 * 200))
