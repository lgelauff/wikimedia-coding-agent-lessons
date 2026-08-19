---
name: charset-hygiene
description: Check text or code against a declared set of permitted characters — catching invisible Unicode, exotic spaces, and homoglyph lookalikes. Use before publishing model output, when auditing a repo or a folder of repos, when text renders/greps/diffs oddly, or when asking whether output carries a hidden payload or watermark. Runs on one string, one file, or a whole tree.
---

# Character-set hygiene

## The frame: allowlist, not blocklist

Do not ask "does this contain a known-bad character?" — that only ever catches
the tricks already known, and every new encoding trick defeats it.

Ask: **is every character in this file one I declared I wanted?** A file that
passes contains nothing but characters from a chosen set, so it behaves the
same on another machine, editor, terminal, or collaborator's checkout. That is
a guarantee; a blocklist cannot produce one.

The invisible tricks this catches have names — **Tags-block ASCII smuggling**,
**variation-selector byte channels**, **zero-width steganography**, **bidi / Trojan
Source** — but chasing the names is the losing game above: each is only ever another
reason a character falls outside the declared set.

Everything else follows. "Watermark removal" is not the goal and not a reliable
frame — most of what gets called an LLM watermark is an artifact, and framing
the work as removal invites a blunt filter that destroys real content.

## Tool

`scripts/charset_guard.py` — detection only, never writes to a scanned file.

```bash
# one output, before it goes anywhere
echo "$TEXT" | charset_guard.py -

# one file
charset_guard.py draft.md

# strict, for source code
charset_guard.py --profile ascii src/

# a document that genuinely needs other scripts
charset_guard.py --profile multilingual --scripts greek,cyrillic paper.tex

# content that genuinely needs the extras
charset_guard.py --allow emoji,math,box README.md

# whole folder of repos, unattended, manifest for the cleaner
charset_guard.py ~/Documents/GitHub --jsonl manifest.jsonl

# "what IS in here?" — describe, don't judge; use before choosing a profile
charset_guard.py --inventory .
```

As a library — same core at every scale:

```python
from charset_guard import check_text, check_file, check_tree, build_profile

check_text(model_output).ok            # single output, in memory
check_file("draft.md").ok              # single file
rep = check_tree(["~/Documents/GitHub"])
rep.by_risk(); rep.by_location()       # what, and where
```

Exit codes: `0` all in set, `1` out-of-set found, `2` usage/IO error — so it
drops into a hook or pre-commit unchanged.

## Choosing the permitted set

Start with `--inventory` to see what a tree actually contains, then declare
that. Do not start from the default and widen on each complaint.

| Profile | Permits | Use for |
|---|---|---|
| `ascii` | printable ASCII + tab/newline | source code, config, data files |
| `latin` | + Latin letters, curated typography | English/Dutch prose, Markdown |
| `multilingual` | + each script named in `--scripts` | papers, wiki content, quotes |

Opt-in groups: `typography` (on by default outside `ascii`), `math`, `box`,
`emoji`, `joiners`, `bidi`, `nbsp`, `crlf`.

Declaring a script pulls in what that script *needs*: `--scripts arabic`
implies `joiners` and `bidi`, because ZWNJ and directional controls are
orthography there, not decoration.

## Reading the output

Every finding says what is out of set, **why**, and **what would bring it in** —
either fix the character or widen the declaration. Both are valid answers; the
tool does not assume the character is wrong.

Findings marked `!!` are structurally invisible (`tags`, `varsel`,
`zero-width`, `bidi`, `control`, `surrogate`, `blank-filler`). Those are the
ones that matter: a human reviewing the file cannot see them. Runs that encode
a payload are decoded, so a Tags-block run is reported as the text it spells.

Findings marked `~` are visible characters outside the declared set — usually a
declaration to widen, not a problem.

**Report every run at a high level**: how many, of what kind, and where
(`by_location()` / the `where:` block groups per repo). Not a finding dump.

## What must never be stripped blindly

The reason this is an allowlist with declarations rather than a filter. Each of
these is a legitimate use of a codepoint that also appears in attacks, and each
has a regression test in `scripts/tests/test_charset_guard.py`:

- **ZWNJ/ZWJ in Persian, Arabic, Indic scripts** — orthographic. Removing them
  misspells words.
- **ZWJ in emoji sequences** — 👨‍👩‍👧 becomes three separate people.
- **VS16 after a pictograph** — emoji presentation selector.
- **Variation selectors after CJK** — ideographic variation sequences.
- **Tag characters inside subdivision flags** — 🏴󠁧󠁢󠁳󠁣󠁴󠁿 is *built from* Tags-block
  characters, the known casualty of a blanket tags-block filter.
- **BOM at offset 0** — a real BOM, not a hidden character.
- **Balanced bidi controls in genuine RTL text**.

Any change to the permitted set runs that suite before it lands.

## Unattended whole-tree runs

Built for an overnight pass over a folder of repos:

- Membership is decided once per *distinct* character and the positions found
  by regex, so scanning runs at ~90M characters/second — the walk and file I/O
  dominate, not the check.
- Pure-ASCII files bail out before any scan; most files in a tree are.
- Skipped: binaries (by null-byte and suffix), symlinks, files over
  `--max-bytes`, and vendor/build/VCS directories.
- Output is sorted and deterministic — two runs over an unchanged tree produce
  byte-identical reports, so diffing runs shows real drift.
- `--jsonl` writes one finding per line with codepoint offsets into the decoded
  text, which is the handover format for the cleaner. Nothing is ever written
  to a scanned file.

Pair with the `overnight-run` skill for the launch/rehearsal discipline.

## Keeping current

The threat surface — new LLM-watermarking and Unicode-smuggling channels — moves, but
reviewing it is a separate, roughly-weekly maintenance ritual, not part of a charset
check. It lives in [`references/threat-surface-review.md`](references/threat-surface-review.md)
to keep it off this skill's hot path.
