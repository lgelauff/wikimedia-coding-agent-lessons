"""Tests for scope.classify — the agent-agnostic core of scope.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
from scope import added_by_file, classify  # noqa: E402

CONFIG = {
    "scope": {
        "TEMPLATES_CSS": ["v2/templates/*.html", "v2/static/*.css"],
        "DB": ["v2/migrations/*", "v2/db.py"],
        "PY": ["v2/*.py"],
        "RUNTIME": ["v2/templates/conversation.html", "v2/polis_admin.py"],
    },
    "sensitive_patterns": ["oauth", "csrf", "session["],
}


def test_template_and_runtime_flags():
    r = classify(["v2/templates/conversation.html"], [], CONFIG)
    assert r["flags"]["TEMPLATES_CSS"] is True
    assert r["flags"]["RUNTIME"] is True
    assert r["flags"]["DB"] is False
    assert r["flags"]["DOCS_ONLY"] is False


def test_docs_only():
    r = classify(["README.md", "docs/x.md"], [], CONFIG)
    assert r["flags"]["DOCS_ONLY"] is True
    assert r["flags"]["TEMPLATES_CSS"] is False


def test_docs_only_false_when_mixed():
    assert classify(["a.md", "v2/db.py"], [], CONFIG)["flags"]["DOCS_ONLY"] is False


def test_db_flag():
    assert classify(["v2/migrations/abc.py"], [], CONFIG)["flags"]["DB"] is True


def test_sensitive_from_added_lines_only():
    # pattern present but only as context/removed → not sensitive
    assert classify(["v2/app.py"], ["return render_template('x')"], CONFIG)["flags"]["SENSITIVE"] is False
    # pattern in an added line → sensitive (case-insensitive)
    assert classify(["v2/app.py"], ["if not OAuth_ok: abort(403)"], CONFIG)["flags"]["SENSITIVE"] is True


EXCL = dict(CONFIG, sensitive_exclude=["i18n/*", "*.md", "CHANGELOG*"])


def test_sensitive_word_in_excluded_path_does_not_fire():
    # the wiki-polis #450 false positive: "OAuth" in a translation catalogue and a doc
    added = {"i18n/qqq.json": ['"login-button": "Log in with OAuth"'],
             "ATTRIBUTION.md": ["Sessions are stored server-side."]}
    r = classify(list(added), added, EXCL)
    assert r["flags"]["SENSITIVE"] is False


def test_same_word_in_code_path_does_fire():
    added = {"i18n/qqq.json": ['"login-button": "Log in with OAuth"'],
             "v2/auth.py": ["if not OAuth_ok: abort(403)"]}
    assert classify(list(added), added, EXCL)["flags"]["SENSITIVE"] is True


def test_exclude_has_no_effect_without_paths():
    # a flat list carries no paths, so nothing can be excluded — fail safe, not silent
    assert classify(["i18n/qqq.json"], ["Log in with OAuth"], EXCL)["flags"]["SENSITIVE"] is True


def test_added_by_file_attributes_lines_to_paths():
    diff = "\n".join([
        "diff --git a/i18n/en.json b/i18n/en.json",
        "--- a/i18n/en.json",
        "+++ b/i18n/en.json",
        "@@ -1 +1,2 @@",
        " {",
        '+"x": "Log in"',
        "diff --git a/v2/app.py b/v2/app.py",
        "--- /dev/null",
        "+++ b/v2/app.py",
        "@@ -0,0 +1 @@",
        "+++ counter  # an added line that looks like a header",
        "diff --git a/gone.py b/gone.py",
        "--- a/gone.py",
        "+++ /dev/null",
        "@@ -1 +0,0 @@",
        "-old",
    ])
    assert added_by_file(diff) == {
        "i18n/en.json": ['"x": "Log in"'],
        "v2/app.py": ["++ counter  # an added line that looks like a header"],
    }


def test_empty_diff_is_not_docs_only():
    assert classify([], [], CONFIG)["flags"]["DOCS_ONLY"] is False
