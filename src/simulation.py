"""Discrete-event simulation of one decanting station feeding an automated small-parts store.

What happens in the model:
- Order lines (one SKU, Q units) arrive as a Poisson process during one shift.
- They wait in a queue until a worker is free. Each worker fills totes for the line.
- Every tote compartment holds one SKU. With dividers on, a small leftover of a line
  goes into one half of a divided tote. The other half takes the next leftover that
  fits, then the tote is sent (decision D10 in CLAUDE.md).
- A tote is pushed onto the conveyor. An overweight tote is rejected there and the
  worker reworks it: removes units, pushes it again. Removed units go into the next tote.
- Accepted totes wait in a small buffer and the lifter takes them into storage.
  Each stored tote uses one storage location.

SimPy terms used below:
- env: the simulation clock and event list. Time jumps from event to event.
- process: a generator function. `yield env.timeout(d)` means "this takes d minutes".
- Store: a queue of objects. `get()` waits until an item is there, `put()` waits if full.

All times are in minutes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import simpy

from src.packing import Item, Tote, units_per_tote

CATALOGUE_PATH = Path(__file__).resolve().parent.parent / "data" / "sku_catalogue.csv"
_EPS = 1e-9

# Random number streams. Each order line gets its own fill-factor and handling-time
# stream, so a line sees the same random draws in every scenario (common random numbers).
_STREAM_ARRIVALS = 0
_STREAM_FILL = 1
_STREAM_TIMES = 2

ACTIVITIES = ("setup", "tote", "decide", "place", "rework", "blocked")


@dataclass(frozen=True)
class Params:
    """Every model input. Sources and reasons are in notes/assumptions_and_sources.md."""

    # Tote
    tote_length_mm: float = 560.0
    tote_width_mm: float = 360.0
    tote_height_mm: float = 200.0
    max_load_kg: float = 15.0
    # Demand
    shift_min: float = 480.0
    arrival_rate_per_h: float = 4.0  # order lines per hour at this station
    # Station
    n_workers: int = 1
    filling: str = "rule"  # "rule" or "judgement"
    dividers: bool = True  # a divider splits the tote length into two halves
    # Judgement fill factor F ~ triangular(low, mode, high), drawn per tote
    f_low: float = 0.65
    f_mode: float = 0.85
    f_high: float = 1.10
    # Handling times (mean, minutes)
    t_line_setup: float = 1.5   # read the delivery, unpack, scan
    t_tote: float = 1.0         # fetch an empty tote, label it, push it onto the conveyor
    t_decide_rule: float = 0.1  # read the number on the screen
    t_decide_judgement: float = 0.5
    t_unit: float = 5 / 60      # place one unit
    t_rework: float = 1.5       # fixed part of redoing a rejected tote
    time_cv: float = 0.3        # coefficient of variation of every handling time, 0 = fixed
    # Induction
    lifter_cycles_per_h: float = 400.0
    buffer_capacity: int = 10
    # Output
    sample_dt: float = 1.0  # minutes between queue-length samples

    @property
    def tote(self) -> Tote:
        return Tote(self.tote_length_mm, self.tote_width_mm, self.tote_height_mm, self.max_load_kg)

    @property
    def half_tote(self) -> Tote:
        """One compartment of a divided tote. The weight limit is still the whole tote's."""
        return Tote(self.tote_length_mm / 2, self.tote_width_mm, self.tote_height_mm, self.max_load_kg)

    @property
    def lifter_time(self) -> float:
        return 60.0 / self.lifter_cycles_per_h


@dataclass(frozen=True)
class Sku:
    sku_id: str
    weight_kg: float
    volume_mm3: float
    n_max: int        # packing rule result
    n_geometry: int   # most units that physically fit (grid bound)
    n_max_half: int       # packing rule in one half of a divided tote (0 = does not fit)
    n_geometry_half: int
    qty_min: int
    qty_max: int
    share: float


@dataclass(frozen=True)
class OrderLine:
    line_id: int
    arrival_min: float
    sku: int        # index into the SKU list
    quantity: int


