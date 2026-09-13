"""Tests for check_skill_vars.py — the bundled-path guard.

Each test builds a throwaway tree, so none depend on the real repo's state.
The cases mirror the bugs that motivated the guard, and the false positives that
sank an earlier draft of it — a guard that cries wolf gets bypassed, and a
bypassed guard still carries the claim of coverage.
"""
import os
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "check_skill_vars.py")


def run(root, *extra):
    return subprocess.run([sys.executable, SCRIPT, "--root", str(root), *extra],
                          capture_output=True, text=True)


def tree(root, body, name="alpha", subdir="agent-tooling/skills"):
    """A minimal repo: one skill, and one real bundled script to point at."""
    d = root / subdir / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n{body}\n")
    s = root / "agent-tooling" / "scripts"
    s.mkdir(parents=True, exist_ok=True)
    (s / "real.py").write_text("# bundled\n")
    return d


def sh(cmd):
    return f"```bash\n{cmd}\n```"


# --- the bug class -----------------------------------------------------------

def test_correct_form_passes(tmp_path):
    tree(tmp_path, sh('python3 "${CLAUDE_PLUGIN_ROOT}/scripts/real.py"'))
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_skill_dir_rooting_a_bundled_path_is_caught(tmp_path):
    """The live bug: 4 skills, 7 invocations, assigned nowhere."""
    tree(tmp_path, sh('python3 "$SKILL_DIR/../../scripts/real.py"'))
    r = run(tmp_path)
    assert r.returncode == 1
    assert "UNRESOLVED" in r.stdout and "SKILL_DIR" in r.stdout
    assert "CLAUDE_PLUGIN_ROOT" in r.stdout          # names the fix


def test_agent_tooling_root_is_caught(tmp_path):
    """Not substituted into skill bodies; it is an OpenCode-side name."""
    tree(tmp_path, sh('python3 "${AGENT_TOOLING_ROOT}/scripts/real.py"'))
    r = run(tmp_path)
    assert r.returncode == 1 and "UNRESOLVED" in r.stdout


def test_bare_bundled_path_in_a_shell_block_is_caught(tmp_path):
    """Resolves against the consuming repo, which has no agent-tooling/."""
    tree(tmp_path, sh("python3 agent-tooling/scripts/real.py"))
    r = run(tmp_path)
    assert r.returncode == 1 and "BARE PATH" in r.stdout


def test_missing_target_is_caught(tmp_path):
    tree(tmp_path, "see `${CLAUDE_PLUGIN_ROOT}/scripts/gone.py`")
    r = run(tmp_path)
    assert r.returncode == 1 and "MISSING" in r.stdout


# --- usage vs mention: the guard must judge only usage -----------------------

def test_retired_name_mentioned_in_prose_passes(tmp_path):
    """session-close/SKILL.md explains why $SKILL_DIR is wrong. Documentation of
    an anti-pattern must not trip the guard that enforces it."""
    tree(tmp_path, "Note that `$SKILL_DIR` is set by nothing at all.")
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_bare_path_named_in_prose_passes(tmp_path):
    tree(tmp_path, "The test lives in agent-tooling/scripts/tests/t.py in this repo.")
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout


# --- false positives that sank the previous draft ----------------------------

def test_home_is_not_flagged(tmp_path):
    tree(tmp_path, sh('cat "$HOME/.claude/skill-run-cost.jsonl"'))
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_variable_assigned_in_document_is_not_flagged(tmp_path):
    tree(tmp_path, sh('OUT=$(mktemp -d)\nls "$OUT"/*.png'))
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_odata_metadata_is_not_flagged(tmp_path):
    """`/$metadata` is an OData endpoint, not a shell variable."""
    tree(tmp_path, "Query `/$metadata` first to list the fields.")
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_reader_supplied_placeholder_is_not_flagged(tmp_path):
    tree(tmp_path, sh('curl -H "Authorization: Bearer $TOKEN" https://x'))
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout


# --- discovery: the guard must not pass vacuously ----------------------------

def test_finds_skills_nested_deeper(tmp_path):
    """cowork-skills nests one level deeper than agent-tooling/skills."""
    tree(tmp_path, sh('python3 "$SKILL_DIR/../../scripts/real.py"'),
         name="beta", subdir="cowork-skills/some-bundle/skills")
    r = run(tmp_path)
    assert r.returncode == 1 and "beta" in r.stdout


def test_follows_symlinked_skill_trees(tmp_path):
    """Regression: os.walk without followlinks reported '0 checked, clean' for a
    symlinked tree — and symlink distribution is this guard's own rationale."""
    real = tmp_path / "real" / "sym"
    real.mkdir(parents=True)
    (real / "SKILL.md").write_text(
        "---\nname: sym\n---\n" + sh('python3 "$SKILL_DIR/../../scripts/real.py"'))
    skills = tmp_path / "agent-tooling" / "skills"
    skills.mkdir(parents=True)
    (skills / "sym").symlink_to(real, target_is_directory=True)
    r = run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "sym" in r.stdout


def test_no_skills_found_fails_closed(tmp_path):
    """Regression: an empty tree, or --root /etc, reported 'clean' and exit 0."""
    (tmp_path / "unrelated").mkdir()
    r = run(tmp_path)
    assert r.returncode == 1
    assert "refusing to report clean" in r.stdout


def test_scans_reference_files_beside_the_skill(tmp_path):
    d = tree(tmp_path, "nothing here")
    ref = d / "references"
    ref.mkdir()
    (ref / "template.md").write_text(sh('python3 "$SKILL_DIR/../../scripts/real.py"'))
    r = run(tmp_path)
    assert r.returncode == 1 and "template.md" in r.stdout


# --- interface ---------------------------------------------------------------

def test_quiet_suppresses_the_clean_line(tmp_path):
    tree(tmp_path, sh('python3 "${CLAUDE_PLUGIN_ROOT}/scripts/real.py"'))
    r = run(tmp_path, "--quiet")
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_quiet_still_prints_problems(tmp_path):
    tree(tmp_path, sh('python3 "$SKILL_DIR/../../scripts/real.py"'))
    r = run(tmp_path, "--quiet")
    assert r.returncode == 1 and "UNRESOLVED" in r.stdout


def test_missing_root_is_a_usage_error(tmp_path):
    r = run(tmp_path / "nope")
    assert r.returncode == 2
