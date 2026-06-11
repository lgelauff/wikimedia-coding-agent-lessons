"""Tests for capture: pure helpers (no browser launch needed)."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import capture as c  # noqa: E402


def test_parse_viewport():
    assert c._parse_viewport(None) is None
    assert c._parse_viewport("390x844") == (390, 844)
    assert c._parse_viewport("1280X900") == (1280, 900)


def test_resolve_base_precedence():
    # explicit --base-url wins, trailing slash stripped
    assert c._resolve_base("http://x:5000/", None) == "http://x:5000"
    # falls back to config browser.base_url
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"browser": {"base_url": "http://cfg:8000/"}}, f)
        cfg = f.name
    try:
        assert c._resolve_base(None, cfg) == "http://cfg:8000"
    finally:
        os.unlink(cfg)
    # default when nothing supplied (env not set)
    os.environ.pop("CAPTURE_BASE_URL", None)
    assert c._resolve_base(None, None) == c.DEFAULT_BASE


def test_apply_step_rejects_unknown_action():
    try:
        c._apply_step(None, {"action": "teleport"})
    except ValueError as e:
        assert "teleport" in str(e)
    else:
        raise AssertionError("expected ValueError on unknown action")
