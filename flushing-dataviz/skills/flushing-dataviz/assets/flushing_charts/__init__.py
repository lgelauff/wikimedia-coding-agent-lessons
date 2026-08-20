"""flushing_charts — consistent, accessible matplotlib styling for research output.

Loosely derived from the Flushing beamer theme (crimson / silver / warm off-white,
sans-serif). Palette is colorblind-safe (validated: worst all-pairs CVD dE 13.2,
Machado 2009) and lightness-laddered so series stay distinguishable in grayscale
print. Line charts additionally cycle linestyle + marker (belt and suspenders).

Usage:
    import flushing_charts as fc
    fc.apply("paper")                      # or "slides"
    fig, ax = plt.subplots(figsize=fc.figsize("column"))
    ...
    fc.to_booktabs(df, "results.tex", caption="...", label="tab:results")

Copy this directory into a project (or pip-install nothing — it is stdlib +
matplotlib only; pandas needed just for to_booktabs).
"""
from __future__ import annotations

import os

import matplotlib as mpl
import matplotlib.pyplot as plt
from cycler import cycler
from matplotlib.colors import LinearSegmentedColormap

_HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

#: Categorical series colors, FIXED assignment order — never shuffle or cycle
#: past the end (7+ series: fold into "Other" or use small multiples).
#: Lightness-laddered for grayscale: crimson(33) < plum(40) < blue(50)
#: < teal(59) < olive(66) < sand(72) in CIE L*.
SERIES = {
    "crimson": "#902828",
    "blue": "#3D7ABC",
    "sand": "#DFA635",
    "teal": "#189E8C",
    "plum": "#784D96",
    "olive": "#95A94E",
}
SERIES_ORDER = list(SERIES.values())

#: Linestyle + marker cycles, paired 1:1 with SERIES_ORDER (redundant encoding
#: so identity survives grayscale print and CVD).
#: NOTE: sand (slot 3) gets the long dash and blue the dot — sand is the
#: lightest stroke and pairing it with the sparsest dash was a double penalty.
DASHES = ["-", (0, (1, 1)), (0, (4, 1.5)), (0, (4, 1.5, 1, 1.5)),
          (0, (6, 1.5, 1, 1.5, 1, 1.5)), (0, (2, 1))]
MARKERS = ["o", "s", "^", "D", "v", "P"]
#: Second-pass marker shapes for series 7-12 (drawn OPEN: face none, edge in
#: the hue). Hues repeat past 6 — never invent a 7th hue; prefer folding into
#: "Other" or small multiples before going past 6.
MARKERS2 = ["X", "*", "p", "h", "<", ">"]
#: Optional hatch textures for stacked/filled areas when extra print safety is
#: wanted (use with facecolor + white edge).
HATCHES = ["", "//", "..", "xx", "\\\\", "oo"]

# Supporting (non-series) tokens — Flushing theme values.
CRIMSON = "#8B1A1A"   #: brand/emphasis accent (exact Flushing primary)
SILVER = "#737378"    #: de-emphasized context series, reference lines
TEXT = "#3C3C3C"      #: text ink (Flushing body text)
BG_SLIDES = "#FAF8F5"  #: warm off-white slide background (Flushing bg)
GRID = "#DDD8D2"      #: recessive gridlines

#: Sequential ramp (magnitude): single crimson hue, light -> dark, monotone
#: lightness. For heatmaps, choropleths, density.
SEQ = ["#FCEEED", "#EDD1CE", "#DDB5B1", "#CD9994", "#BD7D78",
       "#AC625D", "#9A4742", "#872928", "#73000D"]

#: Diverging ramp (polarity): blue <- warm neutral -> crimson, symmetric
#: lightness arms. Midpoint is neutral, never a hue.
DIV = ["#004E8F", "#4074AC", "#729AC7", "#A5C2E2", "#DAEAFC", "#EDEAE6",
       "#FCE1DE", "#E0B1AD", "#C3847E", "#A55651", "#862726"]

#: Thermal ramp (continuous value coloring, e.g. points/surfaces in 3D):
#: perceptually uniform inferno-cousin in Flushing hues, dark plum -> crimson
#: -> sand/gold. CIE L* 8 -> 97 strictly monotone, and stays monotone under
#: deuteranopia/protanopia, so value order survives grayscale and CVD.
#: Prefer this over SEQ when fine value discrimination matters (3D, dense
#: scatter); SEQ (single-hue) when the brand look matters more (heatmaps).
THERMAL = ["#2A013F", "#3D024B", "#530454", "#6A075A", "#810D5D", "#98175D",
           "#AE235B", "#C23356", "#D44450", "#E4584A", "#F16E46", "#FA8446",
           "#FF9D54", "#FFB56E", "#FFCC8C", "#FFE1AE", "#FFF5D9"]

