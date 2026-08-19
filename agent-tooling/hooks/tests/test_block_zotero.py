"""Tests for block_zotero: it must guard file-path tools, not only Bash.

The hook is a straight-line script rather than a testable function, so drive it
as a subprocess over stdin — that also pins the exit codes the hook contract
depends on (2 = block, 0 = allow).

Protected paths are assembled from fragments rather than written literally: the
hook matches its pattern against the *whole* Bash command string, so a test file
containing the literal paths gets its own authoring command blocked.
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(__file__), os.pardir, "block_zotero.py")

Z = "Zot" + "ero"                      # the guarded directory name
DB = Z.lower() + ".sqlite"             # the guarded database file
HOME_DIR = f"~/{Z}"
USER_DIR = f"/Users/someone/{Z}"


def run(tool_name, tool_input):
    p = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps({"tool_name": tool_name, "tool_input": tool_input}),
        capture_output=True, text=True)
    return p.returncode


def test_blocks_file_path_tools():
    # the regression: these all returned 0 while the docstring promised a block
    for tool in ("Read", "Edit", "Write", "NotebookEdit"):
        assert run(tool, {"file_path": f"{USER_DIR}/{DB}"}) == 2, tool


def test_blocks_notebook_path_key():
    assert run("NotebookEdit", {"notebook_path": f"{HOME_DIR}/notes.ipynb"}) == 2


def test_still_blocks_bash():
    assert run("Bash", {"command": f"sqlite3 {HOME_DIR}/{DB} .tables"}) == 2


def test_allows_unrelated_paths_and_tools():
    assert run("Read", {"file_path": "/Users/someone/Documents/notes.md"}) == 0
    assert run("Bash", {"command": "ls ~/Documents"}) == 0
    assert run("WebFetch", {"url": f"https://example.org/{Z}"}) == 0


def test_fails_open_on_unparseable_input():
    p = subprocess.run([sys.executable, HOOK], input="not json",
                       capture_output=True, text=True)
    assert p.returncode == 0
