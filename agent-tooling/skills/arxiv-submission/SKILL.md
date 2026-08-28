---
name: arxiv-submission
description: >-
  Prepare a LaTeX paper for arXiv and prove it is ready. Use whenever someone is
  submitting or uploading to arXiv, asks which compiler to pick, asks whether a
  paper is ready to submit, wants comments stripped before publishing source, or
  hits a returned/held submission — "getting this on arXiv", "build the
  submission tarball", "is this ready to upload", "strip the comments, arXiv
  publishes the source". Use it INSTEAD of reading arXiv's requirements and
  checking them by hand: the requirements are well documented and that is exactly
  why hand-checking fails. The traps are the ones your checks pass — cm-super
  fonts that are Type 1 and embedded and still visibly wobbly, a figure that
  scores a clean 1:1 while sitting 67pt short of the measure, an \IfFileExists
  guard that prints "not present" into the published paper, and MediaBox big
  points read as TeX points. This asserts the document's own geometry, strips
  comments, and verifies by rebuilding the extracted tarball with pdflatex alone.
---

# arxiv-submission

Claude adapter over the agent-neutral **arxiv-submission playbook**. Read it:
[`../../playbooks/arxiv-submission.md`](../../playbooks/arxiv-submission.md).

## Claude-specific notes

- **Measure with absolute paths.** The Bash tool resets its working directory
  between calls. A relative `pdfinfo figures/x.pdf` silently reads a *staged* copy
  instead of the canonical one and reports that a regeneration did nothing.
- **Rebuild before comparing.** Do not diff against a PDF you did not just build in
  this turn; a stale reference returns a false "identical".
- **`timeout` does not exist on macOS.** A loop that wraps each step in it returns
  `rc=127` for every step and still prints "ALL DONE". Set a failure flag inside the
  loop and report it, or the runner is a check that cannot fail.
- **Figure pipelines are slow.** Scripts that load a large corpus run for minutes;
  run them backgrounded and poll, one at a time, verifying each output before
  starting the next.
- **Respect file ownership.** In repos where an author owns the prose files, do not
  edit a `.tex` that is held or has uncommitted changes — the build layer
  (`main.tex` preamble, Makefile, check scripts) is usually enough to fix
  typography without touching content.
- When you add an assertion, **verify it fails** with the condition removed before
  reporting that it passes.
