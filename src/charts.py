"""Figures for the study. Run AFTER metrics.py has written summary.json.

Design notes (deliberate, not defaults):
* Before/after curves use an emphasis form: baseline in muted gray, the
  re-timed schedule in the accent blue - the finding is "after is flatter",
  and a luminance gap keeps the pair legible under any color vision.
* The sensitivity figure uses two separate single-axis panels (percent and
  count are different scales; a dual-axis chart would be misleading).
* Chart titles state that values are SCHEDULED, SIMULATED quantities.
"""

import calendar
import json
import shutil

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config

# Reference palette (validated; see dataviz palette notes in README)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BLUE = "#2a78d6"   # categorical slot 1: re-timed / primary series
ORANGE = "#eb6834"  # categorical slot 2: second series (sensitivity panel)
# categorical slots 1-5 in fixed order, for the per-airport breakout
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]

plt.rcParams.update(
    {
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Arial", "DejaVu Sans"],
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK_2,
        "axes.titlecolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.axisbelow": True,
        "figure.dpi": 150,
    }
)


def _mean_profiles(loads: pd.DataFrame, airports):
    """Mean movements per 15-min bin over all days: {airport: ndarray[96]}."""
    out = {}
    for a in airports:
        sub = loads[loads["airport"] == a]
        days = sub["date"].nunique()
        v = sub.groupby("bin")["load"].sum().reindex(range(96), fill_value=0)
        out[a] = v.to_numpy() / days
    return out


def demand_curves(base, after, airports, title_period):
    prof_b = _mean_profiles(base, airports)
    prof_a = _mean_profiles(after, airports)
    x = np.arange(96) * config.BIN_MINUTES / 60.0

    fig, axes = plt.subplots(
        len(airports), 1, figsize=(8.6, 2.1 * len(airports)), sharex=True
    )
    for ax, a in zip(axes, airports):
        ax.fill_between(x, prof_b[a], color=MUTED, alpha=0.18, linewidth=0)
        ax.plot(x, prof_b[a], color=MUTED, linewidth=1.6, label="baseline schedule")
        ax.plot(x, prof_a[a], color=BLUE, linewidth=2.0,
                label=f"re-timed (±{config.SHIFT_WINDOW_MIN} min, simulated)")
        ax.set_xlim(0, 24)
        ax.set_ylim(0, None)
        ax.text(0.35, ax.get_ylim()[1] * 0.86, a, fontsize=13,
                fontweight="bold", color=INK)
        ax.tick_params(length=0)
    axes[-1].set_xticks(range(0, 25, 3))
    axes[-1].set_xticklabels([f"{h:02d}:00" for h in range(0, 25, 3)])
    axes[-1].set_xlabel("local time of day")
    axes[len(airports) // 2].set_ylabel(
        f"scheduled movements per {config.BIN_MINUTES}-min bin (mean over days)"
    )
    axes[0].legend(loc="upper right", frameon=False, fontsize=9,
                   labelcolor=INK_2)
    axes[0].set_title(
        f"Scheduled demand before vs after simulated re-timing — {title_period}",
        fontsize=12, loc="left", pad=12,
    )
    fig.tight_layout()
    return fig


