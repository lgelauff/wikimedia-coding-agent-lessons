"""Offline tests for the candidates -> vault pending.txt bridge."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import candidates_to_pending as b  # noqa: E402


def test_block_has_doi_url_project_status():
    c = {"title": "Polis", "authors": ["A B", "C D"], "year": 2021,
         "doi": "10.1/x", "oa_pdf_url": "http://x/p.pdf"}
    blocks, skipped = b.to_blocks([c], "proj", "2026-06-11", set())
    assert skipped == 0 and len(blocks) == 1
    blk = blocks[0]
    assert "doi:     10.1/x" in blk and "url:     http://x/p.pdf" in blk
    assert "project:     proj" in blk and "status:     pending" in blk
    assert "Polis" in blk and "2021" in blk


def test_skips_candidate_with_no_doi_or_url():
    blocks, skipped = b.to_blocks([{"title": "no ids"}], "p", "d", set())
    assert blocks == [] and skipped == 1


def test_skips_already_present_id():
    existing = {"10.1/x"}
    blocks, skipped = b.to_blocks([{"title": "T", "doi": "10.1/X"}], "p", "d", existing)  # case-insensitive
    assert blocks == [] and skipped == 1


def test_dedups_within_one_run():
    cs = [{"title": "A", "doi": "10/dup"}, {"title": "B", "doi": "10/dup"}]
    blocks, skipped = b.to_blocks(cs, "p", "d", set())
    assert len(blocks) == 1 and skipped == 1


def test_existing_ids_parses_doi_and_url():
    text = "---\nquery: q\ndoi:     10.5/Y\nurl:     http://Z/\nstatus: failed\n"
    ids = b._existing_ids(text)
    assert "10.5/y" in ids and "http://z" in ids
