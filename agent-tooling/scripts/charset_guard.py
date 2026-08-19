#!/usr/bin/env python3
"""Check that text and code stay inside a declared set of permitted characters.

ALLOWLIST, not blocklist. The question this asks is never "does this file
contain a known-bad character?" — that can only ever catch the tricks we
already know about. It asks "is every character in this file one I declared
I wanted?" That is the only form of the check that yields a portability
guarantee: a file that passes contains nothing but characters from a set you
chose, so it survives a different editor, terminal, filesystem, or collaborator
without silently changing meaning.

Anything outside the declared set is reported with (a) why it is out of set and
(b) what it would take to bring it in — either fix the character, or widen the
declaration. Out-of-set characters that belong to a known abuse family are
annotated as such and, where they encode a payload, decoded.

DETECTION ONLY — this script never writes to a file. Cleanup is a separate
tool that consumes this one's `--jsonl` manifest.

Profiles (the permitted set):

  ascii         Printable ASCII plus tab/newline/CR. Nothing else at all.
                The right default for source code.
  latin         ASCII plus Latin-script letters (accents, ligatures) plus a
                curated typographic punctuation set (en/em dash, curly quotes,
                ellipsis, degree, currency). The right default for prose.
  multilingual  latin plus every script named with --scripts. Declaring a
                script that needs them also permits its joiners and marks.

Opt-in groups (--allow), for content that genuinely needs them:

  typography  – — ' ' " " … • § ¶ ° ± × ÷ © ® ™ ‰ † ‡ « » ′ ″ − (on by
              default in latin/multilingual)
  math        ← → ⇒ ≈ ≠ ≤ ≥ ∀ ∈ ∑ √ ∞ … (Sm/Mathematical Operators)
  box         Box drawing and block elements, for ASCII-art diagrams
  emoji       Pictographs, plus the ZWJ and VS16 that emoji sequences require
  joiners     ZWJ/ZWNJ standalone (implied by Arabic/Indic/Hebrew scripts)
  bidi        Bidirectional controls (implied by RTL scripts)
  nbsp        U+00A0 no-break space
  crlf        Carriage return, for files that must keep CRLF endings

Exit codes: 0 = every character in set, 1 = out-of-set characters found,
2 = usage or IO error. Suitable as a hook or pre-commit gate.

Usage:
  charset_guard.py FILE [FILE ...]              # files and/or directories
  charset_guard.py --profile ascii src/
  charset_guard.py --profile multilingual --scripts greek,cyrillic paper.tex
  charset_guard.py --allow emoji,math README.md
  charset_guard.py --inventory .                # what IS in here? (no verdict)
  charset_guard.py --jsonl out.jsonl ~/Documents/GitHub   # cleaner manifest
  echo "text" | charset_guard.py -
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# The permitted set
# --------------------------------------------------------------------------

ASCII_RANGES = ((0x20, 0x7E),)
ALWAYS_OK = {0x09, 0x0A}  # tab, newline

TYPOGRAPHY = {
    0x00A1, 0x00A7, 0x00A9, 0x00AB, 0x00B0, 0x00B1, 0x00B6, 0x00BB, 0x00BF,
    0x00D7, 0x00F7, 0x2010, 0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D,
    0x2020, 0x2021, 0x2022, 0x2026, 0x2030, 0x2032, 0x2033, 0x2039, 0x203A,
    0x20AC, 0x00A3, 0x00A5, 0x00A2, 0x2122, 0x00AE, 0x2212,
}
MATH_RANGES = ((0x2190, 0x21FF), (0x2200, 0x22FF), (0x27F0, 0x27FF),
               (0x2A00, 0x2AFF), (0x0370, 0x03FF))
BOX_RANGES = ((0x2500, 0x259F), (0x25A0, 0x25FF))
EMOJI_RANGES = (
    (0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x1F1E6, 0x1F1FF),
    (0x2190, 0x21AA), (0x231A, 0x231B), (0x23E9, 0x23FA), (0x25AA, 0x25FE),
    (0xFE0F, 0xFE0F), (0x200D, 0x200D), (0x20E3, 0x20E3),
)

# Scripts, as the first word of the Unicode character name. That prefix is a
# reliable script proxy for letters and marks (the only categories we use it
# for) and needs no data file beyond the stdlib.
SCRIPT_ALIASES = {
    "latin": {"LATIN", "MODIFIER"},
    "greek": {"GREEK"},
    "cyrillic": {"CYRILLIC"},
    "arabic": {"ARABIC"},
    "hebrew": {"HEBREW"},
    "devanagari": {"DEVANAGARI"},
    "bengali": {"BENGALI"},
    "tamil": {"TAMIL"},
    "thai": {"THAI"},
    "hangul": {"HANGUL"},
    "hiragana": {"HIRAGANA"},
    "katakana": {"KATAKANA"},
    "han": {"CJK", "IDEOGRAPHIC", "KANGXI"},
    "armenian": {"ARMENIAN"},
    "georgian": {"GEORGIAN"},
    "ethiopic": {"ETHIOPIC"},
}
# Scripts whose orthography requires ZWJ/ZWNJ, or which are right-to-left.
NEEDS_JOINERS = {"arabic", "hebrew", "devanagari", "bengali", "tamil"}
NEEDS_BIDI = {"arabic", "hebrew"}
# Scripts that supply Latin lookalikes — mixing these is the confusable risk.
CONFUSABLE_SCRIPTS = {"LATIN", "CYRILLIC", "GREEK", "COPTIC", "CHEROKEE", "ARMENIAN"}


@dataclass
class Profile:
    name: str
    scripts: set = field(default_factory=set)      # allowed letter/mark scripts
    codepoints: set = field(default_factory=set)   # allowed non-letter codepoints
    ranges: tuple = ()                             # allowed non-letter ranges
    allows: set = field(default_factory=set)       # enabled opt-in groups
    max_cp: int | None = None                      # hard ceiling (ascii profile)
    # Membership is decided once per distinct character and reused for the rest
    # of the run. Excluded from pickling so worker processes start cold rather
    # than shipping a fat cache across the process boundary.
    _member_cache: dict = field(default_factory=dict, repr=False, compare=False)
    _regex_cache: dict = field(default_factory=dict, repr=False, compare=False)

    def __getstate__(self):
        state = self.__dict__.copy()
        state["_member_cache"] = {}
        state["_regex_cache"] = {}
        return state

    def describe(self) -> str:
        bits = [f"profile={self.name}"]
        if self.scripts:
            bits.append("scripts=" + ",".join(sorted(self.scripts)))
        if self.allows:
            bits.append("allow=" + ",".join(sorted(self.allows)))
        return " ".join(bits)


def build_profile(name: str, scripts=(), allows=()) -> Profile:
    allows = set(allows)
    scripts = {s.strip().lower() for s in scripts if s.strip()}

    if name == "ascii":
        return Profile("ascii", scripts={"LATIN"}, ranges=ASCII_RANGES,
                       allows=allows, max_cp=0x7F)

    declared = {"latin"} | (scripts if name == "multilingual" else set())
    unknown = declared - set(SCRIPT_ALIASES)
    if unknown:
        raise ValueError(
            f"unknown script(s): {', '.join(sorted(unknown))}. "
            f"known: {', '.join(sorted(SCRIPT_ALIASES))}"
        )
    # Declaring a script implies the machinery that script needs.
    if declared & NEEDS_JOINERS:
        allows.add("joiners")
    if declared & NEEDS_BIDI:
        allows.add("bidi")
    allows.add("typography")

    script_names = set()
    for s in declared:
        script_names |= SCRIPT_ALIASES[s]
    return Profile(name, scripts=script_names, ranges=ASCII_RANGES,
                   codepoints=set(TYPOGRAPHY), allows=allows)


# --------------------------------------------------------------------------
# Why a character is out of set: known abuse families, used as annotation
# --------------------------------------------------------------------------

TAGS_START, TAGS_END, TAG_CANCEL = 0xE0000, 0xE007F, 0xE007F
BLACK_FLAG = 0x1F3F4
VS_LOW, VS_SUP = (0xFE00, 0xFE0F), (0xE0100, 0xE01EF)

ZERO_WIDTH = {0x200B, 0x200C, 0x200D, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0xFEFF}
BIDI_CONTROLS = {0x061C, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D,
                 0x202E, 0x2066, 0x2067, 0x2068, 0x2069}
EXOTIC_SPACES = {
    0x00A0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006,
    0x2007, 0x2008, 0x2009, 0x200A, 0x202F, 0x205F, 0x3000, 0x180E,
}
BLANK_FILLERS = {0x115F, 0x1160, 0x17B4, 0x17B5, 0x2800, 0x3164, 0xFFA0}
DEPRECATED_FORMAT = {0x00AD, 0x034F, 0x206A, 0x206B, 0x206C, 0x206D, 0x206E,
                     0x206F, 0xFFF9, 0xFFFA, 0xFFFB, 0xFFFC}

RISK_NOTES = {
    "tags": "Unicode Tags block — an invisible twin of every printable ASCII "
            "character; renders as nothing but is read by tokenizers",
    "varsel": "variation selector — 256 invisible codepoints usable as a byte channel",
    "zero-width": "zero-width character — invisible, used for binary steganography",
    "bidi": "bidirectional control — can make displayed order differ from real order "
            "(Trojan Source, CVE-2021-42574)",
    "exotic-space": "non-ASCII space — looks like a space, is not one; breaks "
                    "grep, diffs, and wikitext",
    "blank-filler": "renders blank but is not a space character",
    "deprecated-format": "deprecated or annotation format character",
    "control": "control character",
    "surrogate": "lone surrogate — can recombine into a Tags-block payload",
    "private-use": "private use area — meaning depends entirely on the font",
    "unassigned": "unassigned codepoint — no defined meaning in this Unicode version",
    "confusable-script": "letter from an undeclared script that looks like a "
                         "declared one; the classic homoglyph substitution",
    "off-script": "letter from a script this profile does not declare",
    "non-ascii-letter": "letter from a declared script, but outside ASCII",
    "off-set-symbol": "symbol or punctuation outside the declared set",
    "emoji": "pictograph",
}
# Which risks are structurally invisible — the ones that matter most.
INVISIBLE_RISKS = {"tags", "varsel", "zero-width", "bidi", "blank-filler",
                   "deprecated-format", "control", "surrogate"}


def _in(cp: int, ranges) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def script_of(ch: str) -> str:
    try:
        return unicodedata.name(ch).split()[0]
    except ValueError:
        return ""


def char_name(cp: int) -> str:
    try:
        return unicodedata.name(chr(cp))
    except ValueError:
        return f"<unnamed U+{cp:04X}>"


def classify_risk(cp: int, cat: str, profile: "Profile") -> str:
    """Name the family an out-of-set character belongs to."""
    if TAGS_START <= cp <= TAGS_END:
        return "tags"
    if _in(cp, (VS_LOW, VS_SUP)):
        return "varsel"
    if cp in ZERO_WIDTH:
        return "zero-width"
    if cp in BIDI_CONTROLS:
        return "bidi"
    if cp in EXOTIC_SPACES or cat in ("Zs", "Zl", "Zp"):
        return "exotic-space"
    if cp in BLANK_FILLERS:
        return "blank-filler"
    if cp in DEPRECATED_FORMAT or cat == "Cf":
        return "deprecated-format"
    if cat == "Cs":
        return "surrogate"
    if cat == "Co":
        return "private-use"
    if cat == "Cn":
        return "unassigned"
    if cat == "Cc":
        return "control"
    if cat[0] in "LM":
        script = script_of(chr(cp))
        if script in profile.scripts:
            # Declared script; out of set only because of the ASCII ceiling.
            return "non-ascii-letter"
        if script in CONFUSABLE_SCRIPTS and profile.scripts & CONFUSABLE_SCRIPTS:
            return "confusable-script"
        return "off-script"
    if _in(cp, EMOJI_RANGES):
        return "emoji"
    return "off-set-symbol"


def remedy(risk: str, cp: int) -> str:
    """What it would take to bring this character into the set."""
    if risk in ("tags", "varsel", "zero-width", "blank-filler", "surrogate"):
        return "delete it — it carries no visible content"
    if risk == "exotic-space":
        return "replace with U+0020 SPACE, or --allow nbsp if the no-break is intended"
    if risk == "bidi":
        return "delete it, or --allow bidi if this file is genuinely bidirectional"
    if risk == "deprecated-format":
        return "delete it"
    if risk == "control":
        return "delete it, or --allow crlf if this is a CR in a CRLF ending"
    if risk == "non-ascii-letter":
        return "replace with its ASCII equivalent, or use --profile latin"
    if risk in ("confusable-script", "off-script"):
        script = script_of(chr(cp)).lower()
        return (f"replace with the lookalike from a declared script, or declare it: "
                f"--profile multilingual --scripts {script}")
    if risk == "emoji":
        return "remove it, or --allow emoji"
    if risk == "private-use":
        return "replace with a standard codepoint"
    return "replace with an ASCII equivalent, or --allow typography/math/box"


# --------------------------------------------------------------------------
# Membership test
# --------------------------------------------------------------------------

def _permitted_cp(ch: str, p: Profile) -> bool:
    """Is this character in the permitted set? Position-independent.

    The one position-dependent rule — tag characters inside an emoji tag
    sequence — is applied by scan_text, so this stays memoizable per character.
    """
    cp = ord(ch)

    if cp in ALWAYS_OK:
        return True
    if cp == 0x0D:
        return "crlf" in p.allows
    if p.max_cp is not None and cp > p.max_cp:
        return False
    if _in(cp, p.ranges) or cp in p.codepoints:
        return True

    cat = unicodedata.category(ch)

    # Letters and marks are decided by declared script.
    if cat[0] in "LM" and not _in(cp, (VS_LOW, VS_SUP)):
        return script_of(ch) in p.scripts

    if "typography" in p.allows and cp in TYPOGRAPHY:
        return True
    if "math" in p.allows and _in(cp, MATH_RANGES) and cat in ("Sm", "So", "Ll", "Lu"):
        return True
    if "box" in p.allows and _in(cp, BOX_RANGES):
        return True
    if "nbsp" in p.allows and cp == 0x00A0:
        return True
    if "bidi" in p.allows and cp in BIDI_CONTROLS:
        return True
    if "joiners" in p.allows and cp in (0x200C, 0x200D):
        return True

    if "emoji" in p.allows and _in(cp, EMOJI_RANGES):
        return True
    return False


def emoji_tag_spans(text: str):
    """Spans of valid emoji tag sequences: U+1F3F4 + tag chars + U+E007F."""
    spans, i = [], 0
    while i < len(text):
        if ord(text[i]) == BLACK_FLAG:
            j = i + 1
            while j < len(text) and TAGS_START <= ord(text[j]) < TAG_CANCEL:
                j += 1
            if j > i + 1 and j < len(text) and ord(text[j]) == TAG_CANCEL:
                spans.append((i, j))
                i = j + 1
                continue
        i += 1
    return spans


# --------------------------------------------------------------------------
# Payload decoding (forensics on what an invisible run actually spells)
# --------------------------------------------------------------------------

def decode_tags(cps):
    out = [chr(cp - TAGS_START) for cp in cps
           if 0x20 <= cp - TAGS_START <= 0x7E]
    text = "".join(out)
    return text if text.strip() else None


def decode_varsel(cps):
    data = bytearray()
    for cp in cps:
        if VS_LOW[0] <= cp <= VS_LOW[1]:
            data.append(cp - VS_LOW[0])
        elif VS_SUP[0] <= cp <= VS_SUP[1]:
            data.append((cp - VS_SUP[0] + 16) & 0xFF)
        else:
            return None
    if len(data) < 2:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text if text.isprintable() and text.strip() else None


def decode_zero_width(cps):
    """The common ZWSP=0 / ZWNJ=1 binary encoding, 8 bits per character."""
    bits = ""
    for cp in cps:
        if cp == 0x200B:
            bits += "0"
        elif cp == 0x200C:
            bits += "1"
        else:
            return None
    if len(bits) < 16 or len(bits) % 8:
        return None
    text = "".join(chr(int(bits[i:i + 8], 2)) for i in range(0, len(bits), 8))
    return text if text.isprintable() and text.strip() else None


DECODERS = {"tags": decode_tags, "varsel": decode_varsel, "zero-width": decode_zero_width}


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------

@dataclass
class Finding:
    path: str
    line: int
    col: int
    offset: int
    risk: str
    codepoints: list
    names: list
    note: str
    remedy: str
    context: str
    decoded: str | None = None

    @property
    def invisible(self) -> bool:
        return self.risk in INVISIBLE_RISKS

    def to_dict(self):
        d = {k: v for k, v in self.__dict__.items()}
        d["codepoints"] = [f"U+{cp:04X}" for cp in self.codepoints]
        d["invisible"] = self.invisible
        return d


def _render_context(text, start, end, width=30):
    lo, hi = max(0, start - width), min(len(text), end + width)
    def safe(s):
        return "".join(
            c if c.isprintable() and unicodedata.category(c) not in ("Cf", "Cc")
            else "·" for c in s
        ).replace("\n", "⏎")
    marked = "".join(f"⟦U+{ord(c):04X}⟧" for c in text[start:end])
    return f"{safe(text[lo:start])}{marked}{safe(text[end:hi])}"


def _bad_char_matcher(text: str, profile: Profile):
    """Regex matching every character in `text` that is outside the set.

    The hot path. Deciding membership per character in Python costs more than
    a whole-tree run can afford (a scan of a folder of repos is >100M
    characters), so membership is decided once per DISTINCT character —
    memoized on the profile — and the positions are then found by a regex,
    which scans at C speed. Python-level work drops from O(characters) to
    O(distinct characters + occurrences of bad ones).
    """
    cache = profile._member_cache
    bad_chars = []
    for ch in set(text):  # C-speed pass over the text
        ok = cache.get(ch)
        if ok is None:
            ok = _permitted_cp(ch, profile)
            cache[ch] = ok
        if not ok:
            bad_chars.append(ch)
    if not bad_chars:
        return None
    key = "".join(sorted(bad_chars))
    matcher = profile._regex_cache.get(key)
    if matcher is None:
        matcher = re.compile("[" + "".join(re.escape(c) for c in key) + "]")
        profile._regex_cache[key] = matcher
    return matcher


def scan_text(text: str, profile: Profile, path: str = "") -> list:
    if not text:
        return []

    matcher = _bad_char_matcher(text, profile)
    if matcher is None:
        return []
    bad = [m.start() for m in matcher.finditer(text)]
    if not bad:
        return []

    # Tag characters inside a subdivision flag are legitimate; that is the one
    # membership rule that depends on position, so it is applied here rather
    # than in the per-character test.
    if "emoji" in profile.allows:
        tag_spans = emoji_tag_spans(text)
        if tag_spans:
            bad = [i for i in bad
                   if not any(lo < i <= hi for lo, hi in tag_spans)]
            if not bad:
                return []

    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    def line_col(off):
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= off:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, off - starts[lo] + 1

    risks = {i: classify_risk(ord(text[i]), unicodedata.category(text[i]), profile)
             for i in bad}

    findings, k = [], 0
    while k < len(bad):
        start = bad[k]
        risk = risks[start]
        j = k
        while j < len(bad) and bad[j] == start + (j - k) and risks[bad[j]] == risk:
            j += 1
        end = start + (j - k)
        cps = [ord(c) for c in text[start:end]]
        line, col = line_col(start)
        findings.append(Finding(
            path=path, line=line, col=col, offset=start, risk=risk,
            codepoints=cps, names=[char_name(cp) for cp in cps],
            note=RISK_NOTES.get(risk, "outside the permitted set"),
            remedy=remedy(risk, cps[0]),
            context=_render_context(text, start, end),
            decoded=DECODERS[risk](cps) if risk in DECODERS else None,
        ))
        k = j
    return findings


# --------------------------------------------------------------------------
# Public API — one string, one file, or a whole tree, over the same core
# --------------------------------------------------------------------------

@dataclass
class Report:
    """Result of a check at any scale. `ok` is the only thing most callers need."""
    findings: list = field(default_factory=list)
    files_scanned: int = 0
    files_skipped: int = 0
    profile: str = ""

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def invisible(self) -> list:
        return [f for f in self.findings if f.invisible]

    def by_risk(self) -> dict:
        out = {}
        for f in self.findings:
            out[f.risk] = out.get(f.risk, 0) + 1
        return out

    def by_location(self, depth: int = 1) -> dict:
        """Findings grouped by the first `depth` path components — the "where".

        On a folder of repos this is a per-repo tally, which is the level a
        run report should lead with.
        """
        out = {}
        for f in self.findings:
            parts = Path(f.path).parts if f.path else ()
            key = str(Path(*parts[:depth])) if parts else "<input>"
            entry = out.setdefault(key, {"total": 0, "invisible": 0, "files": set()})
            entry["total"] += 1
            entry["invisible"] += int(f.invisible)
            entry["files"].add(f.path)
        return {k: {"total": v["total"], "invisible": v["invisible"],
                    "files": len(v["files"])}
                for k, v in sorted(out.items(), key=lambda kv: -kv[1]["total"])}

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "ok": self.ok,
            "files_scanned": self.files_scanned,
            "files_skipped": self.files_skipped,
            "files_with_findings": len({f.path for f in self.findings if f.path}),
            "out_of_set": len(self.findings),
            "invisible": len(self.invisible),
            "by_risk": self.by_risk(),
            "by_location": self.by_location(),
            "findings": [f.to_dict() for f in self.findings],
        }

    def summary_line(self) -> str:
        if self.ok:
            return f"{self.profile}: clean ({self.files_scanned} scanned)"
        return (f"{self.profile}: {len(self.findings)} out-of-set runs "
                f"({len(self.invisible)} invisible) in "
                f"{len({f.path for f in self.findings})} of {self.files_scanned}")


def check_text(text: str, profile: Profile | None = None, label: str = "") -> Report:
    """Check one piece of output held in memory — a model response, a draft.

    The single-output entry point: `check_text(response).ok` before you paste
    anything anywhere.
    """
    profile = profile or build_profile("latin")
    if _is_trivially_clean(text, profile):
        return Report([], 1, 0, profile.describe())
    return Report(scan_text(text, profile, label), 1, 0, profile.describe())


def check_file(path, profile: Profile | None = None) -> Report:
    """Check one file. Skipped (binary/unreadable) files report files_skipped=1."""
    profile = profile or build_profile("latin")
    path = Path(path)
    text = read_text(path)
    if text is None:
        return Report([], 0, 1, profile.describe())
    rep = check_text(text, profile, str(path))
    return rep


def check_tree(paths, profile: Profile | None = None, jobs: int = 0,
               max_bytes: int = None, skip_dirs=None) -> Report:
    """Check a whole tree. Same core, parallel and with the pure-ASCII bail-out.

    Built to run unattended over a folder of repos: binaries, symlinks, oversize
    files, and vendor/build directories are skipped, results are sorted, and
    nothing is ever written to the files being checked.
    """
    profile = profile or build_profile("latin")
    max_bytes = DEFAULT_MAX_BYTES if max_bytes is None else max_bytes
    skip = SKIP_DIRS if skip_dirs is None else set(skip_dirs)
    targets = [str(p) for p in iter_files(paths, skip, max_bytes)]

    findings, scanned, skipped = [], 0, 0
    init = (profile.name, sorted(profile.scripts), sorted(profile.allows), False)
    jobs = jobs or min(os.cpu_count() or 1, 8)

    def absorb(result):
        nonlocal scanned, skipped
        _, fs, _ = result
        if fs is None:
            skipped += 1
        else:
            scanned += 1
            findings.extend(fs)

    if jobs > 1 and len(targets) > 8:
        with ProcessPoolExecutor(jobs, initializer=_init_worker_obj,
                                 initargs=(profile, False)) as ex:
            for result in ex.map(_scan_one, targets, chunksize=32):
                absorb(result)
    else:
        _init_worker_obj(profile, False)
        for path_str in targets:
            absorb(_scan_one(path_str))

    findings.sort(key=lambda f: (not f.invisible, f.path, f.offset))
    return Report(findings, scanned, skipped, profile.describe())


def inventory_text(text: str) -> dict:
    """Positive summary: what character groups this text actually uses."""
    inv = {}
    for ch in text:
        cp = ord(ch)
        if cp < 0x80:
            key = "ascii"
        else:
            cat = unicodedata.category(ch)
            key = script_of(ch).lower() if cat[0] in "LM" else f"category:{cat}"
        inv[key] = inv.get(key, 0) + 1
    return inv


# --------------------------------------------------------------------------
# Walking a large tree, unattended
# --------------------------------------------------------------------------

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages",
    "dist", "build", ".next", ".cache", ".tox", "target", "vendor",
    ".claude", ".DS_Store", "worktrees",
}
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".pdf",
    ".zip", ".gz", ".bz2", ".xz", ".tar", ".7z", ".rar", ".jar", ".whl",
    ".mp3", ".mp4", ".mov", ".avi", ".wav", ".flac", ".ogg", ".webm",
    ".ttf", ".otf", ".woff", ".woff2", ".eot", ".so", ".dylib", ".dll",
    ".exe", ".bin", ".o", ".a", ".pyc", ".pyo", ".class", ".wasm",
    ".sqlite", ".db", ".parquet", ".npy", ".npz", ".pkl", ".h5", ".xlsx",
    ".docx", ".pptx", ".psd", ".ai", ".sketch",
}
DEFAULT_MAX_BYTES = 5_000_000


def iter_files(paths, skip_dirs, max_bytes):
    for p in paths:
        root = Path(p)
        if root.is_file():
            yield root
            continue
        if not root.is_dir():
            print(f"charset_guard: no such path: {p}", file=sys.stderr)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in sorted(dirnames)
                           if d not in skip_dirs and not d.startswith(".")]
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if path.suffix.lower() in BINARY_SUFFIXES:
                    continue
                try:
                    if path.is_symlink() or path.stat().st_size > max_bytes:
                        continue
                except OSError:
                    continue
                yield path


def read_text(path: Path):
    """None = binary, undecodable, or unreadable. Never guessed at."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


