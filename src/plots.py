"""Figures for the README and the report, drawn from the CSV files in results/.

Run from the project root (after src.scenarios and src.sensitivity):
    .venv\\Scripts\\python -m src.plots
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write files, no window
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

from src.packing import Item, units_per_tote
from src.scenarios import SCENARIOS
from src.simulation import CATALOGUE_PATH, Params

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

BLUE, ORANGE, AQUA, GREY, LIGHT = "#2a78d6", "#eb6834", "#1baf7a", "#888888", "#e6e6e6"
RULE, JUDGEMENT = BLUE, ORANGE

plt.rcParams.update({"font.size": 11, "axes.titlesize": 13, "axes.labelsize": 11,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "figure.dpi": 100, "savefig.dpi": 150, "savefig.bbox": "tight"})


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(RESULTS_DIR / name)


def save(fig: plt.Figure, name: str) -> Path:
    path = RESULTS_DIR / name
    fig.savefig(path)
    plt.close(fig)
    return path


def scenario_colour(name: str) -> str:
    return RULE if "rule" in name else JUDGEMENT


def fig1_units_per_tote(params: Params = Params()) -> Path:
    """Units per tote for every SKU, coloured by the binding constraint."""
    cat = pd.read_csv(CATALOGUE_PATH)
    rows = []
    for r in cat.itertuples():
        res = units_per_tote(Item(r.length_mm, r.width_mm, r.height_mm, r.unit_weight_kg), params.tote)
        rows.append((r.sku_id, r.description, res.n_max, res.binding))
    df = pd.DataFrame(rows, columns=["sku", "description", "n_max", "binding"]).sort_values("n_max")
    colours = {"weight": ORANGE, "volume": BLUE, "both": GREY}

    fig, ax = plt.subplots(figsize=(8, 9))
    labels = [f"{s}  {d}" for s, d in zip(df["sku"], df["description"])]
    ax.hlines(labels, 1, df["n_max"], color=LIGHT, linewidth=1)
    ax.scatter(df["n_max"], labels, c=[colours[b] for b in df["binding"]], s=45, zorder=3)
    ax.set_xscale("log")
    ax.set_xlim(1, 600)
    ax.set_xlabel("Units per tote (log scale)")
    ax.set_title(f"Units per tote, {params.tote_length_mm:.0f} × {params.tote_width_mm:.0f} × "
                 f"{params.tote_height_mm:.0f} mm, {params.max_load_kg:.0f} kg tote")
    ax.tick_params(axis="y", labelsize=8)
    ax.legend(handles=[Patch(color=ORANGE, label=f"weight binds ({(df.binding == 'weight').sum()})"),
                       Patch(color=BLUE, label=f"volume binds ({(df.binding == 'volume').sum()})")],
              frameon=False, loc="lower right")
    return save(fig, "fig1_units_per_tote.png")


def fig2_queue() -> Path:
    """Lines waiting over one peak shift, judgement vs rule, same seed."""
    ts = read("queue_timeseries_peak.csv")
    fig, ax = plt.subplots(figsize=(9, 3.8))
    for name, colour, label in [("S3 peak judgement", JUDGEMENT, "judgement (S3)"),
                                ("S4 peak rule", RULE, "rule (S4)")]:
        s = ts[ts["scenario"] == name]
        ax.step(s["t_min"] / 60, s["lines_waiting"], where="post", color=colour, linewidth=2, label=label)
    ax.axvline(8, color=GREY, linewidth=1, linestyle="--")
    ax.text(8.05, ax.get_ylim()[1] * 0.92, "shift ends", color=GREY)
    ax.set_xlabel("Hours since shift start")
    ax.set_ylabel("Order lines waiting")
    ax.set_title(f"Queue at the station over one peak shift (seed {ts['seed'].iloc[0]})")
    ax.legend(frameon=False, loc="upper left")
    return save(fig, "fig2_queue_peak_shift.png")


def fig3_worker_time() -> Path:
    """Stacked bar: how each worker's shift time splits between activities."""
    summary = read("scenario_summary.csv")
    shares = ["share_setup", "share_tote", "share_decide", "share_place", "share_rework", "share_idle"]
    labels = ["line setup", "fetch and send tote", "decide", "place units", "rework", "idle"]
    colours = [BLUE, AQUA, ORANGE, "#e87ba4", "#eda100", LIGHT]
    means = summary[summary["metric"].isin(shares)].pivot(index="scenario", columns="metric", values="mean")
    means = means.loc[list(SCENARIOS), shares]

    fig, ax = plt.subplots(figsize=(9, 3.8))
    left = np.zeros(len(means))
    for col, label, colour in zip(shares, labels, colours):
        ax.barh(means.index, means[col], left=left, color=colour, label=label, height=0.6,
                edgecolor="white", linewidth=1.5)
        left += means[col].to_numpy()
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlabel("Share of each worker's shift time")
    ax.set_title("Where the worker's time goes (mean of 50 shifts)")
    ax.legend(ncol=6, frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.2), fontsize=9)
    return save(fig, "fig3_worker_time.png")


