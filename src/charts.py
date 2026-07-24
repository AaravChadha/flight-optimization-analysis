"""Figures for the study. Run AFTER metrics.py has written summary.json.

Design notes (deliberate, not defaults):
* One committed style, shared with the docs page: same palette, same faces
  (Barlow for titles, B612 Mono - the Airbus cockpit-display face - for
  numerals and airport codes). SVG output with text as paths, so the
  figures render identically everywhere.
* Baseline/re-timed is the same color pair in every figure. The only
  categorical color use is the five-airport chart (Okabe-Ito, CVD-safe).
* Direct labels instead of legends; one short annotation per figure that
  describes only what is plotted.
* Titles state that values are SCHEDULED, SIMULATED quantities.
"""

import calendar
import json
import shutil

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager, ticker

import config

# ---------------------------------------------------------------- palette
PAPER = "#F5F7F8"    # page ground
INK = "#1A2530"      # headings / primary
SLATE = "#4E6172"    # secondary text, axis labels
RULE = "#D3DBE0"     # hairlines, grid
SIGNAL = "#0072B2"   # re-timed series + page accent (Okabe-Ito blue)
BASE = "#97A3AC"     # baseline series

# Okabe-Ito subset, fixed assignment per airport (color follows entity)
AIRPORT_COLOR = {
    "ORD": "#0072B2", "ATL": "#E69F00", "DEN": "#009E73",
    "DFW": "#D55E00", "CLT": "#CC79A7",
}

for f in (config.ROOT / "assets" / "fonts").glob("*.ttf"):
    font_manager.fontManager.addfont(str(f))

plt.rcParams.update(
    {
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
        "savefig.facecolor": PAPER,
        "svg.fonttype": "path",
        "font.family": "Barlow",
        "axes.edgecolor": RULE,
        "axes.labelcolor": SLATE,
        "axes.titlecolor": INK,
        "axes.titlesize": 12,
        "axes.labelsize": 9.5,
        "xtick.color": SLATE,
        "ytick.color": SLATE,
        "axes.grid": False,
        "grid.color": RULE,
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.axisbelow": True,
        "axes.linewidth": 0.8,
        "figure.dpi": 150,
    }
)

MONO = {"fontfamily": "B612 Mono"}


def _style(ax, mono_x=True):
    """House style: horizontal-only hairline grid, mono tick numerals."""
    ax.grid(axis="y", color=RULE, linewidth=0.6)
    ax.tick_params(length=0)
    for lbl in ax.get_yticklabels() + (ax.get_xticklabels() if mono_x else []):
        lbl.set_fontfamily("B612 Mono")
        lbl.set_fontsize(8.5)


def _clock_axis(ax):
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 3))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 25, 3)])


def _label_points(vb, va, avoid=None, pad=10):
    """Anchor 'baseline' in the morning/midday half and 're-timed' in the
    evening half, each at its zone's point of maximum divergence, away
    from an `avoid` bin (e.g. an annotation)."""
    d1, d2 = (vb - va).astype(float).copy(), (va - vb).astype(float).copy()
    if avoid is not None:
        lo, hi = max(0, avoid - pad), min(len(d1), avoid + pad)
        d1[lo:hi] = -np.inf
        d2[lo:hi] = -np.inf
    d1[:26], d1[58:] = -np.inf, -np.inf   # baseline: 06:30-14:30
    d2[:62], d2[93:] = -np.inf, -np.inf   # re-timed: 15:30-23:15
    return int(np.argmax(d1)), int(np.argmax(d2))


def _yticks(ax, top):
    """Deterministic ticks: 0, s, 2s(, 3s) with a round step."""
    s = 20 if top > 45 else 10
    ax.set_yticks(list(range(0, int(top * 1.06) + 1, s)))


