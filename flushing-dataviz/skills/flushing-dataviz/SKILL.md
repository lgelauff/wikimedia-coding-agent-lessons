---
name: flushing-dataviz
description: >-
  Accessible, consistent styling for research charts and tables (matplotlib +
  LaTeX booktabs). Use whenever a figure, plot, chart, graph, table or heatmap is
  wanted for a paper, slide deck, poster or analysis notebook — "make me a line
  chart of X", "plot this", "a figure for the ICWSM submission" — and read it
  BEFORE writing the first line of plotting code, since the styling decisions it
  makes cannot be retrofitted onto a finished chart. It applies even when the
  request is vague about which data or which columns: what to plot is a separate
  question from how it must look, and the answer to the second is the same either
  way. Matplotlib defaults fail colorblind and grayscale-print checks, so a chart
  built without this looks fine on screen and is unreadable in a printed paper.
  Ships a validated colorblind-safe, grayscale-safe palette, ICWSM/AAAI figure
  sizing, and paper/slides/poster styles.
---

# Flushing dataviz — one style for every figure and table

A design system for research output, loosely derived from the Flushing beamer
theme (deep crimson / silver / warm off-white / Helvetica). The palette was
generated on an OKLCH lightness ladder and machine-validated: worst all-pairs
CVD separation ΔE 13.2 (Machado 2009, target ≥ 12), monotone grayscale ladder
with CIE L* gaps ≥ 5.7, all slots in the categorical lightness band with
chroma ≥ 0.10. Full tokens in `references/design-tokens.md`; venue facts in
`references/icwsm-figures.md`.

## Workflow

1. **Copy the package** `assets/flushing_charts/` (one dir: `__init__.py`,
   three `.mplstyle` files, and `fonts/` with vendored Source Sans 3, OFL)
   into the project, e.g. next to the analysis code. Dependencies:
   matplotlib only (pandas just for tables, statsmodels for
   `regression_table`). `fc.apply()` registers the fonts, so figures render
   with identical metrics on any machine — keep `fonts/` when copying.
2. **Apply a mode before plotting:**
   ```python
   import flushing_charts as fc
   fc.apply("paper")     # ICWSM/AAAI print: white bg, 8pt type
   fc.apply("slides")    # Flushing beamer: off-white bg, heavier strokes
   fc.apply("poster")    # A0/A1: ~2x slides geometry, 18pt type
   ```
   Apply BEFORE creating figures — an existing axes keeps its old prop
   cycle (or push it with `ax.set_prop_cycle(plt.rcParams["axes.prop_cycle"])`).
   This sets fonts, grid, spines, 300-dpi export, embedded fonts
   (pdf.fonttype 42), and a composite prop cycle: color + linestyle + marker
   + markevery, so series identity survives grayscale print and CVD.
3. **Size figures exactly — never rescale in LaTeX:**
   ```python
   fig, ax = plt.subplots(figsize=fc.figsize("column"))   # 3.3 in AAAI column
   fig, ax = plt.subplots(figsize=fc.figsize("text"))     # 6.975 in full width
   fig, ax = plt.subplots(figsize=fc.figsize("slide"))    # 4.2 in Flushing \textwidth
   ```
   Insert with `\includegraphics{...}` **without** `width=` so the designed
   point sizes are the printed sizes. Save as PDF for LaTeX.
4. **Tables:** `fc.to_booktabs(df, "tab.tex", caption=..., label=...)` —
   booktabs rules, right-aligned numerics, no vertical rules. Needs
   `\usepackage{booktabs}`. Regression results:
   `fc.regression_table([m1, m2], "tab.tex", model_names=["(1)", "(2)"])`
   (statsmodels fits → coefficients, SEs in parens, stars, N/R² footer,
   star note; the convention is stated once in the table note, never
   improvised per cell).
5. **Figure anatomy — use the helpers, never improvise these elements:**
   `fc.coef_plot(...)` dot-and-whisker coefficients (95% CI whiskers, zero
   line included); `fc.band(ax, x, lo, hi)` CI ribbon (alpha 0.18 = 95%
   unless the caption says otherwise); `fc.refline(ax, x=..., zero=True)`
   reference/zero lines (SILVER, solid for zero, dashed for targets);
   `fc.shade(ax, x0, x1, "rollout")` intervention windows; `fc.panel_label
   (ax, "a")` subplot letters; `fc.legend_top(ax)` above-axes legends;
   `fc.ERROR_KW` for bar/errorbar whisker ink; `fc.scatter_kw(i)` for
   scatter groups (scatter does NOT consume the marker cycle).
6. **Verify** any figure with many series: `demo/gallery.py` shows the
   pattern — its `contact_sheet()` renders deuteranopia/protanopia/grayscale
   simulations (needs `colorspacious`). Eyeball the output for label
   collisions before shipping.

## Rules (non-negotiable)

