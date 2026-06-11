"""Offline tests for source_discovery pure logic (no network)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import source_discovery as sd  # noqa: E402


def test_reconstruct_abstract_orders_by_position():
    inv = {"opinion": [2], "Scaling": [0], "spaces": [3], "deliberation": [1]}
    assert sd._reconstruct_abstract(inv) == "Scaling deliberation opinion spaces"


def test_reconstruct_abstract_empty():
    assert sd._reconstruct_abstract(None) == ""
    assert sd._reconstruct_abstract({}) == ""


def test_dedup_key_prefers_doi_then_oa_then_title():
    assert sd._dedup_key({"doi": "10.1/AbC"}) == "doi:10.1/abc"
    assert sd._dedup_key({"doi": None, "openalex_id": "W42"}) == "oa:W42"
    assert sd._dedup_key({"title": "  Polis Paper "}) == "title:polis paper"


def test_dedup_collapses_same_doi_across_queries(monkeypatch):
    a = {"doi": "10.1/x", "title": "A", "query": "q1"}
    b = {"doi": "10.1/X", "title": "A dup", "query": "q2"}  # same DOI, diff case
    monkeypatch.setattr(sd, "search_openalex", lambda q, *a_, **k: [a] if q == "q1" else [b])
    out = sd.run(["q1", "q2"], use_crossref=False)
    assert len(out) == 1 and out[0]["query"] == "q1"


def test_run_respects_max_total(monkeypatch):
    monkeypatch.setattr(sd, "search_openalex",
                        lambda q, *a_, **k: [{"doi": f"10/{q}{i}", "title": str(i)} for i in range(10)])
    assert len(sd.run(["q"], max_total=3)) == 3


def test_run_survives_a_failing_backend(monkeypatch):
    def boom(*a_, **k): raise RuntimeError("api down")
    monkeypatch.setattr(sd, "search_openalex", boom)
    assert sd.run(["q"]) == []   # logged + skipped, no crash
