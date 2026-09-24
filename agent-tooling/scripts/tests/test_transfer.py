#!/usr/bin/env python3
"""Tests for scripts/transfer.py (session-to-session transfer) and the deliver.py skip.

A guard that only ever reports clean is worse than none, because it is trusted. So every
refusal here has a test that builds the bad case and asserts it is refused *and* that
nothing moved: symlinks, overwrites, hash mismatches, a missing / returned / stale
decision, raw-pii, the disk threshold, the size cap, duplicates, a dest outside the
gitignored data/, and the unbuilt cross-machine route.

Every run gets a temporary HOME with its own ~/agent hub and a throwaway git repo; the real
~/agent is never touched.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
# Overridable only so a mutated copy can be run against this suite (mutation check).
TRANSFER = Path(os.environ.get("TRANSFER_UNDER_TEST", HERE / "transfer.py"))
DELIVER = Path(os.environ.get("DELIVER_UNDER_TEST", HERE / "deliver.py"))
CROSS = "cross-machine route not built: needs Lodewijk's design review"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name).resolve() / "home"
        self.agent = self.home / "agent"
        (self.agent / "outbox").mkdir(parents=True)
        (self.agent / "machine.json").write_text('{"machine": "mac"}\n')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("GIT_") and k != "XDG_CONFIG_HOME"}
        self.env["HOME"] = str(self.home)

        self.repo = self.home / "dev" / "proj"
        self.repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, env=self.env,
                       capture_output=True)
        (self.repo / ".gitignore").write_text("data/\n")
        (self.repo / "data").mkdir()
        self.dest = self.repo / "data" / "incoming"

        self.work = self.home / "work"
        self.work.mkdir()
        self.a = self.work / "a.csv"
        self.b = self.work / "b.txt"
        self.a.write_bytes(b"id,value\n1,2\n")
        self.b.write_bytes(b"hello transfer\n")
        # Generous limits so the clean case passes on any real disk; tests tighten them.
        self.set_limits(disk_max_used_pct=100.0, max_request_bytes=10**12)

    def tearDown(self):
        self._tmp.cleanup()

    # --- helpers ---

    def run_t(self, *args):
        return subprocess.run([sys.executable, str(TRANSFER), *map(str, args)],
                              env=self.env, capture_output=True, text=True)

    def set_limits(self, **kw):
        p = self.agent / "transfer" / "limits.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(kw))

    def request(self, slug="t1", data_class="internal", dest=None, files=None,
                to_machine="mac", harness="claude-code", expect_ok=True):
        r = self.run_t("request", "--slug", slug, "--from-session", "sender",
                       "--to-session", "receiver", "--to-machine", to_machine,
                       "--to-harness", harness, "--data-class", data_class,
                       "--dest", dest or self.dest, "--why", "test transfer",
                       "--source-after", "keep", *(files or [self.a, self.b]))
        if expect_ok:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def tid(self, slug="t1"):
        return f"{datetime.date.today().isoformat()}-{slug}"

    def manifest_path(self, tid):
        return self.agent / "transfer" / "requests" / f"{tid}.json"

    def edit_manifest(self, tid, fn):
        p = self.manifest_path(tid)
        m = json.loads(p.read_text())
        fn(m)
        p.write_text(json.dumps(m))

    def decide(self, tid, decision="approved"):
        d = self.agent / "transfer" / "decisions"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{tid}.json").write_text(json.dumps({
            "id": tid, "decision": decision, "date": "2026-09-24",
            "approved_by": "lodewijk",
            "manifest_sha256": sha(self.manifest_path(tid).read_bytes())}))

    def stage(self, tid):
        folder = self.agent / "outbox" / f"transfer-{tid}"
        folder.mkdir()
        for f in (self.a, self.b):
            shutil.copy2(f, folder / f.name)
        return folder

    def inbox(self, tid):
        return self.agent / "inbox" / "transfers" / tid

    def ready(self, slug="t1"):
        """request + approve + stage; returns (tid, outbox folder)."""
        self.request(slug)
        tid = self.tid(slug)
        self.decide(tid)
        return tid, self.stage(tid)


class TestRequest(Base):
    def test_manifest_records_size_and_sha256(self):
        self.request()
        m = json.loads(self.manifest_path(self.tid()).read_text())
        by = {f["name"]: f for f in m["files"]}
        self.assertEqual(by["a.csv"]["bytes"], len(self.a.read_bytes()))
        self.assertEqual(by["a.csv"]["sha256"], sha(self.a.read_bytes()))
        self.assertEqual(by["b.txt"]["sha256"], sha(self.b.read_bytes()))
        self.assertEqual(m["from"], {"session": "sender", "machine": "mac"})
        self.assertEqual(m["to"]["harness"], "claude-code")
        self.assertEqual((m["data_class"], m["source_after"]), ("internal", "keep"))
        self.assertEqual(m["dest"], str(self.dest))

    def test_symlink_source_refused(self):
        link = self.work / "link.csv"
        link.symlink_to(self.a)
        r = self.request(files=[link], expect_ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("symlink", r.stderr)
        self.assertFalse(self.manifest_path(self.tid()).exists())

    def test_existing_request_not_overwritten(self):
        self.request()
        before = self.manifest_path(self.tid()).read_bytes()
        r = self.request(files=[self.a], expect_ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("refusing to overwrite", r.stderr)
        self.assertEqual(self.manifest_path(self.tid()).read_bytes(), before)

    def test_raw_pii_refused(self):
        r = self.request(data_class="raw-pii", expect_ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("raw-pii", r.stderr)
        self.assertFalse(self.manifest_path(self.tid()).exists())

    def test_file_under_data_pii_refused(self):
        pii = self.home / "Data_pii"
        pii.mkdir()
        (pii / "x.csv").write_text("name\n")
        r = self.request(files=[pii / "x.csv"], expect_ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Data_pii", r.stderr)

    def test_dotfile_and_duplicate_name_refused(self):
        dot = self.work / ".hidden"
        dot.write_text("x")
        self.assertIn("dotfile", self.request(files=[dot], expect_ok=False).stderr)
        other = self.home / "other"
        other.mkdir()
        (other / "a.csv").write_text("different")
        r = self.request(files=[self.a, other / "a.csv"], expect_ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("share this name", r.stderr)


class TestCheck(Base):
    def check(self, tid):
        return self.run_t("check", tid)

    def test_clean_request_passes_and_writes_no_decision(self):
        self.request()
        r = self.check(self.tid())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ALL MECHANICAL CHECKS PASS", r.stdout)
        for c in ("data_class", "receiver", "size", "sources", "dest", "disk", "duplicates"):
            self.assertRegex(r.stdout, rf"PASS\s+{c}\b")
        self.assertIn("used after transfer", r.stdout)  # the disk line carries numbers
        self.assertFalse((self.agent / "transfer" / "decisions").exists())

    def test_raw_pii_refused(self):
        self.request()
        self.edit_manifest(self.tid(), lambda m: m.update(data_class="raw-pii"))
        r = self.check(self.tid())
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"FAIL\s+data_class\s+raw-pii is always refused")
        self.assertIn("RETURN TO SENDER", r.stdout)

    def test_participant_to_hague_needs_claude_code(self):
        self.request("p1", data_class="participant", to_machine="hague", harness="opencode")
        r = self.check(self.tid("p1"))
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"FAIL\s+data_class\s+participant data to hague")
        self.request("p2", data_class="participant", to_machine="hague", harness="claude-code")
        r = self.check(self.tid("p2"))
        self.assertRegex(r.stdout, r"PASS\s+data_class")
        # The hague side cannot be measured from the Mac, so it is not ready either.
        self.assertRegex(r.stdout, r"UNMEASURED\s+disk")
        self.assertIn("NOT READY", r.stdout)
        self.assertEqual(r.returncode, 1)

    def test_disk_threshold_refused(self):
        self.request()
        self.set_limits(disk_max_used_pct=0.001, max_request_bytes=10**12)
        r = self.check(self.tid())
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"FAIL\s+disk\s+[\d.]+% used after transfer")

    def test_size_cap_refused(self):
        self.request()
        self.set_limits(disk_max_used_pct=100.0, max_request_bytes=10)
        r = self.check(self.tid())
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"FAIL\s+size\s+\d+ bytes .* > cap 10")

    def test_duplicate_sha256_at_dest_refused(self):
        self.dest.mkdir()
        (self.dest / "older-copy.csv").write_bytes(self.a.read_bytes())
        self.request()
        r = self.check(self.tid())
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"FAIL\s+duplicates\s+same sha256 already there: "
                                   r"a.csv == older-copy.csv")

    def test_receiver_not_named_refused(self):
        self.request()
        self.edit_manifest(self.tid(), lambda m: m["to"].update(session=""))
        r = self.check(self.tid())
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"FAIL\s+receiver")

    def test_dest_outside_data_refused(self):
        self.request(dest=self.repo / "notdata" / "x")
        r = self.check(self.tid())
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"FAIL\s+dest\s+.*outside .*/data/")

    def test_source_changed_after_request_refused(self):
        self.request()
        self.a.write_bytes(b"changed\n")
        r = self.check(self.tid())
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"FAIL\s+sources\s+a.csv")

    def test_missing_limits_uses_provisional_defaults_and_says_so(self):
        self.request()
        (self.agent / "transfer" / "limits.json").unlink()
        r = self.check(self.tid())
        self.assertIn("PROVISIONAL DEFAULTS (80% disk, 5 GB)", r.stdout)
        self.assertIn("threshold 80.0%", r.stdout)

    def test_unknown_id_is_environment_error(self):
        self.assertEqual(self.check(self.tid("nope")).returncode, 2)
        self.assertEqual(self.check("../../etc/passwd").returncode, 2)


class TestDeliver(Base):
    def deliver(self, *extra):
        return self.run_t("deliver", *extra)

    def assert_nothing_delivered(self, tid, folder):
        self.assertFalse(self.inbox(tid).exists())
        self.assertTrue((folder / "a.csv").exists() or folder.is_symlink())

    def test_approved_transfer_is_delivered(self):
        tid, folder = self.ready()
        r = self.deliver()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.inbox(tid) / "a.csv").read_bytes(), self.a.read_bytes())
        self.assertEqual((self.inbox(tid) / "b.txt").read_bytes(), self.b.read_bytes())
        self.assertFalse(folder.exists())
        self.assertEqual(sorted(p.name for p in self.inbox(tid).iterdir()), ["a.csv", "b.txt"])

    def test_missing_decision_refused(self):
        self.request()
        tid = self.tid()
        folder = self.stage(tid)
        r = self.deliver()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no decision file", r.stderr)
        self.assert_nothing_delivered(tid, folder)

    def test_returned_decision_refused(self):
        tid, folder = self.ready()
        self.decide(tid, decision="returned")  # replaces the approval
        r = self.deliver()
        self.assertEqual(r.returncode, 1)
        self.assertIn("decision is 'returned'", r.stderr)
        self.assert_nothing_delivered(tid, folder)

    def test_manifest_edited_after_approval_refused(self):
        tid, folder = self.ready()
        self.edit_manifest(tid, lambda m: m.update(dest=str(self.repo / "data" / "else")))
        r = self.deliver()
        self.assertEqual(r.returncode, 1)
        self.assertIn("manifest changed since it was approved", r.stderr)
        self.assert_nothing_delivered(tid, folder)

    def test_hash_mismatch_refused_and_nothing_moves(self):
        tid, folder = self.ready()
        (folder / "b.txt").write_bytes(b"hello tampered\n")
        r = self.deliver()
        self.assertEqual(r.returncode, 1)
        self.assertIn("hash mismatch", r.stderr)
        self.assert_nothing_delivered(tid, folder)
        self.assertTrue((folder / "b.txt").exists())  # all or nothing: outbox left intact

    def test_symlinked_file_refused(self):
        tid, folder = self.ready()
        (folder / "a.csv").unlink()
        (folder / "a.csv").symlink_to(self.a)  # same bytes, but a link
        r = self.deliver()
        self.assertEqual(r.returncode, 1)
        self.assertIn("symlink", r.stderr)
        self.assertFalse(self.inbox(tid).exists())

    def test_symlinked_folder_refused(self):
        self.request()
        tid = self.tid()
        self.decide(tid)
        real = self.home / "elsewhere"
        real.mkdir()
        for f in (self.a, self.b):
            shutil.copy2(f, real / f.name)
        (self.agent / "outbox" / f"transfer-{tid}").symlink_to(real)
        r = self.deliver()
        self.assertEqual(r.returncode, 1)
        self.assertIn("symlink", r.stderr)
        self.assertFalse(self.inbox(tid).exists())
        self.assertTrue((real / "a.csv").exists())

    def test_existing_inbox_folder_not_overwritten(self):
        tid, folder = self.ready()
        self.inbox(tid).mkdir(parents=True)
        (self.inbox(tid) / "a.csv").write_text("earlier delivery")
        r = self.deliver()
        self.assertEqual(r.returncode, 1)
        self.assertIn("refusing to overwrite", r.stderr)
        self.assertEqual((self.inbox(tid) / "a.csv").read_text(), "earlier delivery")
        self.assertTrue((folder / "a.csv").exists())

    def test_extra_file_refused(self):
        tid, folder = self.ready()
        (folder / "smuggled.bin").write_bytes(b"x")
        r = self.deliver()
        self.assertEqual(r.returncode, 1)
        self.assertIn("smuggled.bin", r.stderr)
        self.assert_nothing_delivered(tid, folder)

    def test_raw_pii_refused_even_with_approved_decision(self):
        self.request()
        tid = self.tid()
        self.edit_manifest(tid, lambda m: m.update(data_class="raw-pii"))
        self.decide(tid)  # a forged approval
        folder = self.stage(tid)
        r = self.deliver()
        self.assertEqual(r.returncode, 1)
        self.assertIn("raw-pii", r.stderr)
        self.assert_nothing_delivered(tid, folder)

    def test_cross_machine_route_is_a_refusing_stub(self):
        self.request(to_machine="hague")
        tid = self.tid()
        self.decide(tid)
        folder = self.stage(tid)
        r = self.deliver()
        self.assertEqual(r.returncode, 1)
        self.assertIn(CROSS, r.stderr)
        self.assert_nothing_delivered(tid, folder)
        p = self.run_t("push")
        self.assertEqual(p.returncode, 2)
        self.assertIn(CROSS, p.stderr)

    def test_same_machine_route_on_hague_is_not_built(self):
        (self.agent / "machine.json").write_text('{"machine": "hague"}\n')
        self.request(to_machine="hague")
        tid = self.tid()
        self.decide(tid)
        folder = self.stage(tid)
        r = self.deliver()
        self.assertEqual(r.returncode, 1)
        self.assertIn("same-machine route on hague not built", r.stderr)
        self.assert_nothing_delivered(tid, folder)

    def test_takes_no_path_arguments(self):
        tid, folder = self.ready()
        r = self.deliver(str(self.a))
        self.assertEqual(r.returncode, 2)
        self.assert_nothing_delivered(tid, folder)

    def test_plain_outbox_files_left_for_deliver_py(self):
        tid, _folder = self.ready()
        plain = self.agent / "outbox" / "report.pdf"
        plain.write_bytes(b"%PDF")
        self.assertEqual(self.deliver().returncode, 0)
        self.assertTrue(plain.exists())

    def test_dotfiles_are_skipped_not_delivered(self):
        tid, folder = self.ready()
        (folder / ".DS_Store").write_bytes(b"junk")
        r = self.deliver()
        self.assertTrue((self.inbox(tid) / "a.csv").exists())
        self.assertFalse((self.inbox(tid) / ".DS_Store").exists())
        # The folder cannot be removed while the dotfile is in it; that is reported.
        self.assertEqual(r.returncode, 1)
        self.assertIn("not empty", r.stderr)

    def test_empty_outbox_is_nothing_to_do(self):
        r = self.deliver()
        self.assertEqual(r.returncode, 0, r.stderr)


class TestReceive(Base):
    def delivered(self, slug="t1"):
        tid, _ = self.ready(slug)
        r = self.run_t("deliver")
        self.assertEqual(r.returncode, 0, r.stderr)
        return tid

    def test_receive_copies_into_gitignored_data(self):
        tid = self.delivered()
        r = self.run_t("receive", tid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.dest / "a.csv").read_bytes(), self.a.read_bytes())
        self.assertEqual((self.dest / "b.txt").read_bytes(), self.b.read_bytes())
        self.assertTrue((self.agent / "transfer" / "done" / f"{tid}.json").exists())
        again = self.run_t("receive", tid)
        self.assertEqual(again.returncode, 1)
        self.assertIn("already received", again.stderr)

    def test_dest_not_gitignored_refused(self):
        tid = self.delivered()
        (self.repo / ".gitignore").write_text("")
        r = self.run_t("receive", tid)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not gitignored", r.stderr)
        self.assertFalse(self.dest.exists())

    def test_dest_outside_data_refused(self):
        self.request(dest=self.repo / "src")
        tid = self.tid()
        self.decide(tid)
        self.stage(tid)
        self.assertEqual(self.run_t("deliver").returncode, 0)
        r = self.run_t("receive", tid)
        self.assertEqual(r.returncode, 1)
        self.assertIn("outside", r.stderr)
        self.assertFalse((self.repo / "src").exists())

    def test_dest_outside_any_repo_refused(self):
        self.request(dest=self.home / "loose" / "data")
        tid = self.tid()
        self.decide(tid)
        self.stage(tid)
        self.run_t("deliver")
        r = self.run_t("receive", tid)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not inside a git repository", r.stderr)

    def test_symlinked_data_dir_refused(self):
        tid = self.delivered()
        outside = self.home / "outside"
        outside.mkdir()
        (self.repo / "data").rmdir()
        (self.repo / "data").symlink_to(outside)
        r = self.run_t("receive", tid)
        self.assertEqual(r.returncode, 1)
        self.assertIn("symlink", r.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_existing_dest_file_not_overwritten(self):
        tid = self.delivered()
        self.dest.mkdir()
        (self.dest / "b.txt").write_text("keep me")
        r = self.run_t("receive", tid)
        self.assertEqual(r.returncode, 1)
        self.assertIn("refusing to overwrite", r.stderr)
        self.assertEqual((self.dest / "b.txt").read_text(), "keep me")
        self.assertFalse((self.dest / "a.csv").exists())

    def test_hash_mismatch_in_inbox_refused(self):
        tid = self.delivered()
        (self.inbox(tid) / "b.txt").write_bytes(b"tampered in the inbox\n")
        r = self.run_t("receive", tid)
        self.assertEqual(r.returncode, 1)
        self.assertIn("hash mismatch", r.stderr)
        self.assertFalse((self.dest / "a.csv").exists())
        self.assertFalse((self.dest / "b.txt").exists())

    def test_symlink_in_inbox_refused(self):
        tid = self.delivered()
        (self.inbox(tid) / "a.csv").unlink()
        (self.inbox(tid) / "a.csv").symlink_to(self.a)
        r = self.run_t("receive", tid)
        self.assertEqual(r.returncode, 1)
        self.assertIn("symlink", r.stderr)
        self.assertFalse(self.dest.exists())

    def test_decision_withdrawn_before_receive_refused(self):
        tid = self.delivered()
        (self.agent / "transfer" / "decisions" / f"{tid}.json").unlink()
        r = self.run_t("receive", tid)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no decision file", r.stderr)


class TestPlainDeliverSkipsTransfers(Base):
    """deliver.py (outbox -> ~/Downloads) must leave transfer-* folders to transfer.py."""

    def test_transfer_folder_left_alone(self):
        (self.home / "Downloads").mkdir()
        tid, folder = self.ready()
        plain = self.agent / "outbox" / "report.pdf"
        plain.write_bytes(b"%PDF")
        r = subprocess.run([sys.executable, str(DELIVER)], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)  # before the skip: 1, "not a regular file"
        self.assertTrue((self.home / "Downloads" / "report.pdf").exists())
        self.assertTrue((folder / "a.csv").exists())
        self.assertFalse((self.home / "Downloads" / f"transfer-{tid}").exists())

    def test_empty_transfer_folder_not_cleaned_up(self):
        # A sender mkdirs transfer-<id>/ and then copies in. If deliver.py runs in between,
        # its empty-dir cleanup must not remove the folder, or the sender's cp fails.
        (self.home / "Downloads").mkdir()
        staging = self.agent / "outbox" / "transfer-2026-09-24-empty"
        staging.mkdir(parents=True)
        r = subprocess.run([sys.executable, str(DELIVER)], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(staging.is_dir())


if __name__ == "__main__":
    unittest.main()
