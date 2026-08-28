# Playbook: arxiv-submission

Prepare a LaTeX paper for arXiv and **prove** it is ready, rather than checking the
things that are easy to check.

arXiv documents its requirements clearly. What it does not tell you is that the
obvious checks are green on documents that are visibly wrong. Every trap below was
found on a submission that compiled cleanly, embedded every font, shipped every
figure, and passed a hand-written gate.

## Method

### 1. Emit the document's own geometry, then assert against it

Put `\typeout{ARXIVDIMS name=\the\dimen}` lines in the preamble for `\textwidth`,
`\textheight`, `\oddsidemargin`, `\topmargin`, `\headheight`, `\headsep`,
`\paperwidth`, `\paperheight`, and read them back from `main.log`. Never assume a
class default.

**Compute margins to the TEXT BODY.** `\topmargin` measures to the top of the *head*
and goes **negative** under `geometry`; a check built on it alone reports a 0.67in top
margin on a page whose text starts at 3cm. Top of body = `1in + \topmargin +
\headheight + \headsep`. Check the bottom too, or you assert three sides of four.

### 2. Fonts — the trap that passes every font check

`\usepackage[T1]{fontenc}` with no text font selected silently resolves to
**cm-super** (`sfrm1000.pfb` — confirm with `kpsewhich`). Those are Type 1 outlines
**auto-traced from the EC bitmap fonts**, and the unevenness is visible at reading
size. Worse, the document ends up set in **two families at once**: cm-super for text,
original Computer Modern (`CMR`/`CMMI`/`CMSY`) for math, so a roman letter in a
formula does not match the same letter beside it.

cm-super is Type 1 and fully embedded, so **"no Type 3" and "all embedded" are both
green**. Assert a third thing: no `SF*`/`CM*` face appears at all. Fix is
`\usepackage{lmodern}` — drawn, not traced, real T1 coverage, matching math,
metrically compatible so nothing reflows, and present in every TeX Live.

### 3. Figures — two failure modes, and one is silent

- **Units.** matplotlib writes the PDF MediaBox in **big points** (1/72 in); TeX's
  `pt` is **1/72.27 in**. `425.197bp = 426.79pt`. Reading one as the other reports a
  correct figure as ~1.6pt short and invites someone to "fix" it into being wrong.
- **Clamping hides undersizing.** The common `\setkeys{Gin}{width=\maxwidth}` idiom
  clamps an oversized figure but **never enlarges an undersized one**. A figure built
  against an older, narrower text block therefore arrives at natural size, scores a
  clean "1:1", and is simply short of the measure. It does not look broken. Check
  both directions: rescaled *and* materially narrower than `\textwidth`.
- **Raster and vector fail differently.** "Never rescale" is a rule about *vector*
  figures, whose text is drawn at a designed point size. A screenshot has pixels, and
  shrinking it *raises* effective resolution. Judge raster on dpi
  (`72 * natural_pt / requested_pt`), not on scale factor — otherwise the report cries
  wolf forever and everyone learns to ignore the line.
- **Keep one source of truth for width.** If a plotting script sizes figures to the
  text width, assert that constant equals `\the\textwidth` from the built document.
  Nothing else links them, and they drift silently.

### 4. `\IfFileExists` does not search `\graphicspath`

`\includegraphics` resolves through `\graphicspath`; `\IfFileExists` searches
TEXINPUTS. A guard written against a canonical repo path
(`\IfFileExists{../../figures/x.png}`) fails in a flat submission tree and prints its
fallback **into the submitted paper**, with the image sitting right beside it. The
build is clean, the tarball complete, the local PDF correct.

Prefer no guard: a missing figure should stop the build, not ship a placeholder box.

### 5. arXiv publishes the SOURCE — comments included

Not just stray notes: on one paper 35% of the shipped source was comments, including
drafting commentary addressed to the author. Run
[`arxiv_latex_cleaner`](https://github.com/google-research/arxiv-latex-cleaner) and
make the packaging step **refuse to run without it** rather than falling back to
tarring raw source.

Then verify three things, because stripping comments *can* change output — a trailing
`%` suppresses the following newline, so deleting the line it sits on silently joins
or splits words:

1. zero comment lines survive (a stripper that no-ops leaves every other check green);
2. the cleaned tree builds with `pdflatex` alone, from a clean directory;
3. its `pdftotext` output matches a **freshly rebuilt** reference PDF.

Point 3 caught the `\IfFileExists` bug above. Rebuild the reference first — comparing
against a stale PDF returns a false "identical".

### 6. Filenames

arXiv permits only `a-zA-Z0-9_+-.,=`. macOS screenshot names break this twice: they
contain spaces, and the separator before `AM`/`PM` is **U+202F NARROW NO-BREAK
SPACE** — invisible, and the reason `mv` fails on a name `ls` has just printed.
Normalise programmatically, not by retyping what you see.

## Report

Compiler: **pdfLaTeX** whenever figures are PDF/PNG — the DVI path needs `.ps`/`.eps`.
State page count, error count, bibitem count against distinct `\cite` keys, comments
remaining, and the filename-charset result, all measured on the **extracted tarball**
rebuilt with `pdflatex` alone.

## Failure modes

- **Assert only what is easy.** Every trap here survived a plausible gate. When you
  add a check, remove the condition and confirm it *fails* before trusting a pass.
- **Measuring the wrong copy.** Staged figure directories shadow canonical ones and
  shells drift between directories. Use absolute paths for every measurement.
- **A guard that substitutes rather than stops.** Placeholder boxes and silent
  fallbacks convert a loud build failure into a quiet defect in the published PDF.
