# ICWSM / AAAI figure & table requirements

ICWSM papers follow the AAAI two-column format (checked 2026-07).

## Layout (AAAI author kit)

- US letter (8.5 × 11 in); margins 0.75 in (top/left/right), 1.25 in bottom.
- Two columns, each **3.3 in** wide, **0.375 in** gutter → full text width
  **6.975 in**.
- Body type 10pt/12pt leading; figure/table captions **10pt roman**.
- Recommended practice: make figures at final width and include without
  rescaling; keep in-figure text ≥ 7pt printed.

## Figures

- Vector PDF preferred; raster content ≥ **300 dpi** (style default).
- Embed fonts (`pdf.fonttype 42` — set by all mplstyles).
- Page budget includes figures and references (typically 8 recommended,
  10 max — check the year's CFP).
- **Exact width contract:** `savefig.bbox: standard` keeps the emitted PDF
  at exactly the designed `figsize` (3.300 in column), so
  `\includegraphics{fig.pdf}` without `width=` fills the column and fonts
  print at their designed size. Sanity check a build:
  `python -c "import re;print(re.search(rb'MediaBox\\s*\\[\\s*0 0 ([\\d.]+)', open('fig.pdf','rb').read()).group(1))"`
  → 237.6 pt = 3.3 in.
- **File size / arXiv:** any point collection over ~5–10k points gets
  `rasterized=True` (marks raster at 300 dpi, axes/text stay vector). Keep
  per-figure PDFs under ~2–3 MB for arXiv and reviewer PDF viewers.

## Accessibility (ICWSM/AAAI + general venue guidance)

- **Never encode by color alone** — pair color with linestyle, marker,
  texture, direct label, or position (built into `fc.apply`).
- Avoid red–green confusable pairs; use a CVD-validated palette (this
  system's palette is validated, worst all-pairs ΔE 13.2).
- High contrast against the background; assume grayscale printing works.
- Provide alt text for figures where the submission system supports it, and
  make the caption self-contained (what is plotted, what the takeaway is).

## Sources

- [ICWSM-19 submission guidelines](https://icwsm.org/2019/submitting/guidelines/) — AAAI format, page budget
- [AAAI formatting instructions (LaTeX guide)](https://arxiv.org/html/2405.18554v3) — column/gutter/margin/type dimensions
- [ASCB: figures accessible to color-blind readers](https://www.ascb.org/diversity-equity-and-inclusion/how-to-make-scientific-figures-accessible-to-readers-with-color-blindness/)
- [SIGCHI accessibility guide for authors](https://sigchi.org/resources/guides-for-authors/accessibility/) — alt text, contrast, color-independence
- [IEEE guidelines for figures and tables](https://proceedingsoftheieee.ieee.org/resources/guidelines-for-figures-and-tables/) — 300 dpi guidance
