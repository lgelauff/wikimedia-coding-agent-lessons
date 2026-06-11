"""Tests for the content_too_short policy (pure decision logic)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import content_too_short as p  # noqa: E402


def test_flags_short_content():
    assert p.too_short("nope", min_chars=300)
    assert p.too_short("", min_chars=300)


def test_allows_long_content():
    assert p.too_short("x" * 300, min_chars=300) is None
    assert p.too_short("x" * 5000, min_chars=300) is None


def test_threshold_is_configurable():
    body = "x" * 100
    assert p.too_short(body, min_chars=50) is None   # under a loose bar
    assert p.too_short(body, min_chars=500)          # over a strict bar


def test_reason_reports_counts():
    reason = p.too_short("abc", min_chars=300)
    assert "3 chars" in reason and "300" in reason