def _mean_profiles(loads: pd.DataFrame, airports):
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

    # The one annotation: the airport whose mean spike flattens the most.
    spike_apt = max(airports, key=lambda a: prof_b[a].max() - prof_a[a][int(prof_b[a].argmax())])

    fig, axes = plt.subplots(
        len(airports), 1, figsize=(9.2, 2.05 * len(airports)), sharex=True
    )
    for i, (ax, a) in enumerate(zip(axes, airports)):
        vb, va = prof_b[a], prof_a[a]
        ax.fill_between(x, vb, color=BASE, alpha=0.20, linewidth=0)
        ax.plot(x, vb, color=BASE, linewidth=1.4)
        ax.plot(x, va, color=SIGNAL, linewidth=1.9)
        top = max(vb.max(), va.max())
        ax.set_ylim(0, top * 1.3)
        _yticks(ax, top)
        ax.text(0.35, top * 1.08, a, fontsize=12, fontweight=600, color=INK,
                **MONO)
        if i == 0:  # direct labels at separated points of max divergence
            k1, k2 = _label_points(vb, va)
            ax.text(x[k1], vb[k1] + top * 0.06, "baseline", color=BASE,
                    fontsize=9, ha="center", fontweight=500)
            ax.text(x[k2], va[k2] + top * 0.06, "re-timed", color=SIGNAL,
                    fontsize=9, ha="center", fontweight=600)
        if a == spike_apt:
            pk = int(vb.argmax())
            t = f"{int(x[pk]):02d}:{int(x[pk] % 1 * 60):02d}"
            ax.annotate(
                f"sharpest mean spike: {vb.max():.0f} to {va[pk]:.0f} at {t}",
                xy=(x[pk], vb[pk]), xytext=(min(x[pk] + 2.2, 15), top * 1.02),
                fontsize=8.5, color=SLATE,
                arrowprops={"arrowstyle": "-", "color": SLATE, "linewidth": 0.7},
            )
        _style(ax, mono_x=(i == len(airports) - 1))
    _clock_axis(axes[-1])
    axes[-1].set_xlabel("local time of day")
    axes[len(airports) // 2].set_ylabel(
        f"scheduled movements per {config.BIN_MINUTES}-min bin (mean over days)"
    )
    axes[0].set_title(
        f"Scheduled demand before vs after simulated re-timing — {title_period}",
        loc="left", pad=14, fontweight=600,
    )
    fig.tight_layout(h_pad=1.0)
    return fig


