#!/usr/bin/env python3
"""latex_classify.py — is a LaTeX change content-focused, styling-focused, or both?

Decides which review view to use (text/HTML content diff vs before/after PNG).
Heuristic, deterministic, no compile:

  - **Preamble** changes (before \\begin{document}) are styling by default —
    packages, geometry, \\setlength, fonts, colors, macro (re)definitions — UNLESS
    the prose there changed too (e.g. \\title/\\author text).
  - **Body** changes: strip LaTeX commands/markup to the underlying PROSE.
      * prose changed  -> CONTENT  (the words differ)
      * prose same, raw differs -> STYLING  (only commands/markup changed:
        \\textbf wrapping, \\vspace, column specs, environment swaps…)

Returns {"content": bool, "styling": bool, "reason": str}. Both can be True (mixed).
"""
import re
import sys

_DOC = re.compile(r"\\begin\{document\}")
_COMMENT = re.compile(r"(?<!\\)%.*$", re.MULTILINE)
# a command + optional *, optional [..] opt-arg, optional {..} (one brace level)
_CMD = re.compile(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?")
_BRACES = re.compile(r"[{}]")
_WS = re.compile(r"\s+")


def _split(text: str) -> tuple[str, str]:
    """(preamble, body) at \\begin{document}; whole thing is body if none."""
    m = _DOC.search(text)
    if not m:
        return "", text
    return text[:m.start()], text[m.end():]


def prose(text: str) -> str:
    """Underlying natural-language text: strip comments, commands, braces, collapse ws."""
    t = _COMMENT.sub("", text)
    t = _CMD.sub(" ", t)
    t = _BRACES.sub(" ", t)
    t = t.replace("&", " ").replace("\\\\", " ")
    return _WS.sub(" ", t).strip().lower()


def classify(old: str, new: str) -> dict:
    if old == new:
        return {"content": False, "styling": False, "reason": "no change"}
    pre_o, body_o = _split(old)
    pre_n, body_n = _split(new)

    content = prose(body_o) != prose(body_n)
    # styling if the raw body changed without a prose change, or the preamble changed
    styling = (body_o != body_n and prose(body_o) == prose(body_n)) or (pre_o != pre_n)
    # a preamble whose PROSE changed (title/author/abstract text) is also content
    if pre_o != pre_n and prose(pre_o) != prose(pre_n):
        content = True

    if content and styling:
        reason = "mixed: prose changed AND markup/preamble changed"
    elif content:
        reason = "content: the underlying text changed"
    elif styling:
        reason = "styling: only commands/markup/preamble changed (prose identical)"
    else:
        reason = "whitespace-only / no semantic change"
    return {"content": content, "styling": styling, "reason": reason}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Classify a LaTeX change as content/styling.")
    ap.add_argument("before")
    ap.add_argument("after")
    a = ap.parse_args()
    old = open(a.before, encoding="utf-8").read()
    new = open(a.after, encoding="utf-8").read()
    v = classify(old, new)
    print(f"content={v['content']} styling={v['styling']} — {v['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
