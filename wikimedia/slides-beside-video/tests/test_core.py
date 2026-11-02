"""Small offline tests: no network, no video. Run: python -m unittest discover -s tests"""
import csv
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "qc"))
sys.path.insert(0, os.path.join(ROOT, "evidence"))

from slides_beside_video import wmvid as V          # noqa: E402
from slides_beside_video import run as R            # noqa: E402
import qc                                           # noqa: E402
import export_evidence as E                          # noqa: E402
import rebuild_timeline as RT                        # noqa: E402


class TextMatching(unittest.TestCase):
    def test_parse_srt(self):
        srt = "1\n00:00:01,000 --> 00:00:02,500\nHello  world\n\n2\n00:01:00,000 --> 00:01:03,000\nSecond cue\n"
        self.assertEqual(V.parse_srt(srt), [[1.0, 2.5, "Hello world"], [60.0, 63.0, "Second cue"]])

    def test_tokens_drop_function_words(self):
        self.assertEqual(V.ctokens(V.tokens("Anatomy of editing a page")), ["anatomy", "editing", "page"])

    def test_page_phrases_are_distinctive(self):
        pages = ["Structured data for museums and archives", "Volunteer meetups every month in Amsterdam"]
        ph = V.page_phrases(pages)
        self.assertTrue(ph[0] and ph[1])
        self.assertFalse(set(ph[0]) & set(ph[1]))
        screen = V.tokens("the slide reads volunteer meetups every month")
        self.assertTrue(V.contiguous_hits(ph[1], screen))
        self.assertFalse(V.contiguous_hits(ph[0], screen))


class Overrides(unittest.TestCase):
    def test_pair_override_matches_spaces_and_underscores(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "o.csv")
            with open(p, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["commons_file", "decision", "reason", "who", "date"])
                w.writerow(["My_talk.webm", "confirm_pair", "r", "me", "2026-01-01"])
            self.assertIsNotNone(R.pair_override(p, "File:My talk.webm"))
            self.assertIsNone(R.pair_override(p, "Other.webm"))
            self.assertIsNone(R.pair_override(None, "My_talk.webm"))


class QCPoints(unittest.TestCase):
    def test_strata_and_density(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "work", "t1"))
            tl = {"duration_s": 120.0, "decks": ["deck.pdf"], "segments": [
                {"start": 0, "end": 60, "deck": 0, "page": 1, "label": "confirmed"},
                {"start": 60, "end": 90, "deck": 0, "page": 2, "label": "unverified"},
                {"start": 90, "end": 120, "deck": 0, "page": 0, "label": "live_browser"}]}
            with open(os.path.join(d, "work", "t1", "timeline.json"), "w") as f:
                json.dump(tl, f)
            qc.configure({"work_dir": os.path.join(d, "work"), "user_agent": "test",
                          "qc": {"out_dir": os.path.join(d, "qc")}})
            pts, _ = qc.build_points("t1", 10)
            strata = {p["stratum"] for p in pts}
            self.assertEqual(strata, {"rest", "page_change", "low_confidence", "no_slide"})
            times = [p["time_s"] for p in pts if p["seg"] == 0]
            self.assertTrue(all(b - a >= 2 for a, b in zip(times, times[1:])))
            self.assertIn(59.0, times)                     # end point next to the page change
            self.assertTrue(all(p["page"] is None for p in pts if p["stratum"] == "no_slide"))


class Redaction(unittest.TestCase):
    def test_names_and_private_screen(self):
        red, red_token, in_win, count = E.redactor({"terms": [{"term": "Anna", "variants": ["Ana"]}],
                                                    "ocr_blank": [{"from": "01:00", "to": "01:30"}]})
        self.assertEqual(red("Maybe Anna? Or ana."), "Maybe [name]? Or [name].")
        self.assertEqual(red("Annabel stays"), "Annabel stays")
        self.assertTrue(red_token("anna") and not red_token("banana"))
        self.assertTrue(in_win(75) and not in_win(200))


class Rebuild(unittest.TestCase):
    def test_per_second(self):
        segs = [{"start": 0, "end": 3, "page": 2}, {"start": 3, "end": 5, "page": None}]
        self.assertEqual(RT.per_second(segs, 5), [2, 2, 2, None, None])


