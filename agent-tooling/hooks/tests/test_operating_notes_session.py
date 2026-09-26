"""Tests for operating_notes_session: the notes are injected, capped, and never break session start."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir))
import operating_notes_session as h  # noqa: E402

HOOK = os.path.join(HERE, os.pardir, "operating_notes_session.py")


def test_real_notes_fit_the_cap():
    # The shipped file must stay under the cap, or every session silently loses it.
    with open(h.NOTES, encoding="utf-8") as f:
        assert len(f.read().encode("utf-8")) <= h.MAX_BYTES


def test_hook_emits_session_start_context():
    out = subprocess.run([sys.executable, HOOK], input="{}", capture_output=True, text=True)
    assert out.returncode == 0
    payload = json.loads(out.stdout)["hookSpecificOutput"]
    assert payload["hookEventName"] == "SessionStart"
    assert "numbered batch" in payload["additionalContext"]


def test_oversized_notes_are_replaced_by_a_notice():
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write("x" * (h.MAX_BYTES + 1))
    try:
        msg = h.context(f.name)
    finally:
        os.unlink(f.name)
    assert msg.startswith("(operating notes not injected")


def test_missing_file_fails_open():
    assert h.context("/nonexistent/OPERATING-NOTES.md") is None


def test_empty_file_injects_nothing():
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write("  \n")
    try:
        assert h.context(f.name) is None
    finally:
        os.unlink(f.name)
