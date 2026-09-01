# LaTeX Lessons - Full Content

Traps in building, verifying and syncing LaTeX documents. The unifying theme: **LaTeX
keeps going and still writes a PDF**, so "it compiled" and "a PDF exists" are not
evidence of anything. Every check below has to be asserted explicitly or it is never
seen.

Companion to [`agent-tooling/playbooks/arxiv-submission.md`](../agent-tooling/playbooks/arxiv-submission.md)
(packaging for submission) and
[`agent-tooling/playbooks/latex-change-review.md`](../agent-tooling/playbooks/latex-change-review.md)
(showing what an edit changed).

## Docs to fetch at project start

- 🤖 https://www.overleaf.com/learn/how-to/Using_the_History_feature
- 🤖 https://www.overleaf.com/learn/latex/Errors
- 🤖 https://ctan.org/pkg/authblk

## The build gate decides what "clean" means

- **A narrow assertion is a false pass, and it is worse than no check.** A build script
  that counted only undefined references reported "builds clean, 0 undefined" for four
  commits while the log held **9 `! ` errors**. They surfaced only when someone opened
  the same project in Overleaf, which shows an error count in its UI. Nothing was wrong
  with the verification *habit* — the artifact was built and inspected every time — the
  assertion just measured the wrong property.
- **Gate on all of these, not just the one that bit you last time**: `^! ` error count,
  `undefined` count, `multiply defined` (duplicate labels), and bibliography entries
  against distinct `\cite` keys. Each is a separate `grep`; each has leaked at least
  once in practice.
- **`multiply defined` is the quietest of them.** Two sections sharing a `\label` is
  legal, produces a warning, and any `\ref` to it silently resolves to whichever LaTeX
  read last. If neither is referenced yet, it is a landmine for whoever adds the first
  `\ref`.
- **Count bibliography entries with the macro your `.bst` actually emits.** `apsr.bst`
  and other Harvard styles emit `\harvarditem`, not `\bibitem`; grepping for `\bibitem`
  returns 0 and looks like a catastrophic failure rather than a wrong pattern.

## Carrying a build gate into a hosted editor

- **Overleaf runs its own build; your script does not travel. The assertions can.**
  Put them in the document (`\AtEndDocument`) and they fire wherever it compiles.
  This matters because the checks worth having are precisely the ones a hosted
  editor's *Errors* counter ignores: a duplicate label sits under Warnings while
  Errors reads 0.
- **There is no `\ifG@refundefined`.** The obvious form is wrong. `\G@refundefinedtrue`
  is a plain `\def` that redefines `\@refundefined`, which LaTeX leaves as `\relax`
  otherwise — so the test is `\ifx\@refundefined\relax\else ... \fi`, the same shape
  as `\@multiplelabels`. Writing `\ifG@refundefined` gives `Undefined control
  sequence` followed by `Extra \fi`, which reads like a brace bug in your own code.
- **Duplicate labels need two compiler passes to surface.** They are detected when the
  `.aux` is *read back*, not when it is written. A one-pass test of a duplicate-label
  check will report that the check does not work.
- **Give the bypass a name and a rule.** `\gateoff` before `\begin{document}`, with
  "do not commit it switched off" in the file. A gate with no escape hatch gets deleted
  the first time it is inconvenient.
- **Watch what your own error text does to your other checks.** A gate message
  containing the word "undefined" was counted by a build script grepping the log for
  `undefined`, so the gate inflated the very number it existed to protect. Match on the
  real warning shape (`(Reference|Citation) .* undefined`), not a bare word.

## BibTeX exits non-zero on warnings

- **`set -e` in a build script kills the build at the BibTeX pass.** BibTeX returns a
  non-zero status for mere warnings — an empty `publisher` field is enough. With
  `set -e` the two follow-up `pdflatex` runs never happen, and the script *still leaves
  a PDF behind* from the first pass: one with every citation unresolved. It reads as
  success. Either drop `set -e` or write `bibtex "$f" || true`.

