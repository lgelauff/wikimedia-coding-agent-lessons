"""Tests for dev_stack_reminder's pure decision (no docker/subprocess)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import dev_stack_reminder as h  # noqa: E402

CFG = {"container_filter": "particiapp-docker", "stop_command": "docker compose down"}


def test_reminds_on_farewell_with_config():
    for prompt in ["bye for now", "goodnight!", "ok ttyl", "see you tomorrow", "signing off"]:
        assert h.should_remind(prompt, CFG) == CFG, prompt


def test_silent_without_farewell():
    assert h.should_remind("fix the bug in app.py", CFG) is None


def test_silent_without_config():
    assert h.should_remind("bye", None) is None
    assert h.should_remind("bye", {}) is None
    assert h.should_remind("bye", {"container_filter": "x"}) is None  # missing stop_command
