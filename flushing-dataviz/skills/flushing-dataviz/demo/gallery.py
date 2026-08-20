"""Render the demo gallery for the Flushing chart style, plus accessibility
verification sheets (deuteranopia / protanopia / grayscale simulations).

Run from this directory:  python gallery.py
Extra dependency for the verification sheets: colorspacious.
Outputs land in ./output/.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "assets"))
import flushing_charts as fc  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(42)


def line_chart(ax, n_series=4):
    x = np.linspace(0, 10, 60)
    names = ["Baseline", "Model A", "Model B", "Model C", "Model D", "Model E"]
    for i in range(n_series):
        y = 0.92 * (1 - np.exp(-x / (1.5 + i))) + rng.normal(0, 0.012, x.size) \
            + 0.02 * i
        ax.plot(x, np.clip(y, 0, 1), label=names[i])
    ax.set_ylim(0, 1)
    ax.set_xlabel("Training epochs")
    ax.set_ylabel("Accuracy")
    ax.legend()


def bar_chart(ax):
    groups = ["News", "Politics", "Science", "Sports"]
    conds = ["Control", "Treatment", "Treatment+"]
    x = np.arange(len(groups))
    w = 0.26
    vals = rng.uniform(0.3, 0.9, (len(conds), len(groups)))
    for i, cond in enumerate(conds):
        ax.bar(x + (i - 1) * w, vals[i], w, label=cond,
               yerr=vals[i] * 0.07, error_kw=fc.ERROR_KW)
    ax.set_xticks(x, groups)
    ax.set_ylabel("Engagement rate")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncols=3,
              columnspacing=1.0, handlelength=1.2)


def scatter_chart(ax, n_groups=5):
    names = ["Cluster 1", "Cluster 2", "Cluster 3", "Cluster 4", "Cluster 5"]
    for i in range(n_groups):
        pts = rng.normal([i * 1.4, i % 3], 0.45, (40, 2))
        ax.scatter(pts[:, 0], pts[:, 1], s=14, marker=fc.MARKERS[i],
                   color=fc.SERIES_ORDER[i], edgecolors="white",
                   linewidths=0.4, label=names[i])
    ax.set_xlabel("Dimension 1")
    ax.set_ylabel("Dimension 2")
    ax.legend()


def heatmap(ax, fig):
    data = rng.random((8, 12)) ** 1.5
    im = ax.imshow(data, cmap=fc.sequential_cmap(), aspect="auto")
    ax.set_xlabel("Week")
    ax.set_ylabel("Community")
    ax.grid(False)
    fig.colorbar(im, ax=ax, label="Activity", shrink=0.9)


def diverging_bars(ax):
    """Sign carried by position + two constant hues — never double-encode
    magnitude with a color ramp on top of bar length."""
    items = ["Q%d" % i for i in range(1, 9)]
    vals = rng.uniform(-1, 1, len(items))
    colors = [fc.SERIES["blue"] if v < 0 else fc.SERIES["crimson"]
              for v in vals]
    ax.barh(items, vals, color=colors)
    fc.refline(ax, x=0, zero=True)
    ax.set_xlabel("Sentiment shift")
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)


def emphasis_lines(ax):
    """The context-vs-emphasis pattern: silver context, crimson hero."""
    x = np.linspace(0, 10, 60)
    for i in range(5):
        ax.plot(x, np.cumsum(rng.normal(0.01, 0.05, x.size)),
                color=fc.SILVER, linewidth=0.9, alpha=0.55,
                linestyle="-", marker="")
    y = np.cumsum(rng.normal(0.035, 0.05, x.size))
    ax.plot(x, y, color=fc.CRIMSON, linewidth=1.8, linestyle="-", marker="")
    ax.annotate("Our method", (x[-1], y[-1]), xytext=(-2, 6),
                textcoords="offset points", ha="right",
                color=fc.CRIMSON, fontweight="bold")
    ax.set_xlabel("Time")
    ax.set_ylabel("Cumulative effect")


def many_series(ax, mode):
    """Series 7-12 reuse the six hues: solid+filled, then dotted+open."""
    fc.apply(mode, series=10)
    # apply() after axes creation: push the new cycle onto the existing axes
    ax.set_prop_cycle(plt.rcParams["axes.prop_cycle"])
    x = np.linspace(0, 10, 50)
    for i in range(10):
        ax.plot(x, np.cumsum(rng.normal(0.05, 0.06, x.size)) + i * 0.15,
                label=f"S{i + 1}")
    fc.apply(mode)  # restore the default 6-series cycle
    ax.set_xlabel("Time")
    ax.set_ylabel("Value")
    fc.legend_top(ax, ncols=5, fontsize="small", columnspacing=1.0,
                  handlelength=1.6)


def thermal_3d(fig):
    """Value-coded 3D: perceptually uniform thermal ramp, monotone lightness.

    3D + colorbar needs manual layout: colorbar's make_axes does not shrink
    an Axes3D, so the z-axis renders on top of it. Give the 3D axes an
    explicit region, put the colorbar in its own axes, and let the colorbar
    label do the z-label's job.
    """
    fig.set_layout_engine("none")
    ax = fig.add_subplot(projection="3d")
    ax.set_position([0.0, 0.08, 0.8, 0.92])
    cax = fig.add_axes([0.84, 0.24, 0.03, 0.54])
    xg, yg = np.meshgrid(np.linspace(-2, 2, 60), np.linspace(-2, 2, 60))
    z = np.exp(-(xg**2 + yg**2) / 2) + 0.35 * np.exp(
        -((xg - 1.2)**2 + (yg + 1)**2))
    surf = ax.plot_surface(xg, yg, z, cmap=fc.thermal_cmap(),
                           linewidth=0, antialiased=True)
    # warm-neutral panes instead of matplotlib's cool gray box
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.set_pane_color((0, 0, 0, 0))
        axis._axinfo["grid"]["color"] = fc.GRID
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_xticks([-2, -1, 0, 1, 2])
    ax.set_yticks([-2, -1, 0, 1, 2])
    ax.set_zticklabels([])  # the colorbar carries the value scale
    ax.view_init(elev=28, azim=-50)
    fig.colorbar(surf, cax=cax, label="Density")


def coef_panel(ax):
    """Dot-and-whisker coefficient plot, two models. Whiskers = 95% CI."""
    names = ["Tenure", "Degree", "Activity", "Gender (F)", "Weekend"]
    est1 = rng.normal(0, 0.4, 5)
    est2 = est1 + rng.normal(0, 0.12, 5)
    ci1, ci2 = rng.uniform(0.15, 0.4, 5), rng.uniform(0.15, 0.4, 5)
    fc.coef_plot(ax, names, est1, est1 - ci1, est1 + ci1,
                 model="Baseline", offset=-0.13)
    fc.coef_plot(ax, names, est2, est2 - ci2, est2 + ci2,
                 model="+ Controls", offset=0.13)
    ax.set_xlabel("Estimate (95% CI)")
    ax.legend()


def regression_band(ax):
    """Scatter + fit + CI ribbon: points recede, estimate leads."""
    x = rng.uniform(0, 10, 160)
    y = 0.4 * x + rng.normal(0, 0.9, x.size)
    ax.scatter(x, y, s=8, color=fc.SERIES["blue"], alpha=0.35,
               edgecolors="none", rasterized=True)
    xs = np.linspace(0, 10, 50)
    b, a = np.polyfit(x, y, 1)
    se = 0.18 + 0.03 * np.abs(xs - 5)
    ax.plot(xs, a + b * xs, color=fc.CRIMSON, marker="")
    fc.band(ax, xs, a + b * xs - 1.96 * se, a + b * xs + 1.96 * se,
            color=fc.CRIMSON)
    ax.set_xlabel("Exposure")
    ax.set_ylabel("Response")


def distributions(ax):
    """Overlapping distributions: filled steps at alpha + full-ink outline.

    NOTE: use ax.stairs, not ax.hist(histtype='step*') — step hists consume
    the full prop cycle and crash on the line-only redundancy keys.
    """
    data = [rng.normal(m, s, 400) for m, s in ((0, 1), (1.2, 1.3), (2.8, 0.8))]
    bins = np.linspace(-4, 6, 36)
    for i, (d, name) in enumerate(zip(data, ["Control", "Treated", "Power"])):
        counts, _ = np.histogram(d, bins)
        ax.stairs(counts, bins, fill=True, alpha=0.45,
                  color=fc.SERIES_ORDER[i], label=name)
        ax.stairs(counts, bins, lw=1.2, color=fc.SERIES_ORDER[i])
    ax.set_xlabel("Score")
    ax.set_ylabel("Users")
    ax.legend()


def box_violin(ax):
    """Boxplots ride the boxplot.* rcParams; fills in series colors."""
    data = [rng.lognormal(m, 0.5, 200) for m in (0.2, 0.5, 0.9, 0.7)]
    bp = ax.boxplot(data, patch_artist=True, widths=0.55,
                    tick_labels=["News", "Politics", "Science", "Sports"])
    for patch, c in zip(bp["boxes"], fc.SERIES_ORDER):
        patch.set_facecolor(c)
        patch.set_alpha(0.55)
    ax.set_ylabel("Session length (min)")


def ccdf_loglog(ax):
    """Heavy-tail CCDF: log-log steps, decade grid both axes, no markers."""
    for i, alpha in enumerate((1.6, 2.1, 2.8)):
        x = np.sort((rng.pareto(alpha, 4000) + 1))
        ccdf = 1 - np.arange(x.size) / x.size
        ax.loglog(x, ccdf, drawstyle="steps-post", marker="",
                  color=fc.SERIES_ORDER[i], linestyle=fc.DASHES[i],
                  label=rf"$\alpha={alpha}$")
    ax.grid(True, which="major", axis="both")
    ax.set_xlabel("Degree")
    ax.set_ylabel(r"$P(X \geq x)$")
    ax.legend()


def event_study(ax):
    """Time series + intervention: shaded window, vline, CI band."""
    t = np.arange(60)
    y = np.cumsum(rng.normal(0.02, 0.15, t.size)) + np.where(t > 35, 0.9, 0)
    se = 0.25 + 0.1 * (t > 35)
    ax.plot(t, y, color=fc.SERIES["crimson"], marker="")
    fc.band(ax, t, y - 1.96 * se, y + 1.96 * se, color=fc.SERIES["crimson"])
    fc.shade(ax, 35, 42, label="rollout")
    fc.refline(ax, y=0, zero=True)
    ax.set_xlabel("Day")
    ax.set_ylabel("Effect")


def likert(ax):
    """Diverging stacked bars around a neutral center (survey items)."""
    items = ["Trust", "Clarity", "Fairness", "Usefulness"]
    frac = rng.dirichlet(np.ones(5) * 4, len(items)) * 100
    cmap = fc.diverging_cmap()
    shades = [cmap(0.08), cmap(0.28), cmap(0.5), cmap(0.72), cmap(0.92)]
    labels = ["Str. disagree", "Disagree", "Neutral", "Agree", "Str. agree"]
    left = -(frac[:, 0] + frac[:, 1] + frac[:, 2] / 2)
    for j in range(5):
        ax.barh(items, frac[:, j], left=left, color=shades[j],
                label=labels[j], hatch=fc.HATCHES[j])
        left = left + frac[:, j]
    fc.refline(ax, x=0, zero=True)
    ax.set_xlabel("% of respondents")
    fc.legend_top(ax, ncols=5, fontsize="x-small", columnspacing=0.8,
                  handlelength=1.0)
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)


PANELS = [("line", line_chart), ("bars", bar_chart), ("scatter", scatter_chart),
          ("heatmap", heatmap), ("diverging", diverging_bars),
          ("emphasis", emphasis_lines), ("many", many_series),
          ("coef", coef_panel), ("regband", regression_band),
          ("dist", distributions), ("box", box_violin),
          ("ccdf", ccdf_loglog), ("event", event_study), ("likert", likert),
          ("thermal3d", thermal_3d)]


def render(mode):
    fc.apply(mode)
    width = {"paper": "column", "slides": "slide", "poster": "poster"}[mode]
    for name, fn in PANELS:
        if fn is thermal_3d:
            fig = plt.figure(figsize=fc.figsize(width, aspect=0.85))
            fn(fig)
        else:
            fig, ax = plt.subplots(figsize=fc.figsize(width))
            if fn is heatmap:
                fn(ax, fig)
            elif fn is many_series:
                fn(ax, mode)
            else:
                fn(ax)
        for ext in ("png", "pdf"):
            fig.savefig(os.path.join(OUT, f"{mode}_{name}.{ext}"))
        plt.close(fig)


def contact_sheet(mode):
    """Assemble the panel PNGs into one sheet + CVD/grayscale simulations."""
    import matplotlib.image as mpimg
    try:
        from colorspacious import cspace_convert
    except ImportError:
        print("colorspacious not installed - skipping simulation sheets")
        return

    imgs = [mpimg.imread(os.path.join(OUT, f"{mode}_{n}.png"))[..., :3]
            for n, _ in PANELS]

    def sim(img, kind):
        if kind == "gray":
            g = cspace_convert(img, "sRGB1", "JCh")[..., 0] / 100
            return np.clip(np.stack([g] * 3, -1), 0, 1)
        out = cspace_convert(img, {"name": "sRGB1+CVD", "cvd_type": kind,
                                   "severity": 100}, "sRGB1")
        return np.clip(out, 0, 1)

    rows = [("normal vision", lambda im: im),
            ("deuteranopia", lambda im: sim(im, "deuteranomaly")),
            ("protanopia", lambda im: sim(im, "protanomaly")),
            ("grayscale print", lambda im: sim(im, "gray"))]

    fig, axes = plt.subplots(len(rows), len(imgs),
                             figsize=(3.1 * len(imgs), 2.2 * len(rows)))
    for r, (label, f) in enumerate(rows):
        for c, im in enumerate(imgs):
            ax = axes[r, c]
            ax.imshow(f(im))
            ax.set_axis_off()
            if c == 0:
                ax.text(-0.06, 0.5, label, transform=ax.transAxes,
                        rotation=90, va="center", ha="right", fontsize=11)
    fig.suptitle(f"Flushing chart style — {mode} mode — accessibility check",
                 fontsize=13)
    fig.savefig(os.path.join(OUT, f"verify_{mode}.png"), dpi=110)
    plt.close(fig)


def table_demo():
    import pandas as pd
    df = pd.DataFrame({
        "Condition": ["Control", "Treatment", "Treatment+"],
        "N": [412, 405, 398],
        "Engagement": [0.512, 0.634, 0.7012],
        "SE": [0.021, 0.019, 0.0204],
    })
    tex = fc.to_booktabs(df, os.path.join(OUT, "table_demo.tex"),
                         caption="Engagement by condition.",
                         label="tab:engagement", float_format="{:.3f}")
    print(tex)


def regression_table_demo():
    try:
        import statsmodels.api as sm
    except ImportError:
        print("statsmodels not installed - skipping regression table demo")
        return
    x = rng.normal(0, 1, (300, 2))
    y = 0.5 * x[:, 0] - 0.2 * x[:, 1] + rng.normal(0, 1, 300)
    X = sm.add_constant(x)
    m1 = sm.OLS(y, X[:, :2]).fit()
    m2 = sm.OLS(y, X).fit()
    print(fc.regression_table([m1, m2],
                              os.path.join(OUT, "table_regression.tex"),
                              model_names=["(1)", "(2)"],
                              caption="Example OLS models.",
                              label="tab:ols"))


if __name__ == "__main__":
    for mode in ("paper", "slides", "poster"):
        render(mode)
        if mode != "poster":
            contact_sheet(mode)
    table_demo()
    regression_table_demo()
    print("Wrote", len(os.listdir(OUT)), "files to", OUT)
