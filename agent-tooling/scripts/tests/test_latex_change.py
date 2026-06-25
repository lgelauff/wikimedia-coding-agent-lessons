"""Offline tests for the LaTeX change-review pure logic (classify + diff + bbox)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import latex_classify as lc      # noqa: E402
import latex_diff_html as ld     # noqa: E402
import latex_visual_diff as lv   # noqa: E402

DOC = "\\documentclass{article}\n%PRE%\n\\begin{document}\n%BODY%\n\\end{document}\n"


def _doc(pre="", body="Hello world."):
    return DOC.replace("%PRE%", pre).replace("%BODY%", body)


def test_classify_content_only():
    v = lc.classify(_doc(body="The cat sat."), _doc(body="The dog sat."))
    assert v["content"] and not v["styling"]


def test_classify_styling_only_body_markup():
    # same prose, only wrapping changed -> styling
    v = lc.classify(_doc(body="The cat sat."), _doc(body="The \\textbf{cat} sat."))
    assert v["styling"] and not v["content"]


def test_classify_preamble_change_is_styling():
    v = lc.classify(_doc(pre="\\usepackage{geometry}"), _doc(pre="\\usepackage[margin=1in]{geometry}"))
    assert v["styling"] and not v["content"]


def test_classify_mixed():
    v = lc.classify(_doc(pre="\\usepackage{a}", body="The cat sat."),
                    _doc(pre="\\usepackage{b}", body="The dog ran."))
    assert v["content"] and v["styling"]


def test_classify_no_change():
    v = lc.classify(_doc(), _doc())
    assert not v["content"] and not v["styling"]


def test_inline_marks_replacement():
    s = ld.inline("the old wording", "the new wording")
    assert "[-old-]" in s and "{+new+}" in s and "the " in s


def test_render_short_is_inline_long_is_html(tmp_path):
    kind, payload = ld.render("a b c", "a x c")
    assert kind == "inline"
    big_old = "word " * 1000
    kind, payload = ld.render(big_old, big_old + "extra " * 200, str(tmp_path / "d.html"))
    assert kind == "html" and os.path.exists(payload)
    assert "<del>" in open(payload).read() or "<ins>" in open(payload).read()


def test_html_diff_has_two_columns_and_highlights():
    h = ld.html_diff("the cat sat\nline two", "the dog sat\nline two")
    assert "<del>" in h and "<ins>" in h and "old | new" in h


def test_pad_bbox_clamps():
    assert lv._pad_bbox((10, 10, 20, 20), 100, 100, 5) == (5, 5, 25, 25)
    assert lv._pad_bbox((2, 2, 98, 98), 100, 100, 10) == (0, 0, 100, 100)
    assert lv._pad_bbox(None, 100, 100, 5) is None


def test_detect_compiler_honors_tex_program(tmp_path):
    f = tmp_path / "m.tex"
    f.write_text("% !TEX program = xelatex\n\\documentclass{article}\n\\begin{document}x\\end{document}")
    cmd = lv.detect_compiler(str(f))
    assert "xelatex" in " ".join(cmd) or cmd[0] == "xelatex"