@dataclass
class ToteLoad:
    """Contents of one tote: a list of [sku index, units]."""

    kind: str  # "single" or "divided"
    contents: list[list[int]] = field(default_factory=list)
    weight_kg: float = 0.0
    volume_mm3: float = 0.0

    @property
    def units(self) -> int:
        return sum(units for _, units in self.contents)


def rng_for(seed: int, *keys: int) -> np.random.Generator:
    """Independent random stream for (seed, keys)."""
    return np.random.default_rng([seed, *keys])


def load_catalogue(params: Params, path: Path = CATALOGUE_PATH) -> list[Sku]:
    """Read the SKU catalogue and apply the packing rule to every SKU."""
    df = pd.read_csv(path)
    shares = df["demand_share"] / df["demand_share"].sum()  # normalise to sum 1
    skus = []
    for row, share in zip(df.itertuples(), shares):
        item = Item(row.length_mm, row.width_mm, row.height_mm, row.unit_weight_kg)
        packing = units_per_tote(item, params.tote)
        half = units_per_tote(item, params.half_tote)
        if not packing.fits:
            continue  # cannot go into the system at all
        skus.append(Sku(row.sku_id, row.unit_weight_kg, item.volume_mm3, packing.n_max,
                        packing.n_geometry, half.n_max, half.n_geometry,
                        row.typical_inbound_qty_min,
                        row.typical_inbound_qty_max, share))
    return skus


def generate_lines(skus: list[Sku], params: Params, seed: int) -> list[OrderLine]:
    """Order lines arriving during one shift (Poisson process).

    Each line uses three uniform draws: gap to the next arrival, SKU, quantity.
    With the same seed, line k gets the same SKU and quantity at any arrival rate.
    """
    rng = rng_for(seed, _STREAM_ARRIVALS)
    cumulative = np.cumsum([s.share for s in skus])
    rate_per_min = params.arrival_rate_per_h / 60.0
    lines, t = [], 0.0
    while True:
        u_gap, u_sku, u_qty = rng.random(3)
        t += -math.log(1.0 - u_gap) / rate_per_min
        if t > params.shift_min:
            return lines
        sku = min(int(np.searchsorted(cumulative, u_sku, side="right")), len(skus) - 1)
        s = skus[sku]
        quantity = s.qty_min + int(u_qty * (s.qty_max - s.qty_min + 1))
        lines.append(OrderLine(len(lines), t, sku, quantity))


def triangular_from_uniform(u: float, low: float, mode: float, high: float) -> float:
    """Inverse CDF of the triangular distribution.

    Using a uniform draw keeps common random numbers when the sweep changes the mode.
    """
    if high - low < _EPS:
        return mode
    cut = (mode - low) / (high - low)
    if u < cut:
        return low + math.sqrt(u * (high - low) * (mode - low))
    return high - math.sqrt((1.0 - u) * (high - low) * (high - mode))


@dataclass
class ReplicationResult:
    metrics: dict[str, float]
    timeseries: pd.DataFrame
    lines: pd.DataFrame


