#!/usr/bin/env python3
"""latex_diff_html.py — content diff for LaTeX, Wikipedia-style.

Short change -> compact inline text (wdiff markers) you can read in chat:
    the [-old-]{+new+} wording
Long change  -> a Wikipedia-style two-column HTML file (old | new) with word-level
    del/ins highlighting, returned as a path to open.

Token-efficient: inline stays tiny; long diffs go to a file instead of the chat.
Stdlib only (difflib).
"""
import difflib
import html
import re
import sys

_TOK = re.compile(r"\s+|\w+|[^\w\s]")


def _words(s: str) -> list[str]:
    return _TOK.findall(s)


def inline(old: str, new: str) -> str:
    """wdiff-style markers across the whole text. Compact; for short changes."""
    sm = difflib.SequenceMatcher(None, _words(old), _words(new), autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        o = "".join(_words(old)[i1:i2]); n = "".join(_words(new)[j1:j2])
        if op == "equal":
            out.append(o)
        elif op == "delete":
            out.append(f"[-{o}-]")
        elif op == "insert":
            out.append(f"{{+{n}+}}")
        else:
            out.append(f"[-{o}-]{{+{n}+}}")
    return "".join(out)


def _word_cells(a: str, b: str) -> tuple[str, str]:
    """(old_html, new_html) for one line pair, with <del>/<ins> word spans."""
    sm = difflib.SequenceMatcher(None, _words(a), _words(b), autojunk=False)
    ow, nw = _words(a), _words(b)
    o, n = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        oseg = html.escape("".join(ow[i1:i2])); nseg = html.escape("".join(nw[j1:j2]))
        if op == "equal":
            o.append(oseg); n.append(nseg)
        elif op == "delete":
            o.append(f"<del>{oseg}</del>")
        elif op == "insert":
            n.append(f"<ins>{nseg}</ins>")
        else:
            o.append(f"<del>{oseg}</del>"); n.append(f"<ins>{nseg}</ins>")
    return "".join(o), "".join(n)


_CSS = """body{font:13px/1.5 -apple-system,Segoe UI,sans-serif;margin:1rem}
table{border-collapse:collapse;width:100%} td{vertical-align:top;padding:2px 8px;
white-space:pre-wrap;font-family:ui-monospace,monospace;width:50%;border-top:1px solid #eaecf0}
td.ln{width:3em;color:#72777d;text-align:right;font-family:inherit;-webkit-user-select:none}
del{background:#fec5c5;text-decoration:none} ins{background:#a3d3a3;text-decoration:none}
tr.ctx td{color:#54595d} .o{background:#fee} .n{background:#efe}"""


def html_diff(old: str, new: str, context: int = 2) -> str:
    """Wikipedia-style two-column HTML diff (old | new), word-level highlights."""
    o_lines, n_lines = old.splitlines(), new.splitlines()
    sm = difflib.SequenceMatcher(None, o_lines, n_lines, autojunk=False)
    rows = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            span = list(range(i1, i2))
            if len(span) > 2 * context:                      # collapse the middle
                keep = span[:context] + [None] + span[-context:]
            else:
                keep = span
            for k in keep:
                if k is None:
                    rows.append('<tr class="ctx"><td class="ln"></td><td colspan=3>⋮</td></tr>')
                    continue
                t = html.escape(o_lines[k])
                rows.append(f'<tr class="ctx"><td class="ln">{k+1}</td><td>{t}</td>'
                            f'<td class="ln">{k+1-i1+j1}</td><td>{t}</td></tr>')
        else:
            o_block, n_block = o_lines[i1:i2], n_lines[j1:j2]
            for d in range(max(len(o_block), len(n_block))):
                a = o_block[d] if d < len(o_block) else ""
                b = n_block[d] if d < len(n_block) else ""
                oc, nc = _word_cells(a, b)
                ln_o = str(i1 + d + 1) if d < len(o_block) else ""
                ln_n = str(j1 + d + 1) if d < len(n_block) else ""
                rows.append(f'<tr><td class="ln">{ln_o}</td><td class="o">{oc}</td>'
                            f'<td class="ln">{ln_n}</td><td class="n">{nc}</td></tr>')
    return (f"<!doctype html><meta charset=utf-8><style>{_CSS}</style>"
            f"<h3>LaTeX content diff <small>(old | new)</small></h3>"
            f"<table>{''.join(rows)}</table>")


def render(old: str, new: str, out_html: str | None = None, max_inline_chars: int = 1500):
    """Return ('inline', text) for short changes, else ('html', path) written to out_html."""
    snippet = inline(old, new)
    if len(snippet) <= max_inline_chars:
        return ("inline", snippet)
    path = out_html or "/tmp/latex-content-diff.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_diff(old, new))
    return ("html", path)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Wikipedia-style LaTeX content diff.")
    ap.add_argument("before"); ap.add_argument("after")
    ap.add_argument("--out", help="HTML output path for long diffs")
    ap.add_argument("--max-inline", type=int, default=1500)
    a = ap.parse_args()
    old = open(a.before, encoding="utf-8").read()
    new = open(a.after, encoding="utf-8").read()
    kind, payload = render(old, new, a.out, a.max_inline)
    if kind == "inline":
        print(payload)
    else:
        print(f"long diff -> {payload}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
