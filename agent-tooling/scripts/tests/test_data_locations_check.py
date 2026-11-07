"""Tests for data_locations_check.py: each rule is shown to catch the failure it exists for.

Run: python3 -m unittest agent-tooling.scripts.tests.test_data_locations_check
"""
import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("dlc", HERE.parent / "data_locations_check.py")
dlc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dlc)

TODAY = date(2026, 10, 26)


def row(**kw):
    base = {c: "" for c in dlc.COLUMNS}
    base.update(dataset_id="p/ds", project="p", owner="X", what="w", **{"class": "input"},
                location="hague", path="/x", bytes="100", verified_at="2026-10-20", verified_how="sha256sum -c 3/3 OK",
                status="present", updated_at="2026-10-26 10:00", rebuild="none")
    base.update(kw)
    return base


def run(rows):
    return dlc.check(rows, TODAY, check_fs=False)


class Rules(unittest.TestCase):
    def test_clean_two_copies(self):
        e, w = run([row(), row(location="hf-private")])
        self.assertEqual((e, w), ([], []))

    def test_hf_public_counts_unknown_location_refused(self):
        e, w = run([row(location="drive"), row(location="hf-public")])
        self.assertEqual((e, w), ([], []))
        e, _ = run([row(), row(location="hf-bucket")])
        self.assertTrue(any("unknown location 'hf-bucket'" in x for x in e))

    def test_drive_only_is_error(self):
        e, _ = run([row(location="drive"), row(location="mac", status="removed")])
        self.assertTrue(any("only counting copy is on the drive" in x for x in e))

    def test_drive_plus_hague_ok(self):
        e, _ = run([row(location="drive"), row(location="hague")])
        self.assertEqual(e, [])

    def test_toolforge_off_register_does_not_count(self):
        e, _ = run([row(location="drive"), row(location="toolforge", keep_register="no")])
        self.assertTrue(any("drive" in x for x in e))

    def test_toolforge_on_register_counts(self):
        e, _ = run([row(location="drive"), row(location="toolforge", keep_register="yes")])
        self.assertEqual(e, [])

    def test_toolforge_needs_register_field(self):
        e, _ = run([row(location="toolforge")])
        self.assertTrue(any("keep_register" in x for x in e))

    def test_paper_output_single_copy_is_error(self):
        e, _ = run([row(**{"class": "paper-output"})])
        self.assertTrue(any("needs two counting copies" in x for x in e))

    def test_size_check_is_not_verification(self):
        # P017: du -sb was recorded as verification and made copies count.
        for how in ("du -sb", "ls -la pasted", "docker system df", ""):
            e, _ = run([row(verified_how=how), row(location="hf-private")])
            self.assertEqual(len([x for x in e if "no byte-level check" in x]), 1, how)
        # and such a copy does not count: alone it leaves the dataset with no counting copy
        e, _ = run([row(verified_how="du -sb")])
        self.assertTrue(any("p/ds: no counting copy" in x for x in e))

    def test_byte_checks_accepted(self):
        for how in ("sha256sum -c 4/4 OK", "shasum -a 1 -c 13/13 OK", "md5 vs FILES.tsv 7/7 OK",
                    "rsync -a --checksum dry run clean", "hub lfs.sha256", "diff -rq vs source", "cmp OK"):
            e, w = run([row(verified_how=how), row(location="hf-private")])
            self.assertEqual(e, [], how)

    def test_bucket_deposit_verify_accepted_only_with_its_pass_line(self):
        ok = "t5_bucket_deposit.py verify: BUCKET VERIFIED 13/13 by content 20:19:40Z"
        e, _ = run([row(verified_how=ok), row(location="hf-private")])
        self.assertEqual(e, [], ok)
        for how in ("t5_bucket_deposit.py verify", "t5_bucket_deposit.py upload: BUCKET VERIFIED",
                    "BUCKET VERIFIED", "verified OK", "t5_bucket_deposit.py verify; BUCKET VERIFIED"):
            e, _ = run([row(verified_how=how), row(location="hf-private")])
            self.assertEqual(len([x for x in e if "no byte-level check" in x]), 1, how)

    def test_unverified_copy_does_not_count(self):
        e, w = run([row(verified_at="")])
        self.assertTrue(any("no counting copy" in x for x in e))
        self.assertTrue(any("never verified" in x for x in w))

    def test_rebuildable_cache_needs_no_copy(self):
        e, _ = run([row(**{"class": "cache"}, verified_at="", rebuild="script.py from p/in")])
        self.assertEqual(e, [])

    def test_stale_verification_warns(self):
        _, w = run([row(verified_at="2026-08-01"), row(location="hf-private")])
        self.assertTrue(any("> 30 days" in x for x in w))

    def test_stuck_moving_warns(self):
        _, w = run([row(), row(location="drive", status="moving", updated_at="2026-10-20 09:00")])
        self.assertTrue(any("'moving' since" in x for x in w))

    def test_single_input_without_rebuild_warns(self):
        _, w = run([row()])
        self.assertTrue(any("single copy" in x for x in w))

    def test_malformed_rows_are_errors(self):
        e, _ = run([row(location="nas"), row(dataset_id="p/b", bytes="1.5 GB"),
                    row(dataset_id="p/c", verified_at="26-10-2026")])
        self.assertEqual(len(e), 3)

    def test_retired_dataset_is_quiet(self):
        e, w = run([row(status="removed")])
        self.assertEqual((e, w), ([], []))

    def test_missing_mac_path_warns(self):
        r = row(location="mac", path="/nonexistent/definitely/not/here")
        _, w = dlc.check([r, row(location="hague")], TODAY, check_fs=True)
        self.assertTrue(any("path missing" in x for x in w))


class Cli(unittest.TestCase):
    def write(self, header, rows):
        f = Path(tempfile.mkdtemp()) / "t.tsv"
        lines = ["\t".join(header)] + ["\t".join(r[c] for c in dlc.COLUMNS) for r in rows]
        f.write_text("\n".join(lines) + "\n")
        return str(f)

    def test_exit_codes(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(dlc.main([self.write(dlc.COLUMNS, [row(), row(location="hf-private")]), "--no-fs", "--today", "2026-10-26"]), 0)
            self.assertEqual(dlc.main([self.write(dlc.COLUMNS, [row(location="drive")]), "--no-fs", "--today", "2026-10-26"]), 1)
            self.assertEqual(dlc.main([self.write(dlc.COLUMNS[:-1], []), "--no-fs"]), 2)
            self.assertEqual(dlc.main(["/nonexistent/x.tsv"]), 2)

    def test_empty_record_is_clean(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(dlc.main([self.write(dlc.COLUMNS, []), "--no-fs"]), 0)


if __name__ == "__main__":
    unittest.main()
