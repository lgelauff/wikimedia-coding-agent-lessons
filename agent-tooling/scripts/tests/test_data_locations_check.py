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

    def test_cday_ship_accepted_only_with_its_pass_line(self):
        ok = "t5_cday_ship.py BUCKET.VERIFIED: 733 files sha256 OK manifest d0e27c831fb0"
        e, _ = run([row(verified_how=ok), row(location="hf-private")])
        self.assertEqual(e, [], ok)
        for how in ("t5_cday_ship.py", "t5_cday_ship.py shipped 733 files",
                    "733 files sha256 OK manifest d0e27c831fb0",
                    "t5_cday_ship.py; 733 files sha256 OK manifest d0e27c831fb0"):
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


class Links(unittest.TestCase):
    """2026-11-08: 9 laptop copies were links into a failing drive and were counted as live."""
    def test_broken_link_is_an_error_and_not_a_copy(self):
        d = Path(tempfile.mkdtemp())
        (d / "gone").symlink_to("/nonexistent/drive/folder")
        e, _ = dlc.check([row(location="mac", path=str(d / "gone")), row(location="hague")], TODAY, check_fs=True)
        self.assertTrue(any("broken link" in x for x in e), e)
        self.assertFalse(any("no counting copy" in x for x in e))
        e, _ = dlc.check([row(location="mac", path=str(d / "gone") + "/")], TODAY, check_fs=True)
        self.assertTrue(any("no counting copy" in x for x in e), e)

    def test_missing_mac_path_does_not_count(self):
        e, w = dlc.check([row(location="mac", path="/nonexistent/x")], TODAY, check_fs=True)
        self.assertTrue(any("path missing" in x for x in w))
        self.assertTrue(any("no counting copy" in x for x in e), e)

    def test_live_link_counts(self):
        d = Path(tempfile.mkdtemp())
        (d / "real").mkdir()
        (d / "ok").symlink_to(d / "real")
        e, _ = dlc.check([row(location="mac", path=str(d / "ok")), row(location="hague")], TODAY, check_fs=True)
        self.assertEqual(e, [])


class Registry(unittest.TestCase):
    def repo(self, artifacts):
        import json
        root = Path(tempfile.mkdtemp())
        (root / ".git").mkdir()
        (root / "data").mkdir()
        (root / "data" / "here").mkdir()
        (root / "data" / "gone").symlink_to("/nonexistent/drive/gone")
        reg = root / "scripts" / "registry.json"
        reg.parent.mkdir()
        reg.write_text(json.dumps({"artifacts": artifacts}))
        return str(reg)

    def test_broken_laptop_link_in_registry_is_an_error(self):
        reg = self.repo({"ds": {"status": "local", "copies": [{"host": "laptop", "path": "data/gone/"}]}})
        e, _ = dlc.registry_check(reg, [row(dataset_id="p/ds")])
        self.assertEqual(len(e), 1, e)
        self.assertIn("broken link", e[0])
        e, _ = dlc.registry_check(reg, [row(dataset_id="p/ds")], check_fs=False)
        self.assertEqual(e, [])

    def test_missing_laptop_copy_warns(self):
        reg = self.repo({"ds": {"status": "local", "copies": [{"host": "laptop", "path": "data/nothere/"}]}})
        _, w = dlc.registry_check(reg, [row(dataset_id="p/ds")])
        self.assertTrue(any("listed but missing" in x for x in w), w)

    def test_artifact_without_row_is_flagged_once(self):
        reg = self.repo({"has-row": {"status": "local"}, "no_row_a": {"status": "local"},
                         "no-row-b": {"status": "deposited"}, "old": {"status": "retired"},
                         "by-path": {"status": "local", "folder": "/Volumes/X/by-path/"},
                         "live": {"status": "local", "copies": [{"host": "laptop", "path": "data/here"}]}})
        rows = [row(dataset_id="p/has_row"), row(dataset_id="p/other", path="/Volumes/X/by-path"),
                row(dataset_id="p/live")]
        e, w = dlc.registry_check(reg, rows)
        self.assertEqual(e, [])
        self.assertEqual(len(w), 1, w)
        self.assertIn("2 artifacts", w[0])
        self.assertIn("no-row-b, no_row_a", w[0])
        for k in ("has-row", "old", "by-path", "live,"):
            self.assertNotIn(k, w[0].split(": ", 1)[1] + ",")

    def test_cli_registry_flag(self):
        reg = self.repo({"ds": {"status": "local", "copies": [{"host": "laptop", "path": "data/gone"}]}})
        f = Path(tempfile.mkdtemp()) / "t.tsv"
        r = row(dataset_id="p/ds")
        f.write_text("\t".join(dlc.COLUMNS) + "\n" + "\t".join(r[c] for c in dlc.COLUMNS) + "\n"
                     + "\t".join(row(dataset_id="p/ds", location="hf-private")[c] for c in dlc.COLUMNS) + "\n")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(dlc.main([str(f), "--today", "2026-10-26", "--no-fs"]), 0)
            self.assertEqual(dlc.main([str(f), "--today", "2026-10-26", "--registry", reg]), 1)
            self.assertEqual(dlc.main([str(f), "--registry", "/nonexistent/registry.json"]), 2)

    def test_copies_marked_removed_or_not_usable_are_not_checked(self):
        reg = self.repo({
            "a": {"status": "local", "copies": [{"host": "laptop", "path": "data/gone", "status": "NOT USABLE"}]},
            "b": {"status": "local", "copies": [{"host": "laptop", "path": "data/nothere", "removed": "2026-11-06"}]},
            "c": {"status": "local", "copies": [{"host": "laptop", "path": "data/nothere2",
                                                 "partially_removed": "2026-11-06"}]}})
        e, w = dlc.registry_check(reg, [row(dataset_id="p/a"), row(dataset_id="p/b"), row(dataset_id="p/c")])
        self.assertEqual((e, w), ([], []))

    def test_worktree_registry_reads_data_from_main_checkout(self):
        import json
        main = Path(tempfile.mkdtemp())
        (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
        (main / "data" / "here").mkdir(parents=True)
        wt = main / ".claude" / "worktrees" / "wt"
        (wt / "scripts").mkdir(parents=True)
        (wt / ".git").write_text("gitdir: %s/.git/worktrees/wt\n" % main)
        reg = wt / "scripts" / "registry.json"
        reg.write_text(json.dumps({"artifacts": {"ds": {"status": "local",
                                                        "copies": [{"host": "laptop", "path": "data/here"}]}}}))
        self.assertEqual(dlc.registry_check(str(reg), [row(dataset_id="p/ds")]), ([], []))
        _, w = dlc.registry_check(str(reg), [row(dataset_id="p/ds")], data_root=str(wt))
        self.assertTrue(any("listed but missing" in x for x in w), w)

    def test_brace_paths_are_expanded(self):
        self.assertEqual(dlc.expand_braces("d/{a, b}/x{1,2}"), ["d/a/x1", "d/a/x2", "d/b/x1", "d/b/x2"])
        reg = self.repo({"ds": {"status": "local", "copies": [{"host": "laptop", "path": "data/{here,gone}"}]}})
        e, _ = dlc.registry_check(reg, [row(dataset_id="p/ds")])
        self.assertEqual(len(e), 1, e)
        self.assertIn("data/gone", e[0])


if __name__ == "__main__":
    unittest.main()
