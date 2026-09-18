#!/usr/bin/env python3
"""Tests for scripts/audit_skills.py.

The audit exists to catch contradictions that only appear once you have several skills
and a model choosing between them, so the tests must prove it CATCHES each class — a
guard that only ever reports clean is worse than none, because it is trusted.

Fixtures are built in a temp dir and removed by the context manager.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "audit_skills.py"


def load_module():
    spec = importlib.util.spec_from_file_location("audit_skills", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build_repo(root: Path, skills: dict[str, str], agent_refs: list[str] | None = None) -> None:
    """Create a minimal repo laid out the way discover_roots() expects."""
    for name, desc in skills.items():
        d = root / "agent-tooling" / "skills" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {desc}\n---\nbody\n", encoding="utf-8")
    if agent_refs:
        ad = root / "agent-tooling" / "adapters" / "opencode" / "agents"
        ad.mkdir(parents=True, exist_ok=True)
        (ad / "x.md").write_text("\n".join(f"uses `{r}`" for r in agent_refs), encoding="utf-8")


def run_audit(root: Path):
    """Run main() against a fixture repo by patching the module globals it reads."""
    m = load_module()
    m.REPO = root
    m.HERE = root / "agent-tooling" / "scripts"
    saved_argv, saved_out = sys.argv, sys.stdout
    sys.argv = ["audit_skills.py"]
    sys.stdout = io.StringIO()          # the audit is chatty; keep test output readable
    try:
        code = m.main()
    finally:
        sys.argv, sys.stdout = saved_argv, saved_out
    return code


class TestAuditSkills(unittest.TestCase):
    def test_clean_set_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_repo(root, {
                "alpha-tool": "Reconcile citation metadata from scholarly indexes for papers",
                "beta-tool": "Render publication-quality figures with accessible colour palettes",
            })
            self.assertEqual(run_audit(root), 0)

    def test_dangling_agent_reference_is_caught(self):
        """The failure this check exists for: a profile names a skill that isn't there."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_repo(root,
                       {"alpha-tool": "Reconcile citation metadata from scholarly indexes for papers"},
                       agent_refs=["does-not-exist-anywhere"])
            self.assertEqual(run_audit(root), 1)

    def test_known_skill_reference_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_repo(root,
                       {"alpha-tool": "Reconcile citation metadata from scholarly indexes for papers"},
                       agent_refs=["alpha-tool"])
            self.assertEqual(run_audit(root), 0)

    def test_trigger_collision_is_caught(self):
        """Two skills competing for one request: the model picks arbitrarily."""
        desc = ("Extract and reconcile citation metadata from scholarly indexes "
                "and publication records reliably and auditably")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_repo(root, {"alpha-tool": desc, "beta-tool": desc})
            self.assertEqual(run_audit(root), 1)

    def test_duplicate_negation_is_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_repo(root, {
                "alpha-tool": "Check this. Use it INSTEAD of git diff for this purpose.",
                "beta-tool": "Also check. Use it INSTEAD of git diff when reviewing.",
            })
            self.assertEqual(run_audit(root), 1)

    def test_empty_tree_exits_two_not_zero(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(run_audit(Path(td)), 2)

    def test_real_repo_is_clean(self):
        """Regression: the shipped set must not accumulate contradictions."""
        real = SCRIPT.resolve().parent.parent.parent
        if not (real / "agent-tooling" / "skills").is_dir():
            self.skipTest("repo layout not present")
        self.assertEqual(run_audit(real), 0)


if __name__ == "__main__":
    unittest.main()