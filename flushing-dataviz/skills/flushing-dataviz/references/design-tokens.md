# Flushing dataviz — design tokens

Derived (loosely) from `beamerthemeFlushing.sty` (presentations repo):
primary crimson `#8B1A1A`, silver `#737378`, warm off-white `#FAF8F5`, body
text `#3C3C3C`, Helvetica/sans. The chart palette keeps that character but is
re-engineered in OKLCH for accessibility.

## Categorical series (fixed assignment order)

| # | name | hex | OKLCH L | CIE L* (grayscale) | dash | marker |
|---|------|-----|---------|--------------------|------|--------|
| 1 | crimson | `#902828` | 0.44 | 33 | solid | o |
| 2 | blue | `#3D7ABC` | 0.57 | 50 | (1,1) | s |
| 3 | sand | `#DFA635` | 0.76 | 72 | (4,1.5) | ^ |
| 4 | teal | `#189E8C` | 0.63 | 59 | (4,1.5,1,1.5) | D |
| 5 | plum | `#784D96` | 0.50 | 40 | (6,1.5,1,1.5,1,1.5) | v |
| 6 | olive | `#95A94E` | 0.70 | 66 | (2,1) | P |

Sand (the lightest stroke) deliberately gets the long dash and blue the
dot — lightest hue + sparsest dash on one slot was a double penalty.

### Style sets for 3–12 series

`fc.styles(n)` / `fc.apply(mode, series=n)` give n series styles for any
n in 1..12. Any subset of the six hues inherits the validated palette's CVD
guarantees:

- **1–6 series:** the six hues above, each with its own dash + filled
  marker (nested: styles(k) is the first k of styles(6)).
- **7–12 series:** the SAME six hues twice (a 7th hue is never invented —
  it could not stay CVD-safe). Same-hue pairs contrast maximally: the first
  pass is **solid with filled markers**, the second pass **dotted with open
  markers** `X * p h < >` (face none, edge in the hue). So S1 = solid
  crimson ●, S7 = dotted crimson ✕. Grayscale identity within a pass rests
  on the lightness ladder + marker shape; between passes on solid vs dotted.
- Crossing from 6 to 7 series switches pass one from per-hue dashes to
  all-solid — re-render existing figures if a chart grows past 6.
- Past ~6 series, prefer folding into "Other" or small multiples; past 12,
  `styles()` refuses by design.

Design properties (machine-checked, not eyeballed):

- **CVD separation:** worst all-pairs pair (plum↔blue) ΔE 13.2 under
  protanopia (Machado 2009), above the ≥ 12 target — validated with the
  dataviz skill's `validate_palette.js`, `--pairs all`, light surface.
- **Grayscale ladder:** every color has a distinct CIE L*; sorted gaps
  5.7–9.7, so 6 series remain separable in B/W print even before the
  dash/marker redundancy.
- **Lightness band** 0.43–0.77 OKLCH and **chroma ≥ 0.10** for every slot.
- **Known WARN:** sand (2.18:1) and olive (2.6:1) sit below 3:1 contrast on
  white — the price of the grayscale ladder's light end. Mitigation is
  mandatory and built in: composite prop cycle (dash + marker), white bar
  edges, frameless legends; prefer direct labels when either is prominent.
- Hatches for extra print safety on stacked/filled areas:
  `"" // .. xx \\ oo` (`fc.HATCHES`), white hatch color.

## Supporting tokens

| token | hex | use |
|-------|-----|-----|
| `CRIMSON` | `#8B1A1A` | brand emphasis (exact Flushing primary): hero series, annotations |
| `SILVER` | `#737378` | de-emphasized context series, reference lines |
| `TEXT` | `#3C3C3C` | all text ink |
| `BG_SLIDES` | `#FAF8F5` | slide figure + axes background |
| `GRID` | `#DDD8D2` | y-gridlines (paper); `#E2DDD6` on slides |

## Figure anatomy (canonical elements — use the helpers)

| element | helper / token | spec |
|---------|----------------|------|
| CI band | `fc.band(ax, x, lo, hi)` / `BAND_ALPHA` | series color, alpha 0.18, no edge, zorder 1.5; 95% CI unless caption says otherwise |
| error bars | `fc.ERROR_KW` | TEXT ink 0.8pt, cap 1.5 — pass to `bar`/`errorbar`, else matplotlib draws off-token black |
| zero line | `fc.refline(ax, x=0, zero=True)` | SILVER solid 0.8pt, zorder 0 |
| reference/target | `fc.refline(ax, y=t)` | SILVER dashed (4,1.5) 0.7pt, zorder 0 |
| shaded period | `fc.shade(ax, x0, x1, "label")` | GRID at alpha 0.4, zorder 0, small TEXT label at top |
| panel label | `fc.panel_label(ax, "a")` | "(a)" bold, left-aligned above axes |
| legend above axes | `fc.legend_top(ax)` | left-aligned single row (grouped bars, Likert) |
| scatter groups | `fc.scatter_kw(i)` | marker + hue + halo edge (scatter ignores the marker cycle) |
| coefficients | `fc.coef_plot(ax, names, est, lo, hi, model=...)` | horizontal dot-and-whisker, zero line, x-grid, models offset + auto-colored |
| annotations | 7pt TEXT (crimson only for hero series) | arrow `arrowstyle='-'`, 0.6pt, SILVER |