# ---------------------------------------------------------------------------
# Figure sizing (inches) — AAAI/ICWSM two-column layout and Flushing slides
# ---------------------------------------------------------------------------

COLUMN_WIDTH_IN = 3.3     # AAAI column width
TEXT_WIDTH_IN = 6.975     # AAAI full text width (2 * 3.3 + 0.375 gutter)
SLIDE_WIDTH_IN = 4.2      # Flushing beamer content width (\textwidth)
GOLDEN = 0.6180339887

POSTER_COL_IN = 8.4       # poster column (~2x slides; A0 3-col layout)

_WIDTHS = {
    "column": COLUMN_WIDTH_IN,
    "text": TEXT_WIDTH_IN,
    "slide": SLIDE_WIDTH_IN,
    "slide-half": SLIDE_WIDTH_IN / 2,
    "poster": POSTER_COL_IN,
}


def figsize(width="column", aspect=GOLDEN, height=None):
    """Figure size in inches for a named target width (or a float, inches).

    Insert the result at natural size in LaTeX (\\includegraphics WITHOUT a
    width= override) so fonts print at their designed point size.

    width:  "column" (3.3in, AAAI column), "text" (6.975in, full width),
            "slide" (4.2in, Flushing \\textwidth), "slide-half", or inches.
    aspect: height/width ratio (default golden); ignored if height is given.
    """
    w = _WIDTHS.get(width, width)
    if not isinstance(w, (int, float)):
        raise ValueError(f"unknown width {width!r}; use {list(_WIDTHS)} or inches")
    return (w, height if height is not None else w * aspect)


# ---------------------------------------------------------------------------
# Style application
# ---------------------------------------------------------------------------

def styles(n):
    """Style dicts for n series (1 <= n <= 12), for manual plotting control.

    For n <= 6 (nested: styles(k) is the first k of styles(6)) each hue gets
    its own dash + filled marker. For n > 6 the pairing changes so same-hue
    pairs contrast maximally: series 1-6 are SOLID with filled markers,
    series 7-12 repeat the hues DOTTED with open markers (no 7th hue exists —
    past 6, strongly prefer folding small series into "Other" or using small
    multiples instead).
    """
    if not 1 <= n <= 12:
        raise ValueError("n must be 1..12; >12 series: fold into 'Other' "
                         "or use small multiples")
    out = []
    for i in range(n):
        second = i >= 6
        color = SERIES_ORDER[i % 6]
        if n <= 6:
            linestyle = DASHES[i]
        else:
            linestyle = (0, (1, 1)) if second else "-"
        out.append({
            "color": color,
            "linestyle": linestyle,
            "marker": (MARKERS2 if second else MARKERS)[i % 6],
            "markerfacecolor": "none" if second else color,
            "markeredgecolor": color if second else _marker_halo(),
            "markevery": 0.09,
        })
    return out


def _marker_halo():
    """Marker edge = figure background (halo). Safe before apply() too."""
    edge = plt.rcParams["lines.markeredgecolor"]
    return "#FFFFFF" if edge in ("auto", None, "none") else edge


def _style_cycler(n, redundancy):
    sts = styles(n)
    cyc = cycler(color=[s["color"] for s in sts])
    if redundancy:
        for key in ("linestyle", "marker", "markerfacecolor",
                    "markeredgecolor", "markevery"):
            cyc += cycler(**{key: [s[key] for s in sts]})
    return cyc


def _register_fonts():
    """Register the vendored Source Sans 3 faces (OFL 1.1, fonts/OFL.txt) so
    every machine renders identical metrics — no silent DejaVu fallback on
    coauthor/CI boxes without Helvetica."""
    from matplotlib import font_manager
    fdir = os.path.join(_HERE, "fonts")
    if not os.path.isdir(fdir):
        return
    for fname in sorted(os.listdir(fdir)):
        if fname.endswith((".ttf", ".otf")):
            try:
                font_manager.fontManager.addfont(os.path.join(fdir, fname))
            except Exception:
                pass  # a corrupt/unreadable face falls back down the stack


def _register_cmaps():
    for name, colors in (("flushing_seq", SEQ), ("flushing_div", DIV),
                         ("flushing_thermal", THERMAL)):
        cmap = LinearSegmentedColormap.from_list(name, colors)
        try:
            mpl.colormaps.register(cmap, name=name)
            mpl.colormaps.register(cmap.reversed(), name=name + "_r")
        except ValueError:
            pass  # already registered