class Station:
    """One decanting station: workers, conveyor check, buffer and lifter."""

    def __init__(self, params: Params, skus: list[Sku], seed: int) -> None:
        self.p = params
        self.skus = skus
        self.seed = seed
        self.env = simpy.Environment()
        self.line_queue = simpy.Store(self.env)
        self.buffer = simpy.Store(self.env, capacity=params.buffer_capacity)

        self.open_divided: dict[int, ToteLoad | None] = {w: None for w in range(params.n_workers)}
        self.busy = {w: dict.fromkeys(ACTIVITIES, 0.0) for w in range(params.n_workers)}
        self.workers_left = params.n_workers
        self.lifter_working = False
        self.lifter_busy = 0.0
        self.in_system = 0
        self.overweight_rejections = 0
        self.stored: list[ToteLoad] = []
        self.line_done: dict[int, float] = {}
        self.samples: list[tuple[float, int, int, int]] = []

    # ---------- helpers ----------

    def duration(self, mean: float, rng: np.random.Generator) -> float:
        """Random handling time with the given mean (gamma distribution, CV = time_cv)."""
        cv = self.p.time_cv
        if cv <= 0 or mean <= 0:
            return mean
        shape = 1.0 / cv**2
        return float(rng.gamma(shape, mean / shape))

    def work(self, worker: int, activity: str, mean: float, rng: np.random.Generator):
        """The worker spends time on an activity. Use as `yield from self.work(...)`."""
        d = self.duration(mean, rng)
        self.busy[worker][activity] += d
        yield self.env.timeout(d)

    def fill_factor(self, rng: np.random.Generator) -> float:
        """F for one tote. The rule always fills to capacity (F = 1)."""
        u = rng.random()  # drawn in both modes, so the streams stay aligned
        if self.p.filling == "rule":
            return 1.0
        return triangular_from_uniform(u, self.p.f_low, self.p.f_mode, self.p.f_high)

    @staticmethod
    def judged_units(n_max: int, n_geometry: int, f: float) -> int:
        """Units the worker puts in a tote (or a half) whose true capacity is n_max.

        The worker cannot put in more than physically fits (n_geometry), but can
        exceed the weight limit without noticing.
        """
        if n_max <= 0:
            return 0
        judged = max(1, math.floor(n_max * f + 0.5))
        return min(judged, n_geometry)

    def target_units(self, sku: Sku, f: float) -> int:
        """Units for a fresh single-SKU tote."""
        return self.judged_units(sku.n_max, sku.n_geometry, f)

    def half_target_units(self, sku: Sku, f: float) -> int:
        """Units the worker thinks fit in one half of a divided tote."""
        if not self.p.dividers:
            return 0
        return self.judged_units(sku.n_max_half, sku.n_geometry_half, f)

    def second_half_looks_ok(self, tote: ToteLoad, sku_index: int, units: int, f: float) -> bool:
        """Weight check before filling the free half. The rule checks the exact limit,
        judgement checks against f times the limit."""
        weight = tote.weight_kg + units * self.skus[sku_index].weight_kg
        return weight <= f * self.p.max_load_kg + _EPS

    @staticmethod
    def add(tote: ToteLoad, sku: Sku, sku_index: int, units: int) -> None:
        tote.contents.append([sku_index, units])
        tote.weight_kg += units * sku.weight_kg
        tote.volume_mm3 += units * sku.volume_mm3

    # ---------- conveyor check and induction ----------

    def send(self, worker: int, tote: ToteLoad, rng: np.random.Generator):
        """Push a tote onto the conveyor. Returns the units removed in rework.

        An overweight tote is rejected. The worker removes units, last added first,
        until it is under the limit, then pushes it again.
        """
        removed: list[list[int]] = []
        if tote.weight_kg > self.p.max_load_kg + _EPS:
            self.overweight_rejections += 1
            while tote.weight_kg > self.p.max_load_kg + _EPS:
                sku_index, units = tote.contents[-1]
                sku = self.skus[sku_index]
                excess = math.ceil((tote.weight_kg - self.p.max_load_kg) / sku.weight_kg - _EPS)
                k = min(units, excess)
                tote.contents[-1][1] -= k
                if tote.contents[-1][1] == 0:
                    tote.contents.pop()
                tote.weight_kg -= k * sku.weight_kg
                tote.volume_mm3 -= k * sku.volume_mm3
                removed.append([sku_index, k])
            n_removed = sum(k for _, k in removed)
            yield from self.work(worker, "rework", self.p.t_rework + self.p.t_unit * n_removed, rng)

        start = self.env.now
        yield self.buffer.put(tote)  # waits if the buffer is full
        self.busy[worker]["blocked"] += self.env.now - start
        return removed

    def lifter(self):
        """Takes totes from the buffer into storage, one at a time."""
        while True:
            tote = yield self.buffer.get()
            self.lifter_working = True
            yield self.env.timeout(self.p.lifter_time)
            self.lifter_busy += self.p.lifter_time
            self.stored.append(tote)
            self.lifter_working = False

    # ---------- the worker ----------

    def decide_time(self) -> float:
        return self.p.t_decide_rule if self.p.filling == "rule" else self.p.t_decide_judgement

    def fill_single(self, worker: int, sku_index: int, units: int, rng: np.random.Generator):
        """Fill one single-SKU tote and send it. Returns the units removed in rework."""
        tote = ToteLoad("single")
        yield from self.work(worker, "tote", self.p.t_tote, rng)
        yield from self.work(worker, "place", self.p.t_unit * units, rng)
        self.add(tote, self.skus[sku_index], sku_index, units)
        removed = yield from self.send(worker, tote, rng)
        return sum(k for _, k in removed)

    def start_divided(self, worker: int, sku_index: int, units: int, rng: np.random.Generator):
        """Fetch a tote, put in the divider and fill the first half."""
        tote = ToteLoad("divided")
        yield from self.work(worker, "tote", self.p.t_tote, rng)
        yield from self.work(worker, "place", self.p.t_unit * units, rng)
        self.add(tote, self.skus[sku_index], sku_index, units)
        self.open_divided[worker] = tote

    def close_divided(self, worker: int, rng: np.random.Generator):
        """Send the open divided tote. Units removed in rework start the next one."""
        tote = self.open_divided[worker]
        self.open_divided[worker] = None
        if tote is None:
            return
        removed = yield from self.send(worker, tote, rng)
        for sku_index, units in removed:  # in practice at most one SKU comes out
            yield from self.put_in_half(worker, sku_index, units, 1.0, rng)

    def put_in_half(self, worker: int, sku_index: int, units: int, f: float,
                    rng: np.random.Generator):
        """Put a leftover into the free half of the open divided tote, or start a new one."""
        tote = self.open_divided[worker]
        if tote is not None and self.second_half_looks_ok(tote, sku_index, units, f):
            yield from self.work(worker, "place", self.p.t_unit * units, rng)
            self.add(tote, self.skus[sku_index], sku_index, units)
            yield from self.close_divided(worker, rng)  # both halves used
            return
        yield from self.close_divided(worker, rng)  # sent with one half empty
        if self.open_divided[worker] is not None:   # rework units opened a new tote
            yield from self.put_in_half(worker, sku_index, units, f, rng)
        else:
            yield from self.start_divided(worker, sku_index, units, rng)

    def process_line(self, worker: int, line: OrderLine):
        sku = self.skus[line.sku]
        rng_fill = rng_for(self.seed, _STREAM_FILL, line.line_id)
        rng_time = rng_for(self.seed, _STREAM_TIMES, line.line_id)

        yield from self.work(worker, "setup", self.p.t_line_setup, rng_time)
        remaining = line.quantity
        while remaining > 0:
            f = self.fill_factor(rng_fill)
            yield from self.work(worker, "decide", self.decide_time(), rng_time)
            target = self.target_units(sku, f)
            if remaining <= self.half_target_units(sku, f):
                yield from self.put_in_half(worker, line.sku, remaining, f, rng_time)
                remaining = 0
            else:
                units = min(remaining, target)
                removed = yield from self.fill_single(worker, line.sku, units, rng_time)
                remaining -= units - removed

    def worker(self, worker: int):
        while True:
            line = yield self.line_queue.get()
            if line is None:  # end of shift and no lines left
                break
            yield from self.process_line(worker, line)
            self.line_done[line.line_id] = self.env.now
            self.in_system -= 1
        last_rng = rng_for(self.seed, _STREAM_TIMES, 10**6 + worker)
        while self.open_divided[worker] is not None:
            yield from self.close_divided(worker, last_rng)
        self.workers_left -= 1

    # ---------- arrivals and monitoring ----------

    def arrivals(self, lines: list[OrderLine]):
        for line in lines:
            yield self.env.timeout(line.arrival_min - self.env.now)
            self.in_system += 1
            yield self.line_queue.put(line)
        for _ in range(self.p.n_workers):
            yield self.line_queue.put(None)  # tells each worker that no more lines come

    def finished(self) -> bool:
        return self.workers_left == 0 and not self.buffer.items and not self.lifter_working

    def monitor(self):
        """Samples queue lengths every sample_dt minutes until all totes are stored."""
        while not self.finished():
            waiting = sum(1 for item in self.line_queue.items if item is not None)
            self.samples.append((self.env.now, waiting, self.in_system, len(self.buffer.items)))
            yield self.env.timeout(self.p.sample_dt)

    def run(self, lines: list[OrderLine]) -> None:
        self.env.process(self.arrivals(lines))
        for w in range(self.p.n_workers):
            self.env.process(self.worker(w))
        self.env.process(self.lifter())
        self.env.process(self.monitor())
        self.env.run()


