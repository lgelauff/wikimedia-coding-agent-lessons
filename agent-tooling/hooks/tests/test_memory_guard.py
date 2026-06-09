"""Tests for memory_guard decision logic (pure functions)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
from memory_guard import is_gated, is_critical  # noqa: E402

# macOS levels: 1 normal, 2 warning, 4 critical. Default block_level=4, min_pct=8.


def test_gated_workflow():
    assert is_gated("Workflow", {}) is True


def test_not_gated_bash():
    assert is_gated("Bash", {"command": "ls"}) is False


def test_foreground_agent_not_gated():
    assert is_gated("Agent", {"run_in_background": False}) is False


def test_background_agent_gated():
    assert is_gated("Agent", {"run_in_background": True}) is True


def test_warning_level_does_not_block():
    # the everyday state on this machine — must NOT block
    assert is_critical(level=2, free=None, block_level=4, min_pct=8) is False


def test_critical_level_blocks():
    assert is_critical(level=4, free=None, block_level=4, min_pct=8) is True


def test_normal_level_allows():
    assert is_critical(level=1, free=None, block_level=4, min_pct=8) is False


def test_linux_fallback_blocks_below_min():
    assert is_critical(level=None, free=5.0, block_level=4, min_pct=8) is True


def test_linux_fallback_allows_above_min():
    assert is_critical(level=None, free=40.0, block_level=4, min_pct=8) is False


def test_no_signal_fails_open():
    assert is_critical(level=None, free=None, block_level=4, min_pct=8) is False


def test_override_level_5_never_blocks():
    assert is_critical(level=4, free=None, block_level=5, min_pct=8) is False
