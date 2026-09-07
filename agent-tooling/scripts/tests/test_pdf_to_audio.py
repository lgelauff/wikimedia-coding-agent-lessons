"""Tests for pdf_to_audio's pure decision functions.

The LLM call and PyMuPDF extraction are not unit-tested; everything that decides
what gets read aloud — and what happens when the model's reply is unusable — is.
That matters because LiftWing has no JSON mode, so a wrapped or malformed reply
is the expected case, not the exceptional one.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
from pdf_to_audio import column_sort, parse_order  # noqa: E402


def blk(x0, y0, text="t"):
    return {"bbox": [x0, y0, x0 + 100, y0 + 20], "text": text}


class TestColumnSort:
    def test_reads_left_column_fully_before_right(self):
        # The failure this exists to prevent: reading straight across two columns.
        blocks = [blk(10, 10, "L1"), blk(400, 10, "R1"),
                  blk(10, 100, "L2"), blk(400, 100, "R2")]
        order = column_sort(blocks, width=600)
        assert [blocks[i]["text"] for i in order] == ["L1", "L2", "R1", "R2"]

    def test_single_column_is_top_to_bottom(self):
        blocks = [blk(10, 300, "c"), blk(10, 10, "a"), blk(10, 150, "b")]
        order = column_sort(blocks, width=600)
        assert [blocks[i]["text"] for i in order] == ["a", "b", "c"]

    def test_every_block_appears_exactly_once(self):
        blocks = [blk(10, 10), blk(400, 10), blk(10, 50), blk(299, 80)]
        assert sorted(column_sort(blocks, width=600)) == [0, 1, 2, 3]

    def test_empty_page(self):
        assert column_sort([], width=600) == []


class TestParseOrder:
    def test_plain_json_array(self):
        assert parse_order('[{"i": 1, "label": "body"}]', 3) == [(1, "body")]

    def test_reply_wrapped_in_prose(self):
        # No JSON mode — the model often explains itself before answering.
        reply = 'Here is the reading order:\n[{"i": 0, "label": "heading"}]\nHope that helps!'
        assert parse_order(reply, 2) == [(0, "heading")]

    def test_reply_in_a_code_fence(self):
        reply = '```json\n[{"i": 2, "label": "body"}]\n```'
        assert parse_order(reply, 3) == [(2, "body")]

    def test_labels_are_normalised(self):
        assert parse_order('[{"i": 0, "label": "  BODY "}]', 1) == [(0, "body")]

    def test_out_of_range_indices_dropped(self):
        # A hallucinated index must not crash the caller or read a wrong block.
        assert parse_order('[{"i": 0, "label": "body"}, {"i": 99, "label": "body"}]', 2) \
            == [(0, "body")]

    def test_missing_label_defaults_to_body(self):
        assert parse_order('[{"i": 0}]', 1) == [(0, "body")]

    def test_malformed_json_returns_none(self):
        assert parse_order('[{"i": 0, "label": ', 2) is None

    def test_no_array_at_all_returns_none(self):
        assert parse_order("I could not determine the reading order.", 2) is None

    def test_all_indices_invalid_returns_none(self):
        # None means "fall back to geometry", which is better than reading nothing.
        assert parse_order('[{"i": 42, "label": "body"}]', 2) is None

    def test_non_dict_rows_are_skipped(self):
        assert parse_order('[3, {"i": 1, "label": "body"}]', 2) == [(1, "body")]
