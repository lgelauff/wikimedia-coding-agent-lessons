#!/usr/bin/env python3
"""Give every session read access to every tree of its own repo (Lodewijk's ruling, AGENT-LOG E367).

For each git repo directly under the given roots, add one Claude Code allow rule
    Read(/<main checkout>/**)
to `.claude/settings.local.json` in the main checkout and in every worktree. Worktrees live under
the main checkout (`.claude/worktrees/`), so one rule covers all trees of that repo, and only that repo.
Read only: no Edit/Write rule is added. A deny rule keeps any `.claude/quarantine/` inside the repo
unreadable (material waiting to move to ~/Data_pii). Worktrees outside the given roots (scratchpads,
copies elsewhere) are skipped, and a repo reachable under two roots via a symlink is handled once.

Dry run by default; `--apply` writes, backing up each changed file once to `<file>.bak-<date>`.
Idempotent. New worktrees made later need a re-run (or inherit the main checkout's file, if the
app copies it).

Usage:
  grant_repo_read.py                       # dry run over ~/GitHub and ~/dev
  grant_repo_read.py /home/agent/GitHub    # other roots (e.g. on hague)
  grant_repo_read.py --apply
"""
import datetime, json, subprocess, sys
from pathlib import Path


def trees(repo: Path) -> list[Path]:
    out = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                         capture_output=True, text=True)
    if out.returncode:
        return []
    return [Path(l[len("worktree "):]) for l in out.stdout.splitlines() if l.startswith("worktree ")]


def rule_for(main: Path) -> str:
    return f"Read(/{main.resolve()}/**)"  # absolute paths are written //abs/path in Claude Code rules


def deny_for(main: Path) -> str:
    # quarantined material (e.g. recordings awaiting ~/Data_pii) stays unreadable even within the repo
    return f"Read(/{main.resolve()}/**/.claude/quarantine/**)"


def plan(roots: list[Path]) -> list[tuple[Path, str, str]]:
    changes, seen = [], set()
    roots = [r.resolve() for r in roots if r.is_dir()]
    for root in roots:
        for repo in sorted(p for p in root.iterdir() if (p / ".git").is_dir()):
            main = repo.resolve()
            if main in seen:  # a symlinked repo listed under two roots
                continue
            seen.add(main)
            rule, deny = rule_for(main), deny_for(main)
            for t in trees(main):
                t = t.resolve()
                if not any(t == r or r in t.parents for r in roots):
                    print(f"SKIP {t}: worktree outside the given roots")
                    continue
                f = t / ".claude" / "settings.local.json"
                perms = {}
                if f.is_file():
                    try:
                        perms = json.loads(f.read_text()).get("permissions", {})
                    except json.JSONDecodeError:
                        print(f"SKIP {f}: not valid JSON, fix by hand")
                        continue
                if rule not in perms.get("allow", []) or deny not in perms.get("deny", []):
                    changes.append((f, rule, deny))
    return changes


def apply(changes: list[tuple[Path, str, str]]) -> None:
    stamp = datetime.date.today().isoformat()
    for f, rule, deny in changes:
        data = json.loads(f.read_text()) if f.is_file() else {}
        if f.is_file():
            bak = f.with_name(f"{f.name}.bak-{stamp}")
            if not bak.exists():
                bak.write_text(f.read_text())
        f.parent.mkdir(parents=True, exist_ok=True)
        perms = data.setdefault("permissions", {})
        for key, value in (("allow", rule), ("deny", deny)):
            if value not in perms.setdefault(key, []):
                perms[key].append(value)
        tmp = f.with_name(f.name + ".new")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(f)


def main(argv):
    do_apply = "--apply" in argv
    roots = [Path(a).expanduser() for a in argv if a != "--apply"] or [Path.home() / "GitHub", Path.home() / "dev"]
    changes = plan(roots)
    for f, rule, _deny in changes:
        print(f"{'ADD ' if do_apply else 'WOULD ADD '}{rule} (+ quarantine deny)  ->  {f}")
    if do_apply:
        apply(changes)
    print(f"{len(changes)} file(s) {'changed' if do_apply else 'to change (dry run; --apply to write)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