class KillSafety(unittest.TestCase):
    """Atomic outputs, checksummed done markers, locks and the budget ledger."""

    def test_jdump_skips_identical_rewrite(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            V.jdump({"a": 1}, p)
            t = os.stat(p).st_mtime_ns
            os.utime(p, ns=(t - 10 ** 9, t - 10 ** 9))
            V.jdump({"a": 1}, p)
            self.assertEqual(os.stat(p).st_mtime_ns, t - 10 ** 9)
            V.jdump({"a": 2}, p)
            self.assertEqual(V.jload(p), {"a": 2})
            self.assertFalse(os.path.exists(p + ".tmp"))

    def test_marked_chunk_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "chunk.json")
            V.dump_marked({"cues": [[0, 1, "hi"]]}, p)
            self.assertEqual(V.load_marked(p), {"cues": [[0, 1, "hi"]]})
            j = V.jload(p)
            j["data"]["cues"][0][2] = "changed"
            json.dump(j, open(p, "w"))
            self.assertIsNone(V.load_marked(p))
            open(p, "w").write('{"sha256": "x", "da')          # truncated
            self.assertIsNone(V.load_marked(p))

    def test_imwrite_atomic_leaves_no_part_file(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.jpg")
            V.imwrite_atomic(p, np.zeros((8, 8, 3), np.uint8))
            self.assertEqual(os.listdir(d), ["f.jpg"])

    def test_lock_takes_over_dead_pid_and_refuses_live_one(self):
        import subprocess
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, ".lock")
            open(p, "w").write(str(dead.pid))
            self.assertTrue(V.take_lock(p))
            self.assertEqual(open(p).read(), str(os.getpid()))
            open(p, "w").write(str(os.getppid()))                # a live process
            self.assertFalse(V.take_lock(p))
            self.assertFalse(qc.take_lock(p))

    def test_budget_refuses_without_charging(self):
        old = V.BUDGET_FILE, V.BUDGET_CAPS
        with tempfile.TemporaryDirectory() as d:
            V.BUDGET_FILE, V.BUDGET_CAPS = os.path.join(d, "budget.json"), {"api_calls": 2}
            try:
                V.charge("api_calls")
                V.charge("api_calls")
                with self.assertRaises(V.BudgetExceeded):
                    V.charge("api_calls")
                self.assertEqual(V.budget()["api_calls"], 2)
                V.charge("download_bytes", 100)                  # no cap: counted only
                V.charge("download_bytes", -40)                  # refund of a failed attempt
                self.assertEqual(V.budget()["download_bytes"], 60)
            finally:
                V.BUDGET_FILE, V.BUDGET_CAPS = old

    def test_stage_markers_catch_changed_and_missing_outputs(self):
        with tempfile.TemporaryDirectory() as w:
            V.jdump({"frames": []}, os.path.join(w, "ocr.json"))
            V.jdump({"cues": []}, os.path.join(w, "transcript.json"))
            st = {"stages": {"ocr": {"sha256": R.stage_hashes(w, "k", "ocr")},
                             "transcript": {"sha256": R.stage_hashes(w, "k", "transcript")}}}
            self.assertEqual(R.verify_markers(st, w), [])
            open(os.path.join(w, "ocr.json"), "a").write(" ")
            os.remove(os.path.join(w, "transcript.json"))
            self.assertEqual(sorted(R.verify_markers(st, w)), ["ocr: ocr.json changed",
                                                               "transcript: transcript.json missing"])

    def test_qc_truncated_verdict_is_not_done(self):
        with tempfile.TemporaryDirectory() as d:
            b, v = os.path.join(d, "b001.json"), os.path.join(d, "v.json")
            json.dump({"items": [{"id": "a"}, {"id": "b"}]}, open(b, "w"))
            json.dump([{"id": "a", "answer": "yes"}, {"id": "b", "answer": "no"}], open(v, "w"))
            self.assertTrue(qc.verdict_ok(b, v))
            open(v, "w").write('[{"id": "a", "answer": "yes"}, {"id"')
            self.assertFalse(qc.verdict_ok(b, v))
            json.dump([{"id": "a", "answer": "yes"}], open(v, "w"))
            self.assertFalse(qc.verdict_ok(b, v))

    def test_qc_done_marker(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(qc.check_done(d), [])                 # older folders: no marker, accepted
            open(os.path.join(d, "points.csv"), "w").write("time_s\n1\n")
            json.dump({"sha256": {"points.csv": qc.sha256_of(os.path.join(d, "points.csv"))}},
                      open(os.path.join(d, "done.json"), "w"))
            self.assertEqual(qc.check_done(d), [])
            open(os.path.join(d, "points.csv"), "a").write("2\n")
            self.assertEqual(qc.check_done(d), ["points.csv"])


if __name__ == "__main__":
    unittest.main()
