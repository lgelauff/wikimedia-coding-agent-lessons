"""Offline tests for score_candidates (LLM call mocked)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import score_candidates as sc  # noqa: E402


def _mock(monkeypatch, reply):
    monkeypatch.setattr(sc, "query_llm", lambda prompt, system=None, **k: reply)


def test_parses_verdict_and_score(monkeypatch):
    _mock(monkeypatch, '{"verdict":"keep","score":91,"reason":"on topic"}')
    out = sc.score_one("focus", {"title": "T"})
    assert out["x_verdict"] == "keep" and out["x_score"] == 91 and out["x_reason"] == "on topic"


def test_extracts_json_from_chatty_reply(monkeypatch):
    _mock(monkeypatch, 'Sure!\n{"verdict":"drop","score":5,"reason":"off"} hope that helps')
    assert sc.score_one("f", {"title": "T"})["x_verdict"] == "drop"


def test_clamps_score_and_defaults_bad_verdict(monkeypatch):
    _mock(monkeypatch, '{"verdict":"perfect","score":900}')
    out = sc.score_one("f", {"title": "T"})
    assert out["x_score"] == 100 and out["x_verdict"] == "maybe"


def test_bad_reply_does_not_lose_candidate(monkeypatch):
    _mock(monkeypatch, "not json at all")
    out = sc.score_one("f", {"title": "Keep me", "doi": "10/x"})
    assert out["title"] == "Keep me" and out["doi"] == "10/x" and out["x_verdict"] == "maybe"


def test_run_sorts_keep_first_then_by_score(monkeypatch):
    replies = iter([
        '{"verdict":"drop","score":10}',
        '{"verdict":"keep","score":70}',
        '{"verdict":"keep","score":95}',
    ])
    monkeypatch.setattr(sc, "query_llm", lambda *a, **k: next(replies))
    out = sc.run([{"title": "a"}, {"title": "b"}, {"title": "c"}], "focus")
    assert [c["x_verdict"] for c in out] == ["keep", "keep", "drop"]
    assert out[0]["x_score"] == 95 and out[1]["x_score"] == 70