## Unescaped `_` in `.bib` url/doi fields

- **A bare `_` in a `url` or `doi` field is math-mode subscript to TeX**, giving
  `Missing $ inserted`, `Extra }`, and `Missing } inserted` — all reported against the
  generated `.bbl`, whose line numbers mean nothing to you. Escape as `\_` in the
  `.bib`. Zotero exports them unescaped.
- **The tell in the output is a split word.** `type/journal_article` renders as
  "journala rticle" in the PDF. If a URL in a bibliography looks like it has a stray
  space, look for an underscore before you look at line breaking.

## `authblk` expands the `\author` argument

- **`\href` or `\includegraphics` inside `\author` breaks `authblk`** with
  `! Use of \author doesn't match its definition.` — an error that names neither the
  package nor the real culprit. `authblk` runs `\xdef` over the author argument, and
  those commands do not survive full expansion on older `authblk`. Fix by prefixing
  `\protect` to each: `\protect\href{...}{\protect\includegraphics[...]{orcid.pdf}...}`.
  Harmless where expansion was already safe, so it is a portable fix, not a workaround.
- **Suspect the content before the toolchain.** This looks exactly like an
  old-TeX-Live-vs-new-TeX-Live problem, and it is easy to conclude the local
  installation is at fault and move on. Bisect the `\author` block itself: strip it to
  a bare name, then add one construct back at a time.
- **Watch out for `echo` when generating minimal test cases in zsh.** `echo '\usepackage'`
  emits a NUL byte (`\u` is a unicode escape) and `echo '\begin'` emits a backspace,
  producing `Text line contains an invalid character` — an error in your test harness
  that looks like a finding about the document. Write test files with `printf '%s'`,
  a quoted heredoc, or Python.

## Overleaf sync (free tier, no git bridge)

- **Overleaf does not expand a zip uploaded into an existing project.** It stores the
  `.zip` as an inert file in the tree. Zip expansion happens only when *creating* a new
  project from one — which gives a new URL and leaves collaborators and comments behind
  on the old project.
- **Uploading a parent folder nests everything one level deep and breaks `\input`.**
  LaTeX resolves `\input{sections/foo}` against the **compilation directory** — always
  the project root — not the directory the main file lives in. So a `main.tex` sitting
  inside an uploaded wrapper folder looks for `sections/` at the root and does not find
  it. Upload the *sub*folders, with no folder selected in the tree, so they land at the
  root. If it nests anyway, drag the items out and delete the wrapper; nothing is lost.
- **Download and diff before every upload.** The free tier has no divergence check —
  an upload silently overwrites whatever a co-author changed — and only a short version
  history window, so "restore from history" will not recover an edit made months ago.
  `Menu → Download → Source`, then `diff` against your local copy. That diff is the only
  protection there is. The paid git bridge fails safe instead, rejecting a
  non-fast-forward push; the free tier gives you nothing.
- **Conflicts have no resolver on the Overleaf side, even with the git bridge.** The web
  editor has no merge UI and no concept of a conflict; real-time collaborative edits
  merge live between web users. Conflicts exist only at the git boundary, so whoever
  holds the clone makes every merge decision alone, and co-authors are never shown how
  it was resolved.
- **Overleaf caches the `.bbl`.** After fixing a `.bib`, a plain Recompile can keep
  serving the old bibliography and its errors. Use **Recompile from scratch**.
- **A multi-file project needs its folders recreated by hand**, and the names must match
  the `\input` paths exactly. A typo gives `File not found` pointing at the `\input`
  line, not at the folder.

## Filenames

See [`arxiv-submission.md` §6](../agent-tooling/playbooks/arxiv-submission.md) — macOS
screenshot names carry **U+202F NARROW NO-BREAK SPACE** before `AM`/`PM`. Normalise
programmatically; never retype a filename you have only seen printed. The same names
break Overleaf uploads and zip round-trips, not just arXiv.
