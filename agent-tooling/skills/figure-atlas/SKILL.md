---
name: figure-atlas
description: >-
  Gather every figure a research project has produced (across folders,
  worktrees and analysis sessions) into one browsable page: grouped by the
  paper's planned figures, a "what it means" paragraph per group, a caption
  per figure describing what it actually shows, a rebuilt/stale badge, and
  links to source and script. Use when figures are scattered and nobody can
  say which ones exist, before a writing push, an advisor or collaborator
  meeting, a figure-plan review, or when the user asks to "collect the
  figures", "show me all figures", "make an atlas/gallery of the plots", or
  "rebuild all figures". Use it INSTEAD of pasting images into chat or
  listing file paths: a list of paths says nothing about which figure is
  current, which carries a stale input, and which the paper needs.
---

# Figure atlas

*Introduced 2026-10-25 from the Paper 5 (wikipedia-drop-2026) session, where Lodewijk called the result
"super useful" and asked for it to be a standard component of research projects. That run: 169 figure files
from 3 checkouts → 100 unique figures in 12 groups, 149 rebuilt as-is, published as one private page.*

The atlas answers four questions at a glance: **which figures exist, which one is current, what each shows,
and what it means for the paper.** It is a working document, not the paper's figure set.

## Outputs (all inside the project's paper folder, owned by the session that runs this)

```
<paper>/figures/collection-<date>/   copies grouped by slot + INDEX.md (source, script, caveat per file)
<paper>/figures/rebuild-<date>/      optional as-is rebuild + REBUILD-LOG.md + scripts/ (patched copies + .diff)
<paper>/figures/atlas-<date>/        atlas.json (groups + intros), captions.tsv, figures.tsv, README.md
→ published page (private Artifact) built by scripts/build_atlas.py
```

## Steps

1. **Inventory.** `python3 scripts/inventory.py --root main=<repo> --root WT=<worktree> … --since <date>
   --keep '<regex of project areas>' > inventory.tsv`. It deduplicates by path relative to each checkout (newest
   copy wins) and lists every checkout a file was seen in. Exclude other projects' figures with `--keep`, not by hand.
2. **Map each figure to its script.** Grep the figure's stem in the project's scripts. An empty match is
   usually a variant (`_folded`, a dated rerun) of a sibling made by the same script with a flag — say so in the index.
   A pipeline driver that only lists stages is not the producer: name the stage script that calls `savefig`.
3. **Group by the paper's figure plan.** One group per planned figure, then data/appendix, figures another
   paper owns, and working figures. Ownership rules beat convenience: a figure about a question another paper owns
   goes in that paper's group even if it looks relevant.
4. **Collect copies + INDEX.md.** Copy (never move) into `collection-<date>/<group>/`. Keep older copies of the
   same name with a path-derived prefix rather than overwriting. INDEX columns: file · made (file time; note that a
   rebase resets it) · source checkout+path · script · caveat.
5. **(Optional) rebuild as-is.** See *Rebuild rules* below. Only when the user asks; it costs real machine time.
6. **Captions from the images, by a subagent.** Brief it with the project's vocabulary, then: open every image,
   describe only what is visible (axes, units, window, panels, the main visible pattern), quote only printed or
   plainly readable numbers, flag warning stamps ("PRELIMINARY"), and write "Unclear from the figure alone" rather
   than guess. Output `captions.tsv`. A cheap model is fine for this bounded task.
7. **Group intros by the session that knows the paper.** 2–4 sentences per group: what the figure is for in the
   paper, the headline it supports, and **whether its numbers are quotable yet** (registered / reviewed / provisional).
   This is the part captions cannot supply, and the part readers value most.
8. **Build and publish.** `python3 scripts/build_atlas.py --atlas atlas.json --figures figures.tsv --captions
   captions.tsv --out <scratch>/figpage`, then publish `figpage/index.html` as a private Artifact with every
   `figs/...` file in `files`. Prefer PNG where a PNG and SVG of the same figure exist; skip older duplicates.
9. **Save the builder inputs in the repo** (`atlas-<date>/`) so the page can be rebuilt when figures change, and
   give the user the link.

## Rebuild rules (step 5)

- **Never let a build script write into another session's folders.** Copy each script into
  `rebuild-<date>/scripts/`, patch **only** output paths (savefig, OUT/FIG constants, to_csv, open(..., 'w'),
  np.save, json.dump), save a `.diff` per script, grep the copy for every write call before running.
- **Prove it:** hash every file in the directories the original scripts would write to, before and after.
  Report differences with mtimes; other sessions are active, so a difference may not be yours.
- **Machine safety:** one run at a time, `nice -n 19`, a watchdog (peak RSS cap ~2 GB, 15-min timeout), check swap
  between runs and stop below a floor. Skip any script whose analysis step reads > 2 GB (`SKIPPED-HEAVY`).
- **Never regenerate deleted inputs or fetch data** to make a figure build; mark `SKIPPED-INPUT-DELETED` /
  `SKIPPED-INPUT-MISSING` and move on.
- Status set: REBUILT (byte/pixel-identical or metadata-only difference) · REBUILT-DIFFERS-VISIBLY (say why) ·
  FAILED · SKIPPED-HEAVY · SKIPPED-INPUT-DELETED · SKIPPED-INPUT-MISSING · SKIPPED-NO-SCRIPT · SKIPPED-NOT-A-BUILT-FIGURE (screenshots).
  Never claim identical without comparing.
- Keep non-figure outputs (`aux/`) out of git if the project's rules say analysis data is not pushed by writing sessions.

## Traps (each cost time on the first run)

- **Artifact publish refuses SVGs with a `<!DOCTYPE …>` line** (matplotlib writes one). `build_atlas.py` strips it
  from the page copies only.
- **A private Artifact cannot be previewed** from a browser pane that is not signed in to claude.ai. Do not sign in on
  the user's behalf; say the live page is unverified, or preview the local `index.html` instead (file:// may also be
  refused by the pane).
- **A captioning subagent that renders SVGs leaves browser tabs open** and can hit the tab cap. Close them after.
- **"Same as <sibling>" captions for variants hide real differences.** Ask the captioner to name the difference it sees,
  or to say it did not compare.
- **File mtimes are not creation dates** after a rebase or checkout; label the column "file time".
- **INDEX script attribution by grep is approximate**: the rebuild step finds the real producer; feed corrections back
  into INDEX.md.

## What this skill does not do

It does not decide which figures go in the paper, restyle figures, or fix stale analyses. It shows what exists,
what state each is in, and what each is for, so that those decisions can be made quickly.
