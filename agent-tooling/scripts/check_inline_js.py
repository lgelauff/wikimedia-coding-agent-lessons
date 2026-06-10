#!/usr/bin/env python3
"""Syntax-check inline <script> JS in HTML/Jinja templates via `node --check`.

Catches the class of bug where a typo makes a whole inline <script> fail to
parse — so it never executes, while the page still renders and server-side
tests stay green (e.g. a smart/curly quote used as a string delimiter taking
out an entire tab's JS). A plain parse gate is cheap and would have caught it.

Per file: extract each inline <script> body (skipping non-JS: empty, src-only,
type=application/json, importmap), neutralize Jinja (`{{…}}` → 0, drop `{%…%}`
and `{#…#}`), and run it through `node --check`. Reports template path + the
script block's start line + node's message. Exit 1 if any block fails to parse.

Requires Node on PATH (preinstalled on CI runners). A caller that wants to skip
gracefully when Node is absent should check node_available() first.

Usage:
  check_inline_js.py templates/*.html
  check_inline_js.py path/to/dir            # recurses for *.html
"""
import os
import re
import subprocess
import sys
import tempfile

_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.DOTALL | re.IGNORECASE)
_NONJS_TYPE = re.compile(r'type\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)
_HAS_SRC = re.compile(r"\bsrc\s*=", re.IGNORECASE)


def _is_js(attrs):
    if _HAS_SRC.search(attrs):
        return False  # external script, nothing inline to parse
    m = _NONJS_TYPE.search(attrs)
    if m:
        t = m.group(1).lower()
        # JS module types are fine; json / importmap / templates are not JS
        return t in ("", "text/javascript", "module", "application/javascript")
    return True  # no type attr = JS


def extract_scripts(html):
    """-> list of (start_line, body) for inline JS <script> blocks. Pure/testable."""
    out = []
    for m in _SCRIPT.finditer(html):
        attrs, body = m.group(1), m.group(2)
        if not body.strip() or not _is_js(attrs):
            continue
        start_line = html.count("\n", 0, m.start(2)) + 1
        out.append((start_line, body))
    return out


def strip_jinja(s):
    """Neutralize Jinja so node sees plausible JS. Pure/testable."""
    s = re.sub(r"\{#.*?#\}", "", s, flags=re.DOTALL)   # comments
    s = re.sub(r"\{%.*?%\}", "", s, flags=re.DOTALL)   # statements
    s = re.sub(r"\{\{.*?\}\}", "0", s, flags=re.DOTALL)  # expressions -> literal
    return s


def node_available():
    try:
        return subprocess.run(["node", "--version"], capture_output=True,
                              timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check_html(path):
    """Return list of failure messages for one template (empty = clean)."""
    failures = []
    html = open(path, encoding="utf-8").read()
    for start_line, body in extract_scripts(html):
        code = strip_jinja(body)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(code)
            tmp = fh.name
        try:
            r = subprocess.run(["node", "--check", tmp],
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                err = r.stderr
                m = re.search(r":(\d+)\b", err)
                true_line = start_line + (int(m.group(1)) - 1 if m else 0)
                syn = next((ln.strip() for ln in err.splitlines()
                            if "Error:" in ln), "parse error")
                failures.append(f"{path}:{true_line}: {syn}")
        finally:
            os.unlink(tmp)
    return failures


def _iter_html(paths):
    for p in paths:
        if os.path.isdir(p):
            for dp, _, fs in os.walk(p):
                for fn in fs:
                    if fn.endswith(".html"):
                        yield os.path.join(dp, fn)
        else:
            yield p


def main(argv):
    if not node_available():
        print("check_inline_js: node not found on PATH — cannot syntax-check JS.",
              file=sys.stderr)
        return 2
    failures = []
    for path in _iter_html(argv):
        failures.extend(check_html(path))
    if failures:
        print("Inline-JS syntax errors:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
