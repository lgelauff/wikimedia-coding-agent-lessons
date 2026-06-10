"""Tests for check_inline_js: extract/strip are pure; check_html needs node."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import check_inline_js as c  # noqa: E402


def test_extract_skips_nonjs_and_external():
    html = (
        '<script>var a = 1;</script>\n'
        '<script type="application/json">{"x":1}</script>\n'
        '<script src="/static/app.js"></script>\n'
        '<script>  </script>\n'
        '<script type="module">import x from "y";</script>'
    )
    blocks = c.extract_scripts(html)
    bodies = [b for _, b in blocks]
    assert any("var a = 1" in b for b in bodies)          # plain JS kept
    assert any("import x" in b for b in bodies)            # module kept
    assert not any("application/json" in b for b in bodies)
    assert len(blocks) == 2                                # json, src, empty all skipped


def test_extract_reports_start_line():
    html = "line1\nline2\n<script>\nvar a=1;\n</script>"
    (line, _), = c.extract_scripts(html)
    assert line == 3


def test_strip_jinja():
    s = "var x = {{ value }}; {% if y %}var z=1;{% endif %} {# c #}"
    out = c.strip_jinja(s)
    assert "{{" not in out and "{%" not in out and "{#" not in out
    assert "var x = 0;" in out


def _write(body):
    fd, p = tempfile.mkstemp(suffix=".html")
    os.write(fd, body.encode()); os.close(fd)
    return p


def test_check_html_clean_and_broken():
    if not c.node_available():
        print("SKIP: node not available")
        return
    clean = _write("<script>\nvar k = 'hi'; function f(){ return k; }\n</script>")
    # smart/curly quotes as string delimiters → the exact #174 blocker
    broken = _write("<script>\nvar k = ‘hi’; function f(){ return k; }\n</script>")
    try:
        assert c.check_html(clean) == []
        fails = c.check_html(broken)
        # block starts at line 1, node flags line 2 → true template line 2
        assert len(fails) == 1 and ":2:" in fails[0] and "SyntaxError" in fails[0]
    finally:
        os.unlink(clean); os.unlink(broken)
