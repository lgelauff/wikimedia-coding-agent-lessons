# Playbook: latex-change-review

Make a change to a LaTeX document and show it the *right* way — text diff for
content, before/after images for styling — in a time- and token-efficient manner.
Agent-neutral; an adapter (a Claude skill) supplies the wiring.

## Method

### 1. Snapshot before editing
Copy the target `.tex` (and any files you'll touch) to a `before/` dir. This is
the ground truth to diff against — works whether or not the project is in git.

### 2. Make the change
Edit the working copy as requested.

### 3. Classify: content vs styling vs both
Run the classifier (`latex_classify.py before.tex after.tex`). Heuristic:
- **Preamble** changes (packages, geometry, fonts, colors, lengths, macro defs) → **styling**.
- **Body** changes where the prose-with-commands-stripped is unchanged → **styling**
  (only markup/wrapping/spacing moved).
- **Body** changes where the underlying words differ → **content**.
- Both present → **mixed → do both views.**

### 4a. Content view (no compile — fast, cheap)
Use `latex_diff_html.py`:
- **Short change** → inline wdiff text (`the [-old-]{+new+} wording`) shown directly.
- **Long change** → a **Wikipedia-style two-column HTML** file (old | new, word-level
  del/ins) — deliver the path / open it, instead of dumping it into the chat.
Never compile for content-only changes.

### 4b. Styling view (compile + image, only what moved)
Use `latex_visual_diff.py --before before/main.tex --after main.tex`:
- detects the build (latexmk / pdflatex / xelatex; honors `% !TEX program`),
- compiles both, rasterizes (pdftoppm),
- **pixel-diffs pages and skips identical ones**, crops each changed page to the
  changed region (padded), and writes `pageN-old.png` / `pageN-new.png`.
Show only the changed-region pairs — don't render or display unchanged pages.

### 5. Report
- Content: the inline diff or the HTML path.
- Styling: the old/new cropped PNG pairs, one per changed page.
- Mixed: both, labeled.

## Efficiency rules (the point of the skill)
- **Compile only when styling is involved.** Content-only changes never compile.
- **Show only what changed** — changed pages/regions, not whole PDFs.
- **Long content → file, not chat** (HTML), keeping tokens low.
- Reuse the snapshot; don't recompile the "before" if its PDF already exists.

## Failure modes
- Compile fails → report the last ~800 chars of the log; don't fake a visual diff.
- No toolchain (latexmk/pdftoppm/Pillow) → say so; for content changes you still
  have the full text/HTML diff (no compile needed).
