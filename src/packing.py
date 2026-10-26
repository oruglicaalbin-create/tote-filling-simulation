"""Packing rule: how many units of one SKU fit in one tote.

The rule is a simple heuristic, not full 3D bin packing:
- weight bound: floor(max_load / unit_weight)
- geometric bound: all units stand in the same orientation and form a
  regular grid (a "guillotine" layout). We try the 6 axis-aligned
  orientations and keep the best one.
The answer is the smaller of the two bounds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import permutations

# Small tolerance so that e.g. 35 / 0.35 counts as exactly 100 units
# even if floating point gives 99.99999999999999.
_EPS = 1e-9


@dataclass(frozen=True)
class Tote:
    inner_length_mm: float
    inner_width_mm: float
    inner_height_mm: float
    max_load_kg: float
    height_margin_mm: float = 0.0  # keep goods this far below the rim

    @property
    def usable_height_mm(self) -> float:
        return self.inner_height_mm - self.height_margin_mm

    @property
    def usable_volume_mm3(self) -> float:
        return self.inner_length_mm * self.inner_width_mm * self.usable_height_mm


@dataclass(frozen=True)
class Item:
    length_mm: float
    width_mm: float
    height_mm: float
    unit_weight_kg: float

    @property
    def volume_mm3(self) -> float:
        return self.length_mm * self.width_mm * self.height_mm


@dataclass(frozen=True)
class PackingResult:
    n_max: int                 # units per tote, min of the two bounds
    n_weight: int              # weight bound
    n_geometry: int            # geometric bound
    binding: str               # "weight", "volume", "both" or "does_not_fit"
    orientation: tuple[float, float, float]  # item (l, w, h) used for the best grid

    @property
    def fits(self) -> bool:
        return self.n_max > 0


def weight_capacity(item: Item, tote: Tote) -> int:
    """Largest number of units whose total weight stays within max load."""
    if item.unit_weight_kg <= 0:
        raise ValueError("unit weight must be positive")
    return math.floor(tote.max_load_kg / item.unit_weight_kg + _EPS)


def grid_count(dims: tuple[float, float, float], tote: Tote) -> int:
    """Units in a regular grid when the item stands in orientation dims = (l, w, h)."""
    l, w, h = dims
    along_length = math.floor(tote.inner_length_mm / l + _EPS)
    along_width = math.floor(tote.inner_width_mm / w + _EPS)
    layers = math.floor(tote.usable_height_mm / h + _EPS)
    return along_length * along_width * layers


def geometric_capacity(item: Item, tote: Tote) -> tuple[int, tuple[float, float, float]]:
    """Best grid count over the 6 orientations, and the orientation that gives it.

    Ties keep the first orientation found, so the item's own (l, w, h) wins a tie.
    """
    dims = (item.length_mm, item.width_mm, item.height_mm)
    best_count, best_orientation = 0, dims
    for orientation in permutations(dims):
        count = grid_count(orientation, tote)
        if count > best_count:
            best_count, best_orientation = count, orientation
    return best_count, best_orientation


def units_per_tote(item: Item, tote: Tote) -> PackingResult:
    """Apply the packing rule and report which constraint binds."""
    n_w = weight_capacity(item, tote)
    n_geo, orientation = geometric_capacity(item, tote)
    n_max = min(n_w, n_geo)

    if n_max == 0:
        binding = "does_not_fit"
    elif n_w < n_geo:
        binding = "weight"
    elif n_geo < n_w:
        binding = "volume"
    else:
        binding = "both"

    return PackingResult(n_max, n_w, n_geo, binding, orientation)


def totes_needed(quantity: int, n_max: int) -> int:
    """Totes needed for an inbound quantity, the last one possibly part-full."""
    if quantity < 0:
        raise ValueError("quantity cannot be negative")
    if quantity == 0:
        return 0
    if n_max <= 0:
        raise ValueError("item does not fit in the tote")
    return math.ceil(quantity / n_max)


def split_into_totes(quantity: int, n_max: int) -> list[int]:
    """Units in each tote, e.g. split_into_totes(100, 30) == [30, 30, 30, 10]."""
    if totes_needed(quantity, n_max) == 0:  # also checks the inputs
        return []
    full, rest = divmod(quantity, n_max)
    return [n_max] * full + ([rest] if rest else [])


def fill_ratios(units: int, item: Item, tote: Tote) -> tuple[float, float]:
    """(weight fill, volume fill) of a tote holding `units` units, both in [0, 1]."""
    by_weight = units * item.unit_weight_kg / tote.max_load_kg
    by_volume = units * item.volume_mm3 / tote.usable_volume_mm3
    return by_weight, by_volume