def apply(mode="paper", redundancy=True, series=6):
    """Activate the Flushing chart style.

    mode:       "paper" (AAAI print, white bg, 8pt),
                "slides" (Flushing off-white bg, 9pt at beamer scale), or
                "poster" (~2x slides geometry for A0/A1 viewing distance).
    redundancy: also cycle linestyle/marker/markevery with color (default
                True; set False only when direct labels replace the legend).
    series:     length of the style cycle, 1..12 (default 6). Beyond 6 the
                six hues repeat with shifted dashes + open markers — see
                styles(). markevery thins markers on dense lines so they
                read as line + marker accents, not beads.
    """
    path = os.path.join(_HERE, f"{mode}.mplstyle")
    if not os.path.exists(path):
        raise ValueError(f"unknown mode {mode!r}; expected 'paper', 'slides' "
                         "or 'poster'")
    _register_fonts()
    plt.style.use(path)
    _register_cmaps()
    plt.rcParams["axes.prop_cycle"] = _style_cycler(series, redundancy)


def sequential_cmap():
    _register_cmaps()
    return mpl.colormaps["flushing_seq"]


def diverging_cmap():
    _register_cmaps()
    return mpl.colormaps["flushing_div"]


def thermal_cmap():
    _register_cmaps()
    return mpl.colormaps["flushing_thermal"]


# ---------------------------------------------------------------------------
# Figure anatomy — canonical elements so they never drift figure-to-figure
# ---------------------------------------------------------------------------

#: Uncertainty bands (fill_between): 95% CI unless the caption says otherwise.
BAND_ALPHA = 0.18

#: Error-bar ink: pass **ERROR_KW to bar()/errorbar() so whiskers use TEXT
#: ink, not default black (the only off-token black in a default figure).
ERROR_KW = {"ecolor": TEXT, "elinewidth": 0.8, "capsize": 1.5, "capthick": 0.8}


def band(ax, x, lo, hi, color=None, alpha=BAND_ALPHA, **kw):
    """Canonical uncertainty ribbon: series color at BAND_ALPHA, no edge,
    behind the line. Semantics: 95% CI unless the caption states otherwise."""
    if color is None:
        color = ax.lines[-1].get_color() if ax.lines else SERIES_ORDER[0]
    kw.setdefault("zorder", 1.5)
    return ax.fill_between(x, lo, hi, color=color, alpha=alpha, lw=0, **kw)


def refline(ax, x=None, y=None, zero=False, **kw):
    """Reference line convention: SILVER, zorder 0. Solid 0.8pt for a true
    zero axis (zero=True), dashed 0.7pt for hypothetical references/targets."""
    kw.setdefault("color", SILVER)
    kw.setdefault("zorder", 0)
    kw.setdefault("linewidth", 0.8 if zero else 0.7)
    kw.setdefault("linestyle", "-" if zero else (0, (4, 1.5)))
    if x is not None:
        return ax.axvline(x, **kw)
    return ax.axhline(0 if y is None else y, **kw)


def shade(ax, x0, x1, label=None, **kw):
    """Shaded period/region (e.g. an intervention window): GRID at alpha .4,
    zorder 0, optional small label at the top of the span."""
    kw.setdefault("color", GRID)
    kw.setdefault("alpha", 0.4)
    kw.setdefault("zorder", 0)
    kw.setdefault("lw", 0)
    span = ax.axvspan(x0, x1, **kw)
    if label:
        ax.text((x0 + x1) / 2, 0.97, label, transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize="small", color=TEXT)
    return span


def panel_label(ax, letter):
    """Subplot label '(a)', '(b)' — bold, left-aligned above the axes."""
    ax.set_title(f"({letter})", loc="left", fontweight="bold")


def legend_top(ax, ncols=None, **kw):
    """Legend above the axes, left-aligned, one horizontal row (the grouped-
    bars convention; use for any chart whose interior has no empty quadrant)."""
    handles, labels = ax.get_legend_handles_labels()
    return ax.legend(handles, labels, loc="lower left", ncols=ncols or len(labels),
                     bbox_to_anchor=(0, 1.02, 1, 0.2), mode=None,
                     borderaxespad=0, **kw)


def scatter_kw(i, second=False):
    """Style kwargs for ax.scatter — scatter does NOT consume the marker/dash
    prop cycle, so color-only groups slip through unless you pass these."""
    return {
        "marker": (MARKERS2 if second else MARKERS)[i % 6],
        "color": SERIES_ORDER[i % 6],
        "edgecolors": _marker_halo(),
        "linewidths": 0.4,
    }