def sensitivity_chart(sens, title_period):
    w = [s["window_min"] for s in sens]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.4, 3.6))

    ax1.plot(w, [s["peak_bin_reduction_pct"] for s in sens], color=BLUE,
             linewidth=2, marker="o", markersize=6, label="peak 15-min bin load")
    ax1.plot(w, [s["peak_hour_reduction_pct"] for s in sens], color=ORANGE,
             linewidth=2, marker="s", markersize=6, label="peak hourly load")
    ax1.set_xlabel("shift window (± minutes)")
    ax1.set_ylabel("peak reduction, % (all airports)")
    ax1.set_ylim(0, None)
    ax1.set_xticks(w)
    ax1.legend(frameon=False, fontsize=9, labelcolor=INK_2, loc="lower right")
    ax1.set_title("Peak congestion reduction vs window", fontsize=11, loc="left")

    ax2.plot(w, [s["slots_freed_per_day_total"] for s in sens], color=BLUE,
             linewidth=2, marker="o", markersize=6)
    ax2.set_xlabel("shift window (± minutes)")
    ax2.set_ylabel("peak-hour slots freed per day (5 airports)")
    ax2.set_ylim(0, None)
    ax2.set_xticks(w)
    ax2.set_title("Capacity headroom freed vs window", fontsize=11, loc="left")

    for ax in (ax1, ax2):
        ax.tick_params(length=0)
    fig.suptitle(
        f"Sensitivity to the re-timing window — simulated, {title_period}",
        fontsize=12, x=0.01, ha="left", color=INK,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig


def sensitivity_by_airport(sens, airports, title_period):
    """Per-airport breakout: same two panels as the overall sensitivity
    figure, one line per airport (validated categorical slots, fixed order;
    identity carried by the legend and by the tables on the page)."""
    w = [s["window_min"] for s in sens]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.4, 3.8))
    for i, a in enumerate(airports):
        c = SERIES[i]
        ax1.plot(w, [s["per_airport"][a]["peak_bin_reduction_pct"] for s in sens],
                 color=c, linewidth=2, marker="o", markersize=5.5, label=a)
        ax2.plot(w, [s["per_airport"][a]["slots_freed_per_day"] for s in sens],
                 color=c, linewidth=2, marker="o", markersize=5.5, label=a)
    ax1.set_ylabel("peak 15-min bin reduction, %")
    ax2.set_ylabel("peak-hour slots freed per day")
    for ax in (ax1, ax2):
        ax.set_xlabel("shift window (± minutes)")
        ax.set_xticks(w)
        ax.set_ylim(0, None)
        ax.tick_params(length=0)
    ax1.legend(frameon=False, fontsize=9, labelcolor=INK_2, loc="lower right")
    ax2.legend(frameon=False, fontsize=9, labelcolor=INK_2, loc="lower right")
    fig.suptitle(
        f"Per-airport sensitivity to the re-timing window — simulated, {title_period}",
        fontsize=12, x=0.01, ha="left", color=INK,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig


def worst_day_chart(base, after, case, title_period):
    a, d = case["airport"], case["date"]
    x = np.arange(96) * config.BIN_MINUTES / 60.0

    def profile(loads):
        sub = loads[(loads["airport"] == a) & (loads["date"] == d)]
        v = np.zeros(96)
        v[sub["bin"].to_numpy()] = sub["load"].to_numpy()
        return v

    vb, va = profile(base), profile(after)
    fig, ax = plt.subplots(figsize=(8.6, 3.4))
    ax.fill_between(x, vb, color=MUTED, alpha=0.18, linewidth=0)
    ax.plot(x, vb, color=MUTED, linewidth=1.6, label="baseline schedule")
    ax.plot(x, va, color=BLUE, linewidth=2.0,
            label=f"re-timed (±{config.SHIFT_WINDOW_MIN} min, simulated)")
    pk = int(vb.argmax())
    ax.annotate(
        f"{case['max_bin_before']} to {case['max_bin_after']} movements\n"
        f"in the {case['peak_bin_time_local']} bin",
        xy=(x[pk], vb[pk]), xytext=(x[pk] + 1.6, vb[pk] * 0.96),
        fontsize=9, color=INK_2,
        arrowprops={"arrowstyle": "-", "color": AXIS},
    )
    ax.set_xlim(0, 24)
    ax.set_ylim(0, None)
    ax.set_xticks(range(0, 25, 3))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 25, 3)])
    ax.set_xlabel("local time of day")
    ax.set_ylabel(f"movements per {config.BIN_MINUTES}-min bin")
    ax.tick_params(length=0)
    ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK_2)
    ax.set_title(
        f"Worst baseline day in the study: {a}, {d} — simulated re-timing",
        fontsize=12, loc="left", pad=12,
    )
    fig.tight_layout()
    return fig


def main():
    summary = json.loads((config.RESULTS / "summary.json").read_text())
    data = summary["data"]
    airports = data["airports"]
    period = f"{calendar.month_name[data['month']]} {data['year']}"

    base = pd.read_csv(config.DATA_DERIVED / "baseline_bins.csv")
    after = pd.read_csv(config.DATA_DERIVED / "optimized_bins.csv")

    config.FIGURES.mkdir(parents=True, exist_ok=True)
    fig = demand_curves(base, after, airports, period)
    fig.savefig(config.FIGURES / "demand_curves.png", bbox_inches="tight")
    plt.close(fig)

    fig = sensitivity_chart(summary["sensitivity"], period)
    fig.savefig(config.FIGURES / "sensitivity.png", bbox_inches="tight")
    plt.close(fig)

    fig = sensitivity_by_airport(summary["sensitivity"], airports, period)
    fig.savefig(config.FIGURES / "sensitivity_by_airport.png", bbox_inches="tight")
    plt.close(fig)

    fig = worst_day_chart(base, after, summary["worst_day_case_study"], period)
    fig.savefig(config.FIGURES / "worst_day.png", bbox_inches="tight")
    plt.close(fig)

    # copy into docs/ so GitHub Pages can serve them
    config.DOCS_FIGURES.mkdir(parents=True, exist_ok=True)
    for f in config.FIGURES.glob("*.png"):
        shutil.copy(f, config.DOCS_FIGURES / f.name)
    print(f"figures written to {config.FIGURES} and {config.DOCS_FIGURES}")


if __name__ == "__main__":
    main()
