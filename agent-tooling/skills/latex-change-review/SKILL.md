---
name: latex-change-review
description: >-
  Show what actually changed in a LaTeX document. Use whenever a .tex file has
  been edited and someone wants to see or review the result — "show me what
  changed", "what did you change in the paper", "I reworked the intro and
  tightened the methods", or any request to review an edit to a paper, poster or
  slides. Use it INSTEAD of `git diff`: reaching for the raw diff is the obvious
  move and it fails twice over on LaTeX. Rewrapped prose shows as a whole
  paragraph rewritten when a single word moved, and a styling change is worse than
  useless — altering one spacing macro reads as a one-character edit while moving
  half the page. This classifies the change first, then shows content as a
  readable text diff and styling as cropped before/after images of only the pages
  that visually moved, compiling only when it has to.
---

# latex-change-review

Claude adapter over the agent-neutral **latex-change-review playbook**. Read it:
[`../../playbooks/latex-change-review.md`](../../playbooks/latex-change-review.md).
The decision logic + rendering live in `scripts/`; this is the wiring.

## Steps

1. **Snapshot** the file(s) before editing → a `before/` dir (works without git).
2. **Edit** the working copy.
3. **Classify** the change:
   ```bash
   python3 "$SKILL_DIR/../../scripts/latex_classify.py" before/main.tex main.tex
   ```
   → `content` / `styling` / both. Mixed ⇒ do both views.
4. **Content view (no compile):**
   ```bash
   python3 "$SKILL_DIR/../../scripts/latex_diff_html.py" before/main.tex main.tex \
       --out .latex-review/content-diff.html
   ```
   Short → it prints the inline `[-old-]{+new+}` diff; show it directly. Long → it
   writes the Wikipedia-style two-column HTML; share the path (don't paste it).
5. **Styling view (compile + image):**
   ```bash
   python3 "$SKILL_DIR/../../scripts/latex_visual_diff.py" \
       --before before/main.tex --after main.tex --out .latex-review/shots
   ```
   It compiles both, finds the changed pages, and writes `pageN-old.png` /
   `pageN-new.png` cropped to the changed region. Display each pair (old then new).
   If `latexmk`/`pdftoppm`/Pillow are missing, say so — content diffs still work.

## Allowlist (keep it prompt-free)
`Bash(python3 *latex_classify.py*)`, `Bash(python3 *latex_diff_html.py*)`,
`Bash(python3 *latex_visual_diff.py*)`, `Bash(latexmk *)`, `Bash(pdftoppm *)`.

## Environments
- **Claude Code:** as above — needs a LaTeX toolchain + poppler + Pillow on PATH.
- **Cowork:** same scripts, but run in the VM and write outputs to `/outputs/`
  (set `--out /outputs/latex-review`); ensure the LaTeX toolchain is in the VM,
  and remember network isn't needed (purely local compile + image work).

## Why it's efficient
Content-only changes **never compile**; long content goes to an **HTML file** not
the chat; styling shows **only the changed page-regions**, not whole PDFs.