def coef_plot(ax, names, estimates, ci_lo, ci_hi, model=None, offset=0.0):
    """Dot-and-whisker coefficient plot (horizontal), the CSS-paper workhorse.

    Whiskers are 95% CIs (state the level in the caption). Draws the zero
    reference line once. For multiple models, call repeatedly with the same
    names, a model label, and offset=+/-0.15 etc.; series colors follow
    SERIES_ORDER automatically per call.
    """
    i = sum(1 for c in ax.containers
            if type(c).__name__ == "ErrorbarContainer")  # calls so far
    y = [j + offset for j in range(len(names))]
    err_lo = [e - lo for e, lo in zip(estimates, ci_lo)]
    err_hi = [hi - e for e, hi in zip(estimates, ci_hi)]
    ax.errorbar(estimates, y, xerr=[err_lo, err_hi], fmt=MARKERS[i % 6],
                color=SERIES_ORDER[i % 6], markeredgecolor=_marker_halo(),
                markeredgewidth=0.4, linestyle="none", label=model, **{
                    k: v for k, v in ERROR_KW.items() if k != "ecolor"},
                ecolor=SERIES_ORDER[i % 6])
    if i == 0:
        refline(ax, x=0, zero=True)
        ax.set_yticks(range(len(names)), names)
        ax.invert_yaxis()
        ax.grid(axis="x")
        ax.grid(axis="y", visible=False)
    return ax


# ---------------------------------------------------------------------------
# Tables — publication booktabs export
# ---------------------------------------------------------------------------

def to_booktabs(df, path=None, *, float_format="{:.2f}", index=False,
                caption=None, label=None, column_format=None, escape=True):
    """Render a DataFrame as a booktabs LaTeX table (\\toprule/\\midrule/\\bottomrule,
    no vertical rules). Returns the LaTeX string; also writes it if path given.

    float_format applies to float columns only. Requires ``booktabs`` in the
    LaTeX preamble.
    """
    import pandas.api.types as ptypes

    fmts = {c: float_format for c in df.columns if ptypes.is_float_dtype(df[c])}
    sty = df.style.format(fmts, na_rep="--")
    if escape:
        sty = sty.format_index(escape="latex", axis=1)
        non_float = [c for c in df.columns
                     if not ptypes.is_numeric_dtype(df[c])]
        if non_float:
            sty = sty.format(escape="latex", subset=non_float)
    if not index:
        sty = sty.hide(axis="index")
    if column_format is None:
        column_format = ("l" if index else "") + "".join(
            "r" if ptypes.is_numeric_dtype(df[c]) else "l" for c in df.columns)
    tex = sty.to_latex(hrules=True, caption=caption, label=label,
                       column_format=column_format,
                       position_float="centering" if caption else None)
    if path is not None:
        with open(path, "w") as fh:
            fh.write(tex)
    return tex


def regression_table(results, path=None, *, model_names=None, stars=True,
                     float_format="%.3f", stats=("nobs", "rsquared"),
                     caption=None, label=None):
    """Booktabs regression table from statsmodels results (list of fitted
    models -> one column each): coefficients with SEs in parentheses beneath,
    significance stars, N/R^2 footer block. Returns LaTeX; writes if path.

    Star convention (one caption note, never per-cell improvisation):
    ``$^{*}p<.05$; $^{**}p<.01$; $^{***}p<.001$``. Requires statsmodels.
    Coefficient columns are right-aligned; strings like "0.634***" defeat
    pandas' numeric alignment, so column_format is forced here.
    """
    from statsmodels.iolib.summary2 import summary_col

    info = {"N": lambda m: f"{int(m.nobs):d}",
            "$R^2$": lambda m: f"{m.rsquared:.3f}" if hasattr(m, "rsquared")
            else f"{m.prsquared:.3f}"}
    info = {k: v for k, v in info.items()
            if ("nobs" in stats) or k != "N"
            if ("rsquared" in stats) or k != "$R^2$"}
    summ = summary_col(results, stars=stars, float_format=float_format,
                       model_names=model_names, info_dict=info,
                       include_r2=False)
    df = summ.tables[0]
    df.index.name = None
    body = df.reset_index().rename(columns={"index": ""})
    tex = to_booktabs(body, None, index=False, caption=caption, label=label,
                      column_format="l" + "r" * (len(body.columns) - 1),
                      escape=False)
    # rule off the stats footer block at its FIRST row in the rendered table
    positions = [(tex.find(f"\n{key} &"), key) for key in info]
    positions = [(p, k) for p, k in positions if p >= 0]
    if positions:
        _, first = min(positions)
        tex = tex.replace(f"\n{first} &", f"\n\\midrule\n{first} &", 1)
    note = ("\\addlinespace\n\\multicolumn{%d}{l}{\\footnotesize "
            "$^{*}p<.05$; $^{**}p<.01$; $^{***}p<.001$} \\\\\n"
            % len(body.columns))
    tex = tex.replace("\\bottomrule", note + "\\bottomrule") if stars else tex
    if path is not None:
        with open(path, "w") as fh:
            fh.write(tex)
    return tex
