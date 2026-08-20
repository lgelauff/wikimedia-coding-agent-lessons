"""Tests for skill_trigger_eval.py's pure logic.

The subprocess half needs a working `claude -p` and is exercised by running the
eval set for real. These cover the parts that decide what a run *means* — the
classifier and the partial-JSON parser — because a wrong classifier turns a
healthy library into a false alarm, and a wrong parser turns a fired skill into
a silent MISS.
"""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "ste", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "skill_trigger_eval.py"))
ste = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ste)


class TestClassify:
    def test_expected_skill_fires_is_a_hit(self):
        assert ste.classify("pr-check", "pr-check") == "HIT"

    def test_plugin_qualified_name_still_matches(self):
        """Skills arrive as 'agent-tooling:pr-check'; the plugin prefix is noise."""
        assert ste.classify("pr-check", "agent-tooling:pr-check") == "HIT"

    def test_nothing_fires_when_something_expected_is_a_miss(self):
        assert ste.classify("pr-check", None) == "MISS"

    def test_wrong_skill_wins_is_crowding(self):
        """The failure a per-skill eval cannot see."""
        assert ste.classify("wikimedia-analytics-api",
                            "agent-tooling:source-connectors") == "CROWDED"

    def test_skill_fires_when_none_expected_is_overfire(self):
        assert ste.classify(None, "agent-tooling:charset-hygiene") == "OVERFIRE"

    def test_silence_when_none_expected_is_quiet(self):
        assert ste.classify(None, None) == "QUIET"

    def test_crowding_is_not_reported_as_a_hit_on_prefix_collision(self):
        """'api' appearing in both names must not be read as a match."""
        assert ste.classify("mediawiki-action-api",
                            "wikimedia-data-collection:wikimedia-analytics-api") == "CROWDED"


class TestSkillFromJson:
    def test_complete_json(self):
        assert ste._skill_from_json('{"skill": "pr-check"}') == "pr-check"

    def test_truncated_json_still_yields_the_name(self):
        """Streamed tool input arrives in fragments; the name is usable early."""
        assert ste._skill_from_json('{"skill": "overnight-run", "args": "PR') == "overnight-run"

    def test_no_skill_key_returns_none(self):
        assert ste._skill_from_json('{"command": "ls"}') is None

    def test_garbage_returns_none_rather_than_raising(self):
        assert ste._skill_from_json("not json at all") is None

    def test_empty_returns_none(self):
        assert ste._skill_from_json("") is None

    def test_qualified_name_survives_truncation(self):
        assert ste._skill_from_json('{"skill": "agent-tooling:session-close"') \
            == "agent-tooling:session-close"


class TestBrokenSessionDetection:
    """A dead session yields no tool calls, which is indistinguishable from
    'no skill fired' unless the error text is recognised."""

    def test_revoked_token_is_recognised(self):
        assert ste._looks_broken(
            "Failed to authenticate. API Error: 401 OAuth access token has been revoked.")

    def test_usage_limit_is_recognised(self):
        assert ste._looks_broken("You have exceeded your usage limit for today.")

    def test_ordinary_refusal_is_not_broken(self):
        """The model declining to use a skill is a finding, not a fault."""
        assert not ste._looks_broken(
            "I'll handle that directly — no skill is needed for a one-line typo fix.")

    def test_normal_prose_is_not_broken(self):
        assert not ste._looks_broken(
            "Here's the difference between merge and rebase in terms of history.")

    def test_empty_text_is_not_broken(self):
        assert not ste._looks_broken("")
