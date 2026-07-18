# Matplotlib lessons

Gotchas from building a reusable, accessibility-validated matplotlib style
for research figures (papers / slides / posters). The runnable solution this
pairs with is a private figure-style plugin skill; the lessons are general.

## Style state and the prop cycle

- **rcParams changes do not affect already-created axes.** The prop cycle is
  captured at axes creation. Calling `plt.style.use(...)` or setting
  `rcParams["axes.prop_cycle"]` after `plt.subplots()` silently does nothing
  for that axes — series just reuse the old cycle. Apply the style first, or
  push explicitly: `ax.set_prop_cycle(plt.rcParams["axes.prop_cycle"])`.
  This failure is *silent* and produced a shipped demo where two series
  rendered pixel-identical.
- **A composite prop cycle (color + linestyle + marker) crashes
  `ax.hist(histtype="step"/"stepfilled")`.** matplotlib feeds the full cycle
  dict to `Polygon.set()`, which rejects line-only keys (`markevery`):
  `AttributeError: Polygon.set() got an unexpected keyword argument`.
  Use `ax.stairs(*np.histogram(d, bins), fill=True)` instead. `bar`,
  `boxplot`, `violinplot`, `stackplot`, `pie`, `fill_between` are fine.
- **`ax.scatter` and `ax.bar` take only color from the cycle** — marker/dash
  redundancy (colorblind + grayscale safety) silently disappears unless you
  style them explicitly per group.

## Exact figure sizes for camera-ready

- **`savefig.bbox: tight` breaks the "PDF is exactly N inches wide"
  contract.** It re-crops the canvas to content, so every figure exports at
  a slightly different width and LaTeX `\includegraphics` without `width=`
  no longer fills the column consistently. Use `savefig.bbox: standard` +
  `figure.constrained_layout` (which prevents clipping inside the fixed
  canvas). Verify by reading the PDF MediaBox, not by eyeballing.
- **Design figures at final physical size** (e.g. 3.3 in for an AAAI/ICWSM
  column) and insert without LaTeX rescaling, so point sizes are real.

## 3D, fonts, misc

- **`fig.colorbar` on a 3D axes overlaps the z-axis** — `make_axes` does not
  shrink an `Axes3D`, and under constrained layout it renders as what looks
  like a doubled colorbar. Disable the layout engine for 3D figures
  (`fig.set_layout_engine("none")`), position the axes explicitly, and give
  the colorbar its own `fig.add_axes(...)` cax.
- **Vendor an OFL font and register it at style-apply time**
  (`matplotlib.font_manager.fontManager.addfont`) — otherwise coauthor/CI
  machines silently fall back (Helvetica → DejaVu) and every layout shifts.
  Pin `mathtext.fontset` too, or $\beta$/$R^2$ render in a mismatched face.
- **Validate accessibility on rendered pixels, not palette swatches:**
  simulate deuteranopia/protanopia (`colorspacious`, Machado 2009) and
  grayscale on the *actual exported PNGs*, as a contact sheet. Redundant
  encoding (lightness ladder + linestyle + marker) is what survives print.