Boxplots are styled by `boxplot.*` rcParams in all three modes (TEXT ink,
crimson median, silver fliers); pass `patch_artist=True` and fill with
series colors at alpha ~0.55.

## Ramps (generated in OKLCH, monotone lightness)

Sequential (magnitude — heatmaps, densities), single crimson hue 25°:
`#FCEEED #EDD1CE #DDB5B1 #CD9994 #BD7D78 #AC625D #9A4742 #872928 #73000D`
→ `fc.sequential_cmap()` / matplotlib name `flushing_seq`.

Diverging (polarity), blue 252° ↔ warm neutral ↔ crimson 25°, symmetric arms:
`#004E8F #4074AC #729AC7 #A5C2E2 #DAEAFC | #EDEAE6 | #FCE1DE #E0B1AD #C3847E #A55651 #862726`
→ `fc.diverging_cmap()` / `flushing_div`. Grayscale caveat: the arms are
lightness-symmetric, so sign must also be encoded by position.

Thermal (continuous value coloring — 3D surfaces/scatter, dense fields),
perceptually uniform inferno-cousin in Flushing hues, dark plum → crimson →
sand/gold:
`#2A013F #3D024B #530454 #6A075A #810D5D #98175D #AE235B #C23356 #D44450
#E4584A #F16E46 #FA8446 #FF9D54 #FFB56E #FFCC8C #FFE1AE #FFF5D9`
→ `fc.thermal_cmap()` / `flushing_thermal`. Verified: CIE L* 7.9 → 96.6
strictly monotone (min step 5.0 per anchor) and still monotone under
deuteranopia and protanopia — value ordering survives grayscale and CVD.
Follows standard best practice for quantitative color mapping: perceptually
uniform, monotonically increasing lightness, never rainbow/jet (see
matplotlib's colormap guidance and Moreland's color-map advice). Use THERMAL
when fine value discrimination matters (its wide lightness + hue range beats
the single-hue SEQ); use SEQ when the quiet brand look fits better. On 3D
surfaces, keep `antialiased=True` and remember shading multiplies with the
colormap — thermal's large lightness range keeps values readable anyway.

## Type & geometry

- Sans-serif: **Source Sans 3** (vendored in `flushing_charts/fonts/`,
  SIL OFL 1.1 — license text ships alongside; registered automatically by
  `fc.apply()`) → Helvetica → Arial → DejaVu Sans fallback. Identical
  metrics on every machine, coauthor laptops and CI included.
- Paper: 8pt base, 7pt ticks/legend — printed sizes, since figures are made
  at final width. Slides: 9pt base at 4.2 in (visually matches the theme's
  10pt body after beamer projection). Poster: 18pt base at 8.4 in
  (~2x slides geometry for A0/A1 viewing distance).
- Mathtext is pinned to `dejavusans` so $\beta$, $R^2$ render consistently
  everywhere.
- Top/right spines off, y-grid only, grid below data, frameless legend.
- Lines 1.4pt (paper) / 2.0pt (slides); markers 4 / 5.5pt with
  background-colored edges; bars get background-colored 0.8–1pt edges
  (the "2px surface gap" spacer).
- Minor ticks styled (half major size) for log axes; offset notation off
  (`axes.formatter.useoffset: False`) — no dangling "1e3" multipliers.
- Export: 300 dpi, `savefig.bbox: standard` (NOT tight — tight re-crops the
  canvas and breaks the exact-width contract; constrained_layout prevents
  clipping inside the fixed canvas), `pdf.fonttype 42` (embedded TrueType),
  `svg.fonttype none`. Verified: emitted PDFs measure exactly 3.300 /
  4.200 / 8.400 in.

## Widths (inches)

| name | in | source |
|------|----|--------|
| `column` | 3.300 | AAAI column width |
| `text` | 6.975 | 2 × 3.3 + 0.375 gutter |
| `slide` | 4.2 | Flushing \textwidth (128 mm page − margins − 9 % strip − 6 mm) |
| `slide-half` | 2.1 | two-up slide figures |
| `poster` | 8.4 | poster column (~A0 three-column layout) |

Default aspect: golden ratio (0.618). Insert at natural size — never
`width=\columnwidth` rescaling, which silently changes font sizes.

## Extending (web/plotly, future)

Treat this file as the token source: series hexes + order, ramps, ink and
surface colors, and the redundancy rule (identity never by color alone) port
directly; only mark geometry is medium-specific.

## Provenance

Generated 2026-07-15 with an OKLCH ladder script; palette validated with the
Claude dataviz skill validator (six checks) and colorspacious CVD simulation;
demo gallery + verification sheets in `../demo/` (`gallery.py` re-renders
everything, including deutan/protan/grayscale contact sheets).
