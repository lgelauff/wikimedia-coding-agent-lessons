#!/usr/bin/env python3
"""Tests for scripts/lint_skills.py.

Each rule gets a fixture it must CATCH, and a clean fixture must produce nothing: a guard
that only ever reports clean is worse than none, because it is trusted. The description
limit is pinned at its boundary (1,024 passes, 1,025 fails) because that is the defect that
shipped twice (pr-check 1,098, e2e-design 1,072).

Fixtures are built in a temp dir and removed by the context manager.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "lint_skills.py"
GOOD = "Checks widgets for frobnication. Use when someone asks whether a widget is frobnicated."


def load_module():
    spec = importlib.util.spec_from_file_location("lint_skills", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


LINT = load_module()


def skill(root: Path, dirname: str, desc: str = GOOD, body: str = "body\n",
          name: str | None = None, extra: dict[str, str] | None = None) -> Path:
    d = root / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name or dirname}\ndescription: {desc}\n---\n\n{body}", encoding="utf-8")
    for rel, text in (extra or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text, encoding="utf-8")
    return d / "SKILL.md"


def rules(path: Path) -> set[str]:
    return {r for sev, r, _ in LINT.lint(path) if sev != "INFO"}


class CatchesEachRule(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_skill_has_no_findings(self):
        p = skill(self.root, "good-skill", body="See [ref.md](ref.md).\n",
                  extra={"ref.md": "# Ref\n\nflat.\n"})
        self.assertEqual(rules(p), set())

    def test_description_limit_boundary(self):
        base = "Use when x. "
        at = skill(self.root, "at-limit", desc=base + "a" * (1024 - len(base)))
        over = skill(self.root, "over-limit", desc=base + "a" * (1025 - len(base)))
        self.assertNotIn("desc-length", rules(at))
        self.assertIn("desc-length", rules(over))

    def test_folded_description_is_measured_whole(self):
        # `>-` folded scalars span lines; measuring only the first line would miss the defect
        long = "\n".join("  Use when x. " + "word " * 20 for _ in range(12))
        p = skill(self.root, "folded", desc=">-\n" + long)
        self.assertIn("desc-length", rules(p))

    def test_name_format_and_reserved_word(self):
        self.assertIn("name-format", rules(skill(self.root, "Bad_Name", name="Bad_Name")))
        self.assertIn("name-format", rules(skill(self.root, "claude-helper")))
        self.assertIn("name-format", rules(skill(self.root, "dir-a", name="dir-b")))

    def test_xml_person_and_missing_when(self):
        r = rules(skill(self.root, "no-when", desc="I can help you with <b>files</b>."))
        self.assertTrue({"desc-xml", "desc-person", "desc-no-when"} <= r)

    def test_quoted_user_phrasing_is_not_point_of_view(self):
        p = skill(self.root, "quoted",
                  desc='Shows edits. Use whenever someone asks "what did you change".')
        self.assertNotIn("desc-person", rules(p))

    def test_late_trigger_and_markup(self):
        p = skill(self.root, "late", desc="**Concept** " + "x " * 250 + "Use when y.")
        self.assertTrue({"desc-late-when", "desc-markup"} <= rules(p))

    def test_body_size(self):
        p = skill(self.root, "big", body="word\n" * 501)
        self.assertIn("body-lines", rules(p))
        p = skill(self.root, "wordy", body=("w " * 5001) + "\n")
        self.assertIn("body-words", rules(p))

    def test_nested_reference_and_missing_toc(self):
        p = skill(self.root, "deep", body="See [a.md](a.md).\n",
                  extra={"a.md": "# A\n\nSee [b.md](b.md).\n" + "line\n" * 120, "b.md": "# B\n"})
        self.assertTrue({"ref-depth", "ref-no-toc"} <= rules(p))

    def test_backlink_to_skill_md_is_not_nesting(self):
        p = skill(self.root, "back", body="See [references/a.md](references/a.md).\n",
                  extra={"references/a.md": "# A\n\nFrom `../SKILL.md` §4.\n"})
        self.assertNotIn("ref-depth", rules(p))

    def test_toc_heading_satisfies_long_reference(self):
        p = skill(self.root, "toc", body="See [a.md](a.md).\n",
                  extra={"a.md": "# A\n\n## Contents\n- x\n" + "line\n" * 120})
        self.assertNotIn("ref-no-toc", rules(p))

    def test_backslash_path_in_prose_only(self):
        self.assertIn("backslash-path", rules(skill(self.root, "win", body="Run scripts\\x.py\n")))
        fenced = "```\nC:\\tools\\x.py\n```\n"
        self.assertNotIn("backslash-path", rules(skill(self.root, "win-code", body=fenced)))

    def test_bare_script_invocation(self):
        p = skill(self.root, "bare", body="```bash\necho hi | foo_guard.py -\n```\n")
        self.assertIn("bare-script", rules(p))

    def test_prefixed_bundled_and_prose_scripts_pass(self):
        prefixed = '```bash\npython3 "${AGENT_TOOLING_ROOT}/scripts/foo.py"\n```\n'
        self.assertNotIn("bare-script", rules(skill(self.root, "pre", body=prefixed)))
        bundled = "```bash\npython3 scripts/own.py\n```\n"
        p = skill(self.root, "own", body=bundled, extra={"scripts/own.py": "pass\n"})
        self.assertNotIn("bare-script", rules(p))
        prose = "The `scope.py` call does the scoping.\n"
        self.assertNotIn("bare-script", rules(skill(self.root, "prose", body=prose)))

    def test_allow_marker_suppresses_only_named_rule(self):
        body = "<!-- lint: allow bare-script -->\n```bash\nprobe.py\n```\n"
        p = skill(self.root, "allowed", desc="I can do it. Use when x.", body=body)
        r = rules(p)
        self.assertNotIn("bare-script", r)
        self.assertIn("desc-person", r)


class ExitCodes(unittest.TestCase):
    def run_main(self, args):
        saved = sys.stdout
        sys.stdout = io.StringIO()
        try:
            return LINT.main(args)
        finally:
            sys.stdout = saved

    def test_error_exits_1_warning_exits_0_nothing_exits_2(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            skill(root, "warn-only", desc="I can help. Use when x.")
            self.assertEqual(self.run_main([str(root)]), 0)
            skill(root, "Bad_Name", name="Bad_Name")
            self.assertEqual(self.run_main([str(root)]), 1)
        with tempfile.TemporaryDirectory() as empty:
            saved = sys.stderr
            sys.stderr = io.StringIO()
            try:
                self.assertEqual(self.run_main([empty]), 2)
            finally:
                sys.stderr = saved


if __name__ == "__main__":
    unittest.main()