_WORKER = {}


def _init_worker_obj(profile: Profile, want_inventory: bool):
    """Worker-process setup. Profile is a plain dataclass, so it pickles fine."""
    _WORKER["profile"] = profile
    _WORKER["inventory"] = want_inventory


# Printable ASCII plus tab/newline/CR: the subset every profile permits (CR
# only when --allow crlf, which the fast path re-checks).
_ASCII_CLEAN = frozenset(chr(c) for c in range(0x20, 0x7F)) | {"\t", "\n"}


def _is_trivially_clean(text: str, profile: Profile) -> bool:
    """True when no character can possibly be out of set — skip the scan.

    Most files in a large tree are pure printable ASCII, so this bail-out is
    what makes an unattended whole-folder pass cheap.
    """
    if not text.isascii():
        return False
    allowed = _ASCII_CLEAN | ({"\r"} if "crlf" in profile.allows else set())
    return allowed.issuperset(text)


def _scan_one(path_str):
    path = Path(path_str)
    text = read_text(path)
    if text is None:
        return path_str, None, None
    profile = _WORKER["profile"]
    findings = [] if _is_trivially_clean(text, profile) else scan_text(text, profile, path_str)
    inv = inventory_text(text) if _WORKER["inventory"] else None
    return path_str, findings, inv