- **Fixed series order, never shuffled:** crimson, blue, sand, teal, plum,
  olive (`fc.SERIES_ORDER`). Color follows the entity, not its rank; prefer
  folding a 7th series into "Other" or small multiples.
- **3–12 series:** `fc.apply(mode, series=n)` or `fc.styles(n)`. With 7–12
  the six hues repeat: pass one solid + filled markers, pass two dotted +
  open markers (S1 solid crimson, S7 dotted crimson); never invent a 7th hue.
- **One axis.** Never dual y-scales — use two panels or index to a base.
- **Magnitude = `fc.sequential_cmap()`** (single-hue crimson ramp, light→dark)
  for heatmaps; **`fc.thermal_cmap()`** (perceptually uniform, monotone
  lightness, plum→crimson→gold) when fine value discrimination matters —
  3D surfaces, value-colored scatter, dense fields.
  **Polarity = `fc.diverging_cmap()`** (blue ↔ neutral ↔ crimson). Never
  rainbow/jet; never a hue at the diverging midpoint. In grayscale the two
  diverging arms match by design — sign must also be carried by position
  (bar direction, reference line).
- **Emphasis pattern:** context series in `fc.SILVER` (thin, alpha ~0.55),
  the hero in `fc.CRIMSON` with a direct label — see `emphasis_lines` in the
  demo. Text always wears `fc.TEXT`, never a series color (direct labels of
  a specific series excepted).
- **Sand and olive are light by design** (they carry the light end of the
  grayscale ladder and sit below 3:1 on white). Legal only with the built-in
  redundancy (markers/dashes/edges) plus a legend or direct labels — never
  disable `redundancy` for a chart that relies on them.
- **Legend:** frameless (default); ≥ 2 series always get one, a single
  series never does (the title/caption names it).
- **In-figure text ≥ 7pt at print size** (paper mode's tick size is the
  floor). Captions live in LaTeX at 10pt, not inside the figure.
- Slides keep the warm off-white background (`fc.BG_SLIDES`) — do not
  switch it to white or the figure floats on the Flushing slide.
- **Titles:** paper figures never carry in-figure titles (the LaTeX caption
  is the title); on slides the frametitle carries it. Multi-panel figures
  use `fc.panel_label(ax, "a")` and describe panels in the caption.
- **Legend placement:** grouped bars and Likert → `fc.legend_top(ax)`;
  line charts → direct labels first, else the emptiest quadrant; never on
  data. Horizontal bars: grid runs perpendicular to the bars
  (`ax.grid(axis="x"); ax.grid(axis="y", visible=False)`).

## Statistical defaults (non-negotiable)

- Bar axes start at zero; no axis breaks. Whiskers are 95% CIs unless the
  caption states otherwise; prefer plotted CIs over significance stars, and
  when stars appear the convention is stated once (caption or table note).
- Report group n in the caption or tick labels ("News (n=412)").
- Correlation matrices use `fc.diverging_cmap()` centered at 0
  (`vmin=-1, vmax=1`), never the sequential ramp; mask the upper triangle.
- Log-log plots (CCDFs): `drawstyle="steps-post"`, no markers, decade grid
  on both axes (`ax.grid(True, which="major", axis="both")`) — see
  `ccdf_loglog` in the demo.
- Collections over ~5–10k points: pass `rasterized=True` (axes and text
  stay vector at 300 dpi; keeps arXiv/camera-ready PDFs small).

## Library interop (read before mixing tools)

- **seaborn:** call `fc.apply()` AFTER any `sns.set_theme()`. Seaborn's
  `hue=` ignores the prop cycle — always pass
  `palette=fc.SERIES_ORDER[:n]` (+ `hue_order`); for dash/marker redundancy
  pass `style=` with `dashes=dict(zip(levels, fc.DASHES))`.
- **statsmodels:** don't use its built-in plotters (hard-coded colors);
  extract `params`/`conf_int()` and draw with `fc.coef_plot`.
- **`ax.hist(histtype="step*")` crashes** under the redundancy cycle
  (matplotlib feeds line-only cycle keys to Polygons). Use
  `ax.stairs(*np.histogram(d, bins), fill=True)` — see `distributions` in
  the demo.
- **`ax.scatter` / `ax.bar`** take only color from the cycle — style
  scatter groups with `fc.scatter_kw(i)`. Lines with < 15 points: set
  `markevery=1`.
- **Networks/maps are out of scope** of the cycle: color nodes by community
  via `fc.SERIES_ORDER` (degree → size, not color), edges `fc.SILVER` at
  alpha 0.3, continuous node attributes via `fc.thermal_cmap()`.

## Venue quick facts (ICWSM → AAAI format)

Column 3.3 in, gutter 0.375 in, full text width 6.975 in, 10pt body and
captions, US letter. Figures ≥ 300 dpi (style default), don't rely on color
alone (redundancy is built in), high contrast, alt text in the submission
system where offered. Details + sources: `references/icwsm-figures.md`.
