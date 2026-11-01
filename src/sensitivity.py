"""Sensitivity analysis: how the rule's benefit changes when the assumptions change.

Run from the project root:  .venv\\Scripts\\python -m src.sensitivity

Every point of every sweep runs the rule and judgement on the same seeds (common
random numbers) and reports judgement minus rule with a paired 95 % CI. A positive
difference means the rule is better (judgement uses more totes, time, ...).

Sweeps:
- fill_factor: the headline. The mode of the judgement fill factor F goes from 0.60
  to 1.05 with the base spread (mode - 0.20, mode + 0.25). A second variant fills
  volume-bound products perfectly by eye (F = 1) and underfills only weight-bound ones.
- max_load, tote_height, arrival_rate, decide_time, dividers: one assumption at a
  time, everything else at the base case.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from src.scenarios import SEEDS, confidence_interval
from src.simulation import Params, load_catalogue, run_replication

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
BASE = Params()
SPREAD_LOW, SPREAD_HIGH = BASE.f_mode - BASE.f_low, BASE.f_high - BASE.f_mode  # 0.20, 0.25
F_MODES = [round(x, 2) for x in np.arange(0.60, 1.0501, 0.05)]

METRICS = ["totes_per_1000_units", "totes", "totes_per_1000_units_weight_bound",
           "totes_per_1000_units_volume_bound", "overweight_rejections", "rework_min",
           "busy_min", "worker_utilisation", "overtime_min", "lead_mean_min"]


def with_fill_mode(params: Params, mode: float, volume_perfect: bool = False) -> Params:
    """Judgement F ~ triangular(mode - 0.20, mode, mode + 0.25).

    volume_perfect: volume-bound products are filled exactly to capacity (F = 1)."""
    params = replace(params, f_low=mode - SPREAD_LOW, f_mode=mode, f_high=mode + SPREAD_HIGH)
    if volume_perfect:
        params = replace(params, f_low_volume=1.0, f_mode_volume=1.0, f_high_volume=1.0)
    return params


def mean_fill(mode: float) -> float:
    """Mean of the triangular F distribution for a given mode."""
    return (mode - SPREAD_LOW + mode + mode + SPREAD_HIGH) / 3


def compare(rule: Params, judgement: Params, seeds: list[int]) -> list[dict]:
    """Paired judgement-minus-rule differences over the seeds, one row per metric."""
    skus_rule, skus_judgement = load_catalogue(rule), load_catalogue(judgement)
    r = pd.DataFrame([run_replication(rule, s, skus_rule).metrics for s in seeds])
    j = pd.DataFrame([run_replication(judgement, s, skus_judgement).metrics for s in seeds])
    rows = []
    for metric in METRICS:
        mean, low, high = confidence_interval((j[metric] - r[metric]).to_numpy())
        rows.append({"metric": metric, "rule_mean": r[metric].mean(),
                     "judgement_mean": j[metric].mean(), "diff_mean": mean,
                     "diff_ci_low": low, "diff_ci_high": high, "n": len(seeds)})
    return rows


def sweep(name: str, values: list, make: Callable[[object, str], Params], seeds: list[int]) -> pd.DataFrame:
    """For each value, build the rule and judgement Params with `make` and compare them."""
    rows = []
    for value in values:
        for row in compare(make(value, "rule"), make(value, "judgement"), seeds):
            rows.append({"sweep": name, "value": value, **row})
    return pd.DataFrame(rows)


def fill_factor_sweep(seeds: list[int]) -> pd.DataFrame:
    """The headline: extra totes from judgement as a function of how much workers underfill."""
    frames = []
    for variant, volume_perfect in [("all products", False), ("only weight-bound underfilled", True)]:
        df = sweep("fill_factor", F_MODES,
                   lambda m, filling: with_fill_mode(replace(BASE, filling=filling), m, volume_perfect),
                   seeds)
        df["variant"] = variant
        df["mean_fill"] = df["value"].map(mean_fill)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def one_at_a_time(seeds: list[int]) -> pd.DataFrame:
    """Vary one assumption at a time around the base case."""
    sweeps = {
        "max_load_kg": ([15.0, 25.0, 35.0], lambda v, f: replace(BASE, filling=f, max_load_kg=v)),
        "tote_height_mm": ([150.0, 200.0, 300.0], lambda v, f: replace(BASE, filling=f, tote_height_mm=v)),
        "arrival_rate_per_h": ([3.0, 4.0, 5.0, 6.0, 7.0], lambda v, f: replace(BASE, filling=f, arrival_rate_per_h=v)),
        "t_decide_judgement_min": ([0.1, 0.25, 0.5, 1.0], lambda v, f: replace(BASE, filling=f, t_decide_judgement=v)),
        "dividers_waiting": (["none/1", "halves/1", "all/1", "halves/2", "all/2"],
                             lambda v, f: replace(BASE, filling=f, dividers=v.split("/")[0],
                                                  waiting_totes=int(v.split("/")[1]))),
    }
    return pd.concat([sweep(name, values, make, seeds) for name, (values, make) in sweeps.items()],
                     ignore_index=True)


def main(n_replications: int = len(SEEDS)) -> None:
    seeds = list(range(1, n_replications + 1))
    RESULTS_DIR.mkdir(exist_ok=True)
    fill_factor_sweep(seeds).to_csv(RESULTS_DIR / "sensitivity_fill_factor.csv", index=False)
    one_at_a_time(seeds).to_csv(RESULTS_DIR / "sensitivity_one_at_a_time.csv", index=False)
    print(f"sensitivity results saved to {RESULTS_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reps", type=int, default=len(SEEDS), help="replications per point")
    main(parser.parse_args().reps)
