"""Scenarios S1-S5: run replications, compute confidence intervals, save CSV files.

Run from the project root:  .venv\\Scripts\\python -m src.scenarios

Statistics used:
- Replication: one shift with its own random numbers. Every scenario uses the same
  list of seeds, so replication k of S1 and replication k of S2 see the same order
  lines and the same random handling times (common random numbers).
- 95 % confidence interval of a mean: mean ± t(0.975, n-1) · s / sqrt(n).
- Paired difference: for each seed, scenario B minus scenario A. The CI of the mean
  difference is much narrower than comparing two separate CIs, because the shared
  randomness cancels out.
- No warm-up: each replication is one shift that starts empty, as a real shift does.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from src.simulation import Params, load_catalogue, run_replication

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
N_REPLICATIONS = 50
SEEDS = list(range(1, N_REPLICATIONS + 1))  # fixed seed list, the same for every scenario

NORMAL_RATE = 4.0  # order lines per hour
PEAK_RATE = 6.0    # 1.5 x normal

SCENARIOS: dict[str, Params] = {
    "S1 judgement": Params(filling="judgement", arrival_rate_per_h=NORMAL_RATE),
    "S2 rule": Params(filling="rule", arrival_rate_per_h=NORMAL_RATE),
    "S3 peak judgement": Params(filling="judgement", arrival_rate_per_h=PEAK_RATE),
    "S4 peak rule": Params(filling="rule", arrival_rate_per_h=PEAK_RATE),
    "S5 peak judgement 2 workers": Params(filling="judgement", arrival_rate_per_h=PEAK_RATE, n_workers=2),
}

# (B, A): the difference reported is B minus A.
COMPARISONS: list[tuple[str, str]] = [
    ("S2 rule", "S1 judgement"),
    ("S4 peak rule", "S3 peak judgement"),
    ("S5 peak judgement 2 workers", "S3 peak judgement"),
    ("S4 peak rule", "S5 peak judgement 2 workers"),
]

# Metrics reported in the summary tables, in this order.
METRICS = [
    "totes", "totes_per_1000_units",
    "totes_per_1000_units_weight_bound", "totes_per_1000_units_volume_bound",
    "fill_weight_mean", "fill_volume_mean", "totes_divided", "empty_compartments",
    "overweight_rejections", "rework_min",
    "worker_utilisation", "share_setup", "share_tote", "share_decide", "share_place",
    "share_rework", "share_blocked", "share_idle",
    "lifter_utilisation", "lines_waiting_mean", "lines_waiting_max", "buffer_mean",
    "lead_mean_min", "lead_p95_min", "overtime_min", "units_per_h", "totes_per_h",
]


def confidence_interval(values: np.ndarray, level: float = 0.95) -> tuple[float, float, float]:
    """(mean, lower, upper) of a t-based confidence interval for the mean."""
    values = np.asarray(values, dtype=float)
    n = len(values)
    mean = float(values.mean())
    if n < 2:
        return mean, mean, mean
    half = stats.t.ppf(0.5 + level / 2, n - 1) * values.std(ddof=1) / np.sqrt(n)
    return mean, mean - half, mean + half


def run_all(seeds: list[int] = SEEDS, scenarios: dict[str, Params] = SCENARIOS) -> pd.DataFrame:
    """Every scenario × every seed. One row per replication."""
    skus = load_catalogue(next(iter(scenarios.values())))
    rows = []
    for name, params in scenarios.items():
        for seed in seeds:
            metrics = run_replication(params, seed, skus).metrics
            rows.append({"scenario": name, "seed": seed, **metrics})
    return pd.DataFrame(rows)


def summary_table(reps: pd.DataFrame, metrics: list[str] = METRICS) -> pd.DataFrame:
    """Mean and 95 % CI of each metric in each scenario."""
    rows = []
    for name, group in reps.groupby("scenario", sort=False):
        for metric in metrics:
            mean, low, high = confidence_interval(group[metric].to_numpy())
            rows.append({"scenario": name, "metric": metric, "mean": mean,
                         "ci_low": low, "ci_high": high, "n": len(group)})
    return pd.DataFrame(rows)


def paired_differences(reps: pd.DataFrame, comparisons: list[tuple[str, str]] = COMPARISONS,
                       metrics: list[str] = METRICS) -> pd.DataFrame:
    """Mean of B minus A over matching seeds, with its paired 95 % CI.

    `unpaired_half_width` is the CI half-width you would get by treating the two
    scenarios as independent samples (Welch). It shows what common random numbers buy.
    """
    rows = []
    for b, a in comparisons:
        rb = reps[reps["scenario"] == b].set_index("seed")
        ra = reps[reps["scenario"] == a].set_index("seed")
        seeds = rb.index.intersection(ra.index)
        for metric in metrics:
            xb, xa = rb.loc[seeds, metric].to_numpy(float), ra.loc[seeds, metric].to_numpy(float)
            mean, low, high = confidence_interval(xb - xa)
            unpaired = welch_half_width(xb, xa)
            base = xa.mean()
            rows.append({"comparison": f"{b} minus {a}", "metric": metric,
                         "mean_diff": mean, "ci_low": low, "ci_high": high,
                         "relative_to_a": mean / base if base else np.nan,
                         "paired_half_width": (high - low) / 2,
                         "unpaired_half_width": unpaired, "n": len(seeds)})
    return pd.DataFrame(rows)


def welch_half_width(xb: np.ndarray, xa: np.ndarray, level: float = 0.95) -> float:
    """CI half-width for a difference of means of two independent samples."""
    vb, va = xb.var(ddof=1) / len(xb), xa.var(ddof=1) / len(xa)
    if vb + va == 0:
        return 0.0
    dof = (vb + va) ** 2 / (vb**2 / (len(xb) - 1) + va**2 / (len(xa) - 1))
    return float(stats.t.ppf(0.5 + level / 2, dof) * np.sqrt(vb + va))


def queue_timeseries(seed: int = SEEDS[0]) -> pd.DataFrame:
    """Lines waiting over one peak shift, judgement vs rule, same seed (for figure 2)."""
    skus = load_catalogue(SCENARIOS["S3 peak judgement"])
    frames = []
    for name in ("S3 peak judgement", "S4 peak rule"):
        ts = run_replication(SCENARIOS[name], seed, skus).timeseries
        frames.append(ts.assign(scenario=name, seed=seed))
    return pd.concat(frames, ignore_index=True)


def main(n_replications: int = N_REPLICATIONS) -> None:
    seeds = list(range(1, n_replications + 1))
    RESULTS_DIR.mkdir(exist_ok=True)
    reps = run_all(seeds)
    reps.to_csv(RESULTS_DIR / "scenario_replications.csv", index=False)
    summary_table(reps).to_csv(RESULTS_DIR / "scenario_summary.csv", index=False)
    paired_differences(reps).to_csv(RESULTS_DIR / "scenario_differences.csv", index=False)
    queue_timeseries(seeds[0]).to_csv(RESULTS_DIR / "queue_timeseries_peak.csv", index=False)
    print(f"{len(reps)} replications saved to {RESULTS_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reps", type=int, default=N_REPLICATIONS, help="replications per scenario")
    main(parser.parse_args().reps)
