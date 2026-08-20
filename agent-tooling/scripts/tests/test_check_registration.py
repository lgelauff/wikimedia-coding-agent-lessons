"""Tests for check_registration.py — the README/tree drift check.

Each test builds a throwaway tree, so none of them depend on the real repo's
current state.
"""
import os
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "check_registration.py")


def run(root):
    return subprocess.run([sys.executable, SCRIPT, "--root", str(root)],
                          capture_output=True, text=True)


def make_skill(root, name, subdir="agent-tooling/skills"):
    d = root / subdir / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n# {name}\n")
    return d


def test_clean_tree_passes(tmp_path):
    make_skill(tmp_path, "alpha")
    (tmp_path / "README.md").write_text("We ship `alpha`.\n")
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "clean" in r.stdout


def test_skill_missing_from_readme_fails(tmp_path):
    make_skill(tmp_path, "alpha")
    make_skill(tmp_path, "orphan")
    (tmp_path / "README.md").write_text("We ship `alpha`.\n")
    r = run(tmp_path)
    assert r.returncode == 1
    assert "UNREGISTERED" in r.stdout and "orphan" in r.stdout
    assert "alpha" not in r.stdout  # the registered one is not reported


def test_phantom_skill_in_readme_fails(tmp_path):
    """The deep-research bug: prose advertises a skill that does not exist."""
    make_skill(tmp_path, "alpha")
    (tmp_path / "README.md").write_text("We ship `alpha`. Skill: `deep-research`.\n")
    r = run(tmp_path)
    assert r.returncode == 1
    assert "PHANTOM" in r.stdout and "deep-research" in r.stdout


def test_todo_may_name_future_skills(tmp_path):
    """A backlog naming something unbuilt is doing its job, not drifting."""
    make_skill(tmp_path, "alpha")
    (tmp_path / "README.md").write_text("We ship `alpha`.\n")
    (tmp_path / "TODO.md").write_text("Promote `morning-integration` to a skill.\n")
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_broken_relative_link_fails(tmp_path):
    make_skill(tmp_path, "alpha")
    (tmp_path / "README.md").write_text(
        "We ship `alpha`. See [gone](docs/gone.md).\n")
    r = run(tmp_path)
    assert r.returncode == 1
    assert "BROKEN LINK" in r.stdout


def test_external_links_are_not_checked(tmp_path):
    make_skill(tmp_path, "alpha")
    (tmp_path / "README.md").write_text(
        "We ship `alpha`. See [docs](https://example.org/x) and [m](mailto:a@b.c).\n")
    assert run(tmp_path).returncode == 0


def test_anchor_is_stripped_before_resolving(tmp_path):
    make_skill(tmp_path, "alpha")
    (tmp_path / "guide.md").write_text("# guide\n")
    (tmp_path / "README.md").write_text(
        "We ship `alpha`. See [g](guide.md#some-heading).\n")
    assert run(tmp_path).returncode == 0


def test_cowork_and_plugin_dirs_are_scanned(tmp_path):
    make_skill(tmp_path, "beta", subdir="cowork-skills/pack/skills")
    (tmp_path / "README.md").write_text("nothing here\n")
    r = run(tmp_path)
    assert r.returncode == 1
    assert "beta" in r.stdout


def test_missing_root_is_usage_error(tmp_path):
    r = run(tmp_path / "nope")
    assert r.returncode == 2


def test_tree_without_skills_is_usage_error(tmp_path):
    (tmp_path / "README.md").write_text("empty\n")
    r = run(tmp_path)
    assert r.returncode == 2
    assert "wrong --root" in r.stderr


def test_playbook_name_on_a_skills_line_is_not_flagged(tmp_path):
    """A `Skills:` line that also mentions a playbook must not flag the playbook."""
    make_skill(tmp_path, "alpha")
    (tmp_path / "README.md").write_text(
        "Skills: `alpha` (does things). Playbook: `research-data-collection`.\n")
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_external_plugin_skill_is_not_flagged(tmp_path):
    """skill-creator ships with another plugin; naming it is correct."""
    make_skill(tmp_path, "alpha")
    (tmp_path / "README.md").write_text(
        "We ship `alpha`. Skills with verifiable output: `skill-creator` evals.\n")
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_trailing_skill_word_shape_is_flagged(tmp_path):
    """The other advertising shape: `name` skill."""
    make_skill(tmp_path, "alpha")
    (tmp_path / "README.md").write_text(
        "We ship `alpha`. Pair it with the `never-written` skill.\n")
    r = run(tmp_path)
    assert r.returncode == 1
    assert "never-written" in r.stdout


def test_phantom_and_clean_paths_both_reach_the_summary(tmp_path):
    """Regression: the phantom loop once shadowed the argparse namespace, so any
    run that found a match crashed on the summary line instead of reporting."""
    make_skill(tmp_path, "alpha")
    (tmp_path / "README.md").write_text(
        "Skills: `alpha`. Pair with the `never-written` skill.\n")
    # a second doc with no phantom, so both branches execute in one run
    (tmp_path / "TODO.md").write_text("nothing\n")
    r = run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "Traceback" not in r.stderr, r.stderr
    assert "never-written" in r.stdout