def sensitivity_chart(sens, title_period):
    w = [s["window_min"] for s in sens]
    bin_r = [s["peak_bin_reduction_pct"] for s in sens]
    hr_r = [s["peak_hour_reduction_pct"] for s in sens]
    HOUR = "#D55E00"

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.2, 3.7))
    ax1.plot(w, bin_r, color=SIGNAL, linewidth=1.9, marker="o", markersize=5)
    ax1.plot(w, hr_r, color=HOUR, linewidth=1.9, marker="s", markersize=5)
    ax1.text(w[-1] + 1.5, bin_r[-1], "peak 15-min bin", color=SIGNAL,
             fontsize=9, va="center", fontweight=600)
    ax1.text(w[-1] + 1.5, hr_r[-1], "peak hourly load", color=HOUR,
             fontsize=9, va="center", fontweight=600)
    ax1.annotate(
        "gains flatten past ±45 min",
        xy=(52, (bin_r[2] + bin_r[3]) / 2),
        xytext=(31, (bin_r[1] + hr_r[1]) / 2),
        fontsize=8.5, color=SLATE,
        arrowprops={"arrowstyle": "-", "color": SLATE, "linewidth": 0.7},
    )
    ax1.set_xlim(11, 92)
    ax1.set_ylabel("peak reduction, % (5 airports)")
    ax1.set_title("Peak congestion reduction vs window", loc="left",
                  fontsize=11, fontweight=600)

    ax2.plot(w, [s["slots_freed_per_day_total"] for s in sens], color=SIGNAL,
             linewidth=1.9, marker="o", markersize=5)
    ax2.set_xlim(11, 64)
    ax2.set_ylabel("peak-hour slots freed per day (5 airports)")
    ax2.set_title("Capacity headroom freed vs window", loc="left",
                  fontsize=11, fontweight=600)

    for ax in (ax1, ax2):
        ax.set_ylim(0, None)
        ax.set_xticks(w)
        ax.set_xlabel("shift window (± minutes)")
        _style(ax)
    fig.suptitle(
        f"Sensitivity to the re-timing window — simulated, {title_period}",
        x=0.005, ha="left", color=INK, fontsize=12, fontweight=600, y=0.99,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    return fig


def _spread(labels, min_gap):
    """Nudge label y-positions apart until no pair is closer than min_gap."""
    order = sorted(range(len(labels)), key=lambda i: labels[i])
    for _ in range(20):
        moved = False
        for a, b in zip(order, order[1:]):
            if labels[b] - labels[a] < min_gap:
                mid = (labels[a] + labels[b]) / 2
                labels[a] = mid - min_gap / 2
                labels[b] = mid + min_gap / 2
                moved = True
        if not moved:
            break
    return labels


def sensitivity_by_airport(sens, airports, title_period):
    w = [s["window_min"] for s in sens]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.2, 3.9))
    for metric, ax in (("peak_bin_reduction_pct", ax1),
                       ("slots_freed_per_day", ax2)):
        series = {a: [s["per_airport"][a][metric] for s in sens] for a in airports}
        ys = _spread([series[a][-1] for a in airports],
                     min_gap=(max(v[-1] for v in series.values()) * 0.075))
        for a, y in zip(airports, ys):
            c = AIRPORT_COLOR[a]
            ax.plot(w, series[a], color=c, linewidth=1.8, marker="o",
                    markersize=4.5)
            ax.text(w[-1] + 1.5, y, a, color=c, fontsize=9, va="center",
                    fontweight=600, **MONO)
        ax.set_xlim(11, 74)
        ax.set_xticks(w)
        ax.set_ylim(0, None)
        ax.set_xlabel("shift window (± minutes)")
        _style(ax)
    dfw = [s["per_airport"]["DFW"]["peak_bin_reduction_pct"] for s in sens]
    ax1.annotate(
        "DFW: smallest reduction through ±30",
        xy=(30, dfw[1]), xytext=(31, dfw[0] * 0.35),
        fontsize=8.5, color=SLATE,
        arrowprops={"arrowstyle": "-", "color": SLATE, "linewidth": 0.7},
    )
    ax1.set_ylabel("peak 15-min bin reduction, %")
    ax2.set_ylabel("peak-hour slots freed per day")
    fig.suptitle(
        f"Per-airport sensitivity to the re-timing window — simulated, {title_period}",
        x=0.005, ha="left", color=INK, fontsize=12, fontweight=600, y=0.99,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.90))
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
    fig, ax = plt.subplots(figsize=(9.2, 3.5))
    ax.fill_between(x, vb, color=BASE, alpha=0.20, linewidth=0)
    ax.plot(x, vb, color=BASE, linewidth=1.4)
    ax.plot(x, va, color=SIGNAL, linewidth=1.9)
    top = vb.max()
    pk = int(vb.argmax())
    k1, k2 = _label_points(vb, va, avoid=pk)
    ax.text(x[k1], vb[k1] + top * 0.05, "baseline", color=BASE, fontsize=9,
            ha="center", fontweight=500)
    ax.text(x[k2], va[k2] + top * 0.05, "re-timed", color=SIGNAL, fontsize=9,
            ha="center", fontweight=600)
    _yticks(ax, top)
    ax.annotate(
        f"{case['max_bin_before']} to {case['max_bin_after']} movements\n"
        f"in the {case['peak_bin_time_local']} bin",
        xy=(x[pk], vb[pk]), xytext=(x[pk] - 7.5, vb[pk] * 0.9),
        fontsize=8.5, color=SLATE, ha="left",
        arrowprops={"arrowstyle": "-", "color": SLATE, "linewidth": 0.7},
    )
    ax.set_ylim(0, top * 1.12)
    _clock_axis(ax)
    ax.set_xlabel("local time of day")
    ax.set_ylabel(f"movements per {config.BIN_MINUTES}-min bin")
    ax.set_title(
        f"Worst baseline day in the study: {a}, {d} — simulated re-timing",
        loc="left", pad=12, fontweight=600,
    )
    _style(ax)
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
    for old in config.FIGURES.glob("*.png"):
        old.unlink()

    figures = {
        "demand_curves": demand_curves(base, after, airports, period),
        "sensitivity": sensitivity_chart(summary["sensitivity"], period),
        "sensitivity_by_airport": sensitivity_by_airport(
            summary["sensitivity"], airports, period
        ),
        "worst_day": worst_day_chart(
            base, after, summary["worst_day_case_study"], period
        ),
    }
    for name, fig in figures.items():
        fig.savefig(config.FIGURES / f"{name}.svg", format="svg",
                    bbox_inches="tight")
        plt.close(fig)

    # publish into docs/ so GitHub Pages serves figures AND the
    # machine-readable results (results/ itself is not in the Pages root)
    config.DOCS_FIGURES.mkdir(parents=True, exist_ok=True)
    for old in config.DOCS_FIGURES.glob("*.png"):
        old.unlink()
    for f in config.FIGURES.glob("*.svg"):
        shutil.copy(f, config.DOCS_FIGURES / f.name)
    docs_results = config.ROOT / "docs" / "results"
    docs_results.mkdir(parents=True, exist_ok=True)
    shutil.copy(config.RESULTS / "summary.json", docs_results / "summary.json")
    print(f"figures written to {config.FIGURES} and {config.DOCS_FIGURES}; "
          f"summary.json published to {docs_results}")


if __name__ == "__main__":
    main()