# --------------------------------------------------------------------------
# Reporting and CLI
# --------------------------------------------------------------------------

def format_report(report: Report, limit=None) -> str:
    """Human-readable findings. Invisible risks first (they sort first)."""
    lines, shown = [], 0
    for f in report.findings:
        if limit is not None and shown >= limit:
            lines.append(f"... {len(report.findings) - shown} more "
                         f"(use --jsonl for the full list)")
            break
        mark = "!!" if f.invisible else " ~"
        cps = [f"U+{cp:04X}" for cp in f.codepoints]
        head = " ".join(cps) if len(cps) <= 3 else f"{len(cps)}x {cps[0]}.."
        where = f"{f.path}:{f.line}:{f.col}" if f.path else f"{f.line}:{f.col}"
        lines.append(f"{mark} {where}  [{f.risk}] {head}  {f.names[0]}")
        lines.append(f"      {f.note}")
        if f.decoded:
            lines.append(f"      DECODED: {f.decoded!r}")
        lines.append(f"      fix: {f.remedy}")
        lines.append(f"      {f.context}")
        shown += 1
    return "\n".join(lines)


def write_manifest(report: Report, path: str) -> None:
    """One JSON finding per line — the handover format for the cleaner.

    Offsets are codepoint indices into the file's decoded text, so a cleaner
    can act on them directly without re-scanning.
    """
    with open(path, "w", encoding="utf-8") as fh:
        for f in report.findings:
            fh.write(json.dumps(f.to_dict(), ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="charset_guard.py",
        description="Check that every character stays inside a declared permitted set.",
    )
    ap.add_argument("paths", nargs="*", help="files, directories, or - for stdin")
    ap.add_argument("--profile", choices=("ascii", "latin", "multilingual"),
                    default="latin", help="the permitted set (default: latin)")
    ap.add_argument("--scripts", default="",
                    help="comma-separated scripts to declare (multilingual profile)")
    ap.add_argument("--allow", default="",
                    help="comma-separated opt-in groups: typography,math,box,"
                         "emoji,joiners,bidi,nbsp,crlf")
    ap.add_argument("--inventory", action="store_true",
                    help="report which character groups are present; no pass/fail")
    ap.add_argument("--json", action="store_true", help="full JSON report")
    ap.add_argument("--jsonl", metavar="FILE",
                    help="write one JSON finding per line (manifest for the cleaner)")
    ap.add_argument("--jobs", type=int, default=0, help="worker processes (0 = auto)")
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    ap.add_argument("--skip-dir", action="append", default=[],
                    help="extra directory name to skip (repeatable)")
    ap.add_argument("--limit", type=int, default=40,
                    help="findings to print, 0 = all (default 40)")
    ap.add_argument("--quiet", "-q", action="store_true", help="exit code only")
    args = ap.parse_args(argv)

    if not args.paths:
        ap.error("give at least one path, or - for stdin")
        return 2

    try:
        profile = build_profile(
            args.profile,
            [s for s in args.scripts.split(",") if s.strip()],
            [a for a in args.allow.split(",") if a.strip()],
        )
    except ValueError as exc:
        print(f"charset_guard: {exc}", file=sys.stderr)
        return 2

    # --- inventory mode: describe, don't judge ---
    if args.inventory:
        merged, files = {}, 0
        sources = ([("<stdin>", sys.stdin.read())] if args.paths == ["-"] else
                   [(str(p), read_text(p))
                    for p in iter_files(args.paths, SKIP_DIRS | set(args.skip_dir),
                                        args.max_bytes)])
        for _, text in sources:
            if text is None:
                continue
            files += 1
            for k, v in inventory_text(text).items():
                merged[k] = merged.get(k, 0) + v
        if args.json:
            print(json.dumps({"files": files, "inventory": merged}, indent=2))
        else:
            print(f"{files} files — character groups present:")
            for k, v in sorted(merged.items(), key=lambda kv: -kv[1]):
                print(f"  {v:>10,}  {k}")
        return 0

    # --- check mode: one string, one file, or a whole tree; same core ---
    if args.paths == ["-"]:
        rep = check_text(sys.stdin.read(), profile, "<stdin>")
    elif len(args.paths) == 1 and Path(args.paths[0]).is_file():
        rep = check_file(args.paths[0], profile)
    else:
        rep = check_tree(args.paths, profile, jobs=args.jobs,
                         max_bytes=args.max_bytes,
                         skip_dirs=SKIP_DIRS | set(args.skip_dir))

    if args.jsonl:
        try:
            write_manifest(rep, args.jsonl)
        except OSError as exc:
            print(f"charset_guard: cannot write {args.jsonl}: {exc}", file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
    elif not args.quiet:
        body = format_report(rep, None if args.limit == 0 else args.limit)
        if body:
            print(body + "\n")
        print(rep.summary_line())
        for risk, n in sorted(rep.by_risk().items(), key=lambda kv: -kv[1]):
            print(f"  {n:>6}  {risk}")
        locations = rep.by_location()
        if len(locations) > 1:
            print("\nwhere:")
            for loc, v in list(locations.items())[:20]:
                inv = f", {v['invisible']} invisible" if v["invisible"] else ""
                print(f"  {v['total']:>6}  {loc}  ({v['files']} files{inv})")
            if len(locations) > 20:
                print(f"  ... and {len(locations) - 20} more")
        if rep.files_skipped:
            print(f"  ({rep.files_skipped} binary or unreadable files skipped)")
        if args.jsonl:
            print(f"manifest written to {args.jsonl}")

    return 1 if rep.findings else 0


if __name__ == "__main__":
    sys.exit(main())
