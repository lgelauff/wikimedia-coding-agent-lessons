"""Tests for record_run.make_record and cost_report aggregate/predict."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
from record_run import make_record           # noqa: E402
from cost_report import pr_type, aggregate, predict  # noqa: E402


def test_make_record_sorts_and_drops_empty_flags():
    r = make_record("pr-check", ["JS", "", "TEMPLATES_CSS"], 123, pr="174", diff_lines=10)
    assert r["flags"] == ["JS", "TEMPLATES_CSS"]
    assert r["skill"] == "pr-check" and r["subagent_tokens"] == 123 and r["pr"] == "174"


def test_make_record_coerces_tokens():
    assert make_record("s", [], None, )["subagent_tokens"] == 0


def test_pr_type():
    assert pr_type(["B", "A"]) == "A+B"
    assert pr_type([]) == "NONE"
    assert pr_type(["", "X"]) == "X"


def test_aggregate_groups_by_skill_and_type():
    rows = [
        {"skill": "pr-check", "flags": ["JS", "PY"], "subagent_tokens": 100, "diff_lines": 50},
        {"skill": "pr-check", "flags": ["PY", "JS"], "subagent_tokens": 300, "diff_lines": 150},
        {"skill": "pr-check", "flags": [], "subagent_tokens": 5, "diff_lines": 3},
    ]
    agg = aggregate(rows)
    assert agg[("pr-check", "JS+PY")]["n"] == 2
    assert sorted(agg[("pr-check", "JS+PY")]["tokens"]) == [100, 300]
    assert agg[("pr-check", "NONE")]["n"] == 1


def test_predict_exact_type_uses_its_mean():
    rows = [
        {"skill": "pr-check", "flags": ["JS"], "subagent_tokens": 200, "diff_lines": 100},
        {"skill": "pr-check", "flags": ["JS"], "subagent_tokens": 400, "diff_lines": 100},
    ]
    est, why = predict(rows, ["JS"], 100)
    assert est == 300 and "exact" in why


def test_predict_falls_back_when_unseen():
    rows = [{"skill": "pr-check", "flags": ["JS"], "subagent_tokens": 200, "diff_lines": 100}]
    est, why = predict(rows, ["DB"], 100)  # unseen type, same flag-count (1)
    assert est is not None and "flag-count" in why
