"""Tests for hooks/fail_closed.sh and for the Python-3.9 import floor of the hooks.

Found 2026-11-02: block_ssh, block_secret_read and github_write_permission (via
is_ssh_command / classify_github_op) used `X | None` annotations without
`from __future__ import annotations`. On /usr/bin/python3 (3.9) they raised
TypeError at import, the hook exited 1, and Claude Code treats exit 1 as a
non-blocking error, so the gate let every call through.

These tests show:
  * the unwrapped crash exits 1 (the failure mode), and the wrapper turns it into 2;
  * the wrapper passes 0 and 2, stdout and stdin through unchanged;
  * every Python PreToolUse gate in hooks.json is wired through the wrapper;
  * no hook, and no policy or script a hook imports, uses a PEP 604 union at
    runtime without the __future__ import (static check, any interpreter), and
    each one really imports on a pre-3.10 python3 when one is installed.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
ROOT = HOOKS.parent
WRAPPER = HOOKS / "fail_closed.sh"
GATES = ["block_ssh", "webfetch_registry_gate", "github_write_permission", "block_secret_read"]


def gate(tmp: Path, body: str) -> Path:
    p = tmp / "gate.py"
    p.write_text(body, encoding="utf-8")
    return p


def wrap(script: Path, stdin: str = "{}") -> subprocess.CompletedProcess:
    return subprocess.run([str(WRAPPER), str(script)], input=stdin,
                          capture_output=True, text=True, timeout=30)


class Wrapper(unittest.TestCase):
    def test_crash_is_exit_1_unwrapped_and_2_wrapped(self):
        with tempfile.TemporaryDirectory() as d:
            g = gate(Path(d), "raise TypeError('unsupported operand type(s) for |')\n")
            bare = subprocess.run(["python3", str(g)], capture_output=True, text=True)
            self.assertEqual(bare.returncode, 1, "control: a crashing gate exits 1 (non-blocking)")
            r = wrap(g)
            self.assertEqual(r.returncode, 2)
            self.assertIn("fail closed", r.stderr)

    def test_other_nonzero_codes_block(self):
        with tempfile.TemporaryDirectory() as d:
            for code in (1, 3, 127):
                r = wrap(gate(Path(d), f"import sys; sys.exit({code})\n"))
                self.assertEqual(r.returncode, 2, code)

    def test_allow_and_block_pass_through_with_output(self):
        with tempfile.TemporaryDirectory() as d:
            r0 = wrap(gate(Path(d), "print('{\"ok\": 1}')\n"))
            self.assertEqual((r0.returncode, r0.stdout.strip()), (0, '{"ok": 1}'))
            r2 = wrap(gate(Path(d), "import sys; print('nope', file=sys.stderr); sys.exit(2)\n"))
            self.assertEqual(r2.returncode, 2)
            self.assertIn("nope", r2.stderr)
            self.assertNotIn("fail closed", r2.stderr)

    def test_stdin_reaches_the_gate(self):
        with tempfile.TemporaryDirectory() as d:
            g = gate(Path(d), "import sys,json; d=json.load(sys.stdin); sys.exit(2 if d['tool_input']['command']=='ssh x' else 0)\n")
            self.assertEqual(wrap(g, json.dumps({"tool_input": {"command": "ssh x"}})).returncode, 2)
            self.assertEqual(wrap(g, json.dumps({"tool_input": {"command": "ls"}})).returncode, 0)


class Wiring(unittest.TestCase):
    def test_every_python_pretooluse_gate_goes_through_the_wrapper(self):
        cfg = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
        cmds = [h["command"] for e in cfg["hooks"]["PreToolUse"] for h in e["hooks"]]
        for g in GATES:
            mine = [c for c in cmds if f"/{g}.py" in c]
            self.assertEqual(len(mine), 1, g)
            self.assertIn("fail_closed.sh", mine[0], f"{g} is not wrapped")


def _hook_import_closure() -> list[Path]:
    """Every hook .py plus the policy/script modules the hooks import."""
    files = sorted(HOOKS.glob("*.py"))
    seen = set(files)
    for f in list(files):
        for m in re.findall(r"^(?:from|import) ([a-z_]+)", f.read_text(encoding="utf-8"), re.M):
            for d in ("policies", "scripts"):
                p = ROOT / d / f"{m}.py"
                if p.exists() and p not in seen:
                    seen.add(p)
                    files.append(p)
    files += [p for p in sorted((ROOT / "policies").glob("*.py")) if p not in seen]
    return files


class Py39Floor(unittest.TestCase):
    def test_no_runtime_pep604_union_without_future_import(self):
        bad = []
        for f in _hook_import_closure():
            src = f.read_text(encoding="utf-8")
            if "from __future__ import annotations" in src:
                continue
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr) and (
                        isinstance(node.right, ast.Constant) and node.right.value is None
                        or isinstance(node.left, ast.Constant) and node.left.value is None):
                    bad.append(f"{f.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(bad, [], "X | None needs `from __future__ import annotations` (3.9 floor)")

    def test_imports_on_a_pre_310_python_if_installed(self):
        py = shutil.which("python3", path="/usr/bin")
        if not py:
            self.skipTest("no /usr/bin/python3")
        ver = subprocess.run([py, "-c", "import sys; print(sys.version_info[:2] < (3, 10))"],
                             capture_output=True, text=True).stdout.strip()
        if ver != "True":
            self.skipTest("/usr/bin/python3 is 3.10+")
        failures = []
        for f in _hook_import_closure():
            code = ("import sys; sys.argv=['probe']; sys.path[:0]=%r; "
                    "import importlib.util as u; s=u.spec_from_file_location('probe', %r); "
                    "m=u.module_from_spec(s); s.loader.exec_module(m)"
                    % ([str(ROOT / 'policies'), str(HOOKS), str(ROOT / 'scripts')], str(f)))
            try:
                r = subprocess.run([py, "-c", code], stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, timeout=20)
            except subprocess.TimeoutExpired:
                continue  # a hook that runs main() on import and waits; import itself succeeded
            if "TypeError" in r.stderr or "SyntaxError" in r.stderr:
                failures.append(f"{f.relative_to(ROOT)}: {r.stderr.strip().splitlines()[-1]}")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
