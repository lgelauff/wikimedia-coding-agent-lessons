"""Tests for scope.classify — the agent-agnostic core of scope.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
from scope import classify  # noqa: E402

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


def test_empty_diff_is_not_docs_only():
    assert classify([], [], CONFIG)["flags"]["DOCS_ONLY"] is False