def summarise(station: Station, lines: list[OrderLine]) -> ReplicationResult:
    """Metrics of one replication."""
    p = station.p
    tote = p.tote
    stored = station.stored
    finish = max(station.line_done.values(), default=0.0)
    horizon = max(p.shift_min, finish)

    units_in = sum(line.quantity for line in lines)
    units_stored = sum(t.units for t in stored)
    n_totes = len(stored)
    lead = np.array([station.line_done[line.line_id] - line.arrival_min for line in lines])

    m: dict[str, float] = {
        "lines": len(lines),
        "units_in": units_in,
        "units_stored": units_stored,
        "totes": n_totes,
        "totes_divided": sum(t.kind == "divided" for t in stored),
        "totes_per_1000_units": 1000 * n_totes / units_in if units_in else 0.0,
        "fill_weight_mean": float(np.mean([t.weight_kg / tote.max_load_kg for t in stored])) if stored else 0.0,
        "fill_weight_max": max((t.weight_kg / tote.max_load_kg for t in stored), default=0.0),
        "fill_volume_mean": float(np.mean([t.volume_mm3 / tote.usable_volume_mm3 for t in stored])) if stored else 0.0,
        "overweight_rejections": station.overweight_rejections,
        "finish_min": finish,
        "overtime_min": max(0.0, finish - p.shift_min),
        "lead_mean_min": float(lead.mean()) if len(lead) else 0.0,
        "lead_p95_min": float(np.percentile(lead, 95)) if len(lead) else 0.0,
        "units_per_h": 60 * units_stored / horizon,
        "totes_per_h": 60 * n_totes / horizon,
        "lifter_utilisation": station.lifter_busy / horizon,
    }
    capacity = p.n_workers * horizon
    busy_total = 0.0
    for activity in ACTIVITIES:
        minutes = sum(station.busy[w][activity] for w in station.busy)
        m[f"{activity}_min"] = minutes
        m[f"share_{activity}"] = minutes / capacity
        busy_total += minutes
    m["worker_utilisation"] = (busy_total - m["blocked_min"]) / capacity
    m["share_idle"] = 1.0 - busy_total / capacity

    ts = pd.DataFrame(station.samples, columns=["t_min", "lines_waiting", "lines_in_system", "buffer"])
    m["lines_waiting_mean"] = float(ts["lines_waiting"].mean()) if len(ts) else 0.0
    m["lines_waiting_max"] = float(ts["lines_waiting"].max()) if len(ts) else 0.0
    m["buffer_mean"] = float(ts["buffer"].mean()) if len(ts) else 0.0

    line_df = pd.DataFrame({
        "line_id": [line.line_id for line in lines],
        "arrival_min": [line.arrival_min for line in lines],
        "sku_id": [station.skus[line.sku].sku_id for line in lines],
        "quantity": [line.quantity for line in lines],
        "done_min": [station.line_done[line.line_id] for line in lines],
    })
    return ReplicationResult(m, ts, line_df)


def run_replication(params: Params, seed: int, skus: list[Sku] | None = None,
                    lines: list[OrderLine] | None = None) -> ReplicationResult:
    """One shift. Pass `lines` to replace the random arrivals (used in tests)."""
    if params.filling not in ("rule", "judgement"):
        raise ValueError("filling must be 'rule' or 'judgement'")
    skus = skus if skus is not None else load_catalogue(params)
    lines = lines if lines is not None else generate_lines(skus, params, seed)
    station = Station(params, skus, seed)
    station.run(lines)
    return summarise(station, lines)