def fig4_totes_per_scenario() -> Path:
    """Totes per 1000 units with 95 % CI per scenario."""
    summary = read("scenario_summary.csv")
    t = summary[summary["metric"] == "totes_per_1000_units"].set_index("scenario").loc[list(SCENARIOS)]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    y = np.arange(len(t))
    for i, (name, r) in enumerate(t.iterrows()):
        c = scenario_colour(name)
        ax.plot([r.ci_low, r.ci_high], [i, i], color=c, linewidth=2)
        ax.scatter(r["mean"], i, color=c, s=60, zorder=3)
        ax.text(r.ci_high + 0.4, i, f"{r['mean']:.1f}", va="center", fontsize=10)
    ax.set_yticks(y, t.index)
    ax.invert_yaxis()
    ax.set_xlim(30, 50)
    ax.set_xlabel("Totes (storage locations) per 1000 units, mean and 95 % CI")
    ax.set_title("Storage locations used per 1000 units")
    ax.legend(handles=[Patch(color=JUDGEMENT, label="judgement"), Patch(color=RULE, label="rule")],
              frameon=False, loc="lower left")
    diffs = read("scenario_differences.csv")
    d = diffs[(diffs["comparison"] == "S2 rule minus S1 judgement")
              & (diffs["metric"] == "totes_per_1000_units")].iloc[0]
    fig.text(0.01, -0.06, "The intervals overlap because shifts differ a lot. Compared shift by shift, "
             f"the rule uses {d.mean_diff:.1f} [{d.ci_low:.1f}, {d.ci_high:.1f}] totes per 1000 units "
             "versus judgement (S2 vs S1).", fontsize=9, color="#555555")
    return save(fig, "fig4_totes_per_scenario.png")


def fig5_sensitivity_fill() -> Path:
    """Headline: extra storage locations from judgement vs how full workers fill on average."""
    f = read("sensitivity_fill_factor.csv")
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(8.5, 7), sharex=True,
                                      gridspec_kw={"height_ratios": [2.2, 1]})
    styles = {"all products": (ORANGE, "all products underfilled (base)"),
              "only weight-bound underfilled": (BLUE, "only heavy products underfilled,\nbulky ones filled perfectly")}
    for variant, (colour, label) in styles.items():
        d = f[(f["variant"] == variant) & (f["metric"] == "totes_per_1000_units")].sort_values("mean_fill")
        x = 100 * d["mean_fill"]
        top.fill_between(x, d["diff_ci_low"], d["diff_ci_high"], color=colour, alpha=0.2, linewidth=0)
        top.plot(x, d["diff_mean"], color=colour, linewidth=2, marker="o", markersize=4, label=label)
    base = f[(f["variant"] == "all products") & (f["metric"] == "totes_per_1000_units") & (f["value"] == 0.85)].iloc[0]
    top.annotate(f"base case: {100 * base.mean_fill:.0f} % fill,\n{base.diff_mean:.1f} extra per 1000 units",
                 xy=(100 * base.mean_fill, base.diff_mean), xytext=(92, 12),
                 arrowprops={"arrowstyle": "->", "color": GREY}, fontsize=10)
    top.axhline(0, color=GREY, linewidth=0.8)
    top.set_ylabel("Extra storage locations\nper 1000 units (judgement − rule)")
    top.set_title("How much the rule saves depends on how full workers fill by eye")
    top.legend(frameon=False, loc="upper right", fontsize=9)

    d = f[(f["variant"] == "all products") & (f["metric"] == "overweight_rejections")].sort_values("mean_fill")
    x = 100 * d["mean_fill"]
    bottom.fill_between(x, d["diff_ci_low"], d["diff_ci_high"], color=GREY, alpha=0.25, linewidth=0)
    bottom.plot(x, d["diff_mean"], color="#555555", linewidth=2, marker="o", markersize=4)
    bottom.set_ylabel("Overweight\nrejections per shift")
    bottom.set_xlabel("Average fill aimed by judgement, % of the rule's capacity")
    return save(fig, "fig5_sensitivity_fill_factor.png")


def fig6_rule_vs_worker() -> Path:
    """Peak: is the rule worth as much as an extra worker? Two measures, two panels."""
    summary = read("scenario_summary.csv")
    names = ["S3 peak judgement", "S4 peak rule", "S5 peak judgement 2 workers"]
    short = ["judgement,\n1 worker", "rule,\n1 worker", "judgement,\n2 workers"]
    colours = [JUDGEMENT, RULE, AQUA]
    panels = [("totes_per_1000_units", "Storage locations per 1000 units"),
              ("overtime_min", "Overtime per shift (min)"),
              ("lead_mean_min", "Mean lead time per order line (min)")]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))
    for ax, (metric, title) in zip(axes, panels):
        t = summary[summary["metric"] == metric].set_index("scenario").loc[names]
        ax.bar(short, t["mean"], color=colours, width=0.6)
        ax.errorbar(short, t["mean"], yerr=[t["mean"] - t["ci_low"], t["ci_high"] - t["mean"]],
                    fmt="none", ecolor="#333333", capsize=4, linewidth=1)
        for i, (v, top) in enumerate(zip(t["mean"], t["ci_high"])):
            ax.text(i, top * 1.03, f"{v:.0f}", ha="center", va="bottom", fontweight="bold")
        ax.set_ylim(0, t["ci_high"].max() * 1.18)
        ax.set_title(title, fontsize=11)
        ax.tick_params(axis="x", labelsize=9)
    fig.suptitle("Peak load (6 lines/h): the rule saves storage, a second worker saves time", fontsize=13)
    fig.tight_layout()
    return save(fig, "fig6_peak_rule_vs_worker.png")


def main() -> None:
    for make in (fig1_units_per_tote, fig2_queue, fig3_worker_time, fig4_totes_per_scenario,
                 fig5_sensitivity_fill, fig6_rule_vs_worker):
        print("saved", make().name)


if __name__ == "__main__":
    main()
