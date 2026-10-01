#!/usr/bin/env python3
"""handoff.py — move a finished branch from a server agent to Lodewijk's Mac to GitHub, safely.

The branch-handoff playbook (agent-tooling/playbooks/branch-handoff.md) made into one command per side.
Python 3.9+, standard library and git only.

  prepare   (server, run by the agent)  — writes a manifest that only NAMES things:
      handoff.py prepare --repo OWNER/NAME --path CLONE --branch BRANCH --base REF
                         [--test-cmd CMD --test-result LINE] [--pr-title T] [--pr-body-file F]
                         [--pr-base BRANCH] [--out DIR]
      -> DIR/<owner>__<name>__<branch>.json   (DIR default /srv/exchange/from-agent/handoffs)

  fetch     (Mac, run by Lodewijk in his own Terminal) — checks, fetches, asks, pushes:
      handoff.py fetch MANIFEST [--registry FILE]
      MANIFEST is a local file or ALIAS:/abs/path.json (read with `ssh ALIAS cat`; ALIAS must be a
      server alias in the registry). Everything that decides WHERE things go (the Mac clone, the
      expected origin, the server clone to fetch from) comes from the registry, never the manifest.
      Steps, each stopping with a clear message on failure:
        1. origin of the registered Mac clone must equal the registered origin URL;
        2. a local branch of that name must not exist with different commits;
        3. git fetch --no-tags from the registered server clone; "no common commits" aborts;
        4. git log base..branch must equal the manifest's commit list exactly (sha and subject);
        5. shows the diffstat, the test command and result, the PR title;
        6. asks "push? [y/N]" (needs a terminal), then git push origin BRANCH;
        7. prints the prefilled PR compare link (never opens or creates a PR itself).

  link      (anywhere) — a prefilled GitHub link for a DRAFT someone will post by hand:
      handoff.py link issue   --repo OWNER/NAME --title T --body-file F
      handoff.py link compare --repo OWNER/NAME --base B --branch BR [--title T --body-file F]

Registry (default ~/agent/handoff-registry.json), one entry per repo:
  {"hatnote/montage": {"mac_path": "/Users/.../montage",
                       "origin": "https://github.com/hatnote/montage.git",
                       "server": "hague:/home/agent/GitHub/montage"}}

`fetch` refuses to run inside an agent session (Claude Code / OpenCode environment) or without a
terminal: the push is Lodewijk's act. Exit codes: 0 ok / pushed / declined, 1 a check failed, 2 usage.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
BRANCH = re.compile(r"(?!.*\.\.)(?!.*//)(?!/)[A-Za-z0-9][A-Za-z0-9._/-]{0,199}(?<![./])")
SHA = re.compile(r"[0-9a-f]{40}")
ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
DEFAULT_OUT = "/srv/exchange/from-agent/handoffs"
DEFAULT_REGISTRY = os.path.expanduser("~/agent/handoff-registry.json")
AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "OPENCODE", "OPENCODE_SESSION")


class Stop(Exception):
    """A check failed; the message says which and what to do."""


def git(path, *args, check=True):
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise Stop(f"git {' '.join(args[:2])} failed in {path}: {r.stderr.strip()[:300]}")
    return r


def commits(path, base, head):
    out = git(path, "log", "--reverse", "--format=%H%x09%s", f"{base}..{head}").stdout
    return [line.split("\t", 1) for line in out.splitlines() if line]


def manifest_name(repo, branch):
    return repo.replace("/", "__") + "__" + branch.replace("/", "__") + ".json"


# ---- prepare (server) ----------------------------------------------------------------------------
def prepare(a):
    if not SLUG.fullmatch(a.repo):
        raise Stop(f"--repo must be OWNER/NAME, got {a.repo!r}")
    if not BRANCH.fullmatch(a.branch):
        raise Stop(f"--branch is not a plain branch name: {a.branch!r}")
    path = Path(a.path).resolve()
    head = git(path, "rev-parse", "--verify", f"refs/heads/{a.branch}^{{commit}}").stdout.strip()
    base = git(path, "rev-parse", "--verify", f"{a.base}^{{commit}}").stdout.strip()
    if git(path, "merge-base", "--is-ancestor", base, head, check=False).returncode != 0:
        raise Stop(f"base {a.base} is not an ancestor of {a.branch}")
    lst = commits(path, base, head)
    if not lst:
        raise Stop(f"{a.branch} has no commits after {a.base}")
    m = {
        "version": 1, "repo": a.repo, "branch": a.branch, "base_sha": base, "head_sha": head,
        "commits": [{"sha": s, "subject": subj} for s, subj in lst],
        "diffstat": git(path, "diff", "--shortstat", base, head).stdout.strip(),
        "test_cmd": a.test_cmd or "", "test_result": a.test_result or "not run",
        "pr_base": a.pr_base or "", "pr_title": a.pr_title or "",
        "pr_body": Path(a.pr_body_file).read_text(encoding="utf-8") if a.pr_body_file else "",
    }
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / manifest_name(a.repo, a.branch)
    f.write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"manifest: {f}\n{len(lst)} commits, head {head[:10]}, {m['diffstat']}")
    return 0


# ---- fetch (Mac) ---------------------------------------------------------------------------------
def load_registry(path):
    try:
        reg = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Stop(f"no registry at {path}; create it (see this script's docstring)")
    for repo, e in reg.items():
        if not SLUG.fullmatch(repo) or not {"mac_path", "origin", "server"} <= set(e):
            raise Stop(f"registry entry {repo!r} needs mac_path, origin and server")
    return reg


def read_manifest(spec, reg):
    if re.fullmatch(r"[^/:]+:/.+", spec):          # ALIAS:/abs/path.json, read over ssh
        alias, rpath = spec.split(":", 1)
        aliases = {e["server"].split(":", 1)[0] for e in reg.values()}
        if not ALIAS.fullmatch(alias) or alias not in aliases:
            raise Stop(f"{alias!r} is not a server alias in the registry")
        if not re.fullmatch(r"/[A-Za-z0-9._/-]+\.json", rpath) or ".." in rpath.split("/"):
            raise Stop(f"manifest path not allowed: {rpath!r}")
        r = subprocess.run(["ssh", alias, "cat", "--", rpath], capture_output=True, text=True)
        if r.returncode != 0:
            raise Stop(f"could not read {spec}: {r.stderr.strip()[:200]}")
        text = r.stdout
    else:
        text = Path(spec).read_text(encoding="utf-8")
    try:
        m = json.loads(text)
    except ValueError as e:
        raise Stop(f"manifest is not JSON: {e}")
    if m.get("version") != 1:
        raise Stop("manifest version must be 1")
    if not SLUG.fullmatch(str(m.get("repo", ""))) or not BRANCH.fullmatch(str(m.get("branch", ""))):
        raise Stop("manifest repo or branch is malformed")
    for k in ("base_sha", "head_sha"):
        if not SHA.fullmatch(str(m.get(k, ""))):
            raise Stop(f"manifest {k} is not a full sha")
    cl = m.get("commits")
    if not isinstance(cl, list) or not cl or not all(isinstance(c, dict) and SHA.fullmatch(str(c.get("sha", ""))) for c in cl):
        raise Stop("manifest commit list is missing or malformed")
    if cl[-1]["sha"] != m["head_sha"]:
        raise Stop("manifest head_sha is not the last commit in its list")
    if m.get("pr_base") and not BRANCH.fullmatch(m["pr_base"]):
        raise Stop("manifest pr_base is malformed")
    return m


def norm_origin(u):
    u = u.strip()
    u = re.sub(r"^git@github\.com:", "https://github.com/", u)
    u = re.sub(r"^ssh://git@github\.com/", "https://github.com/", u)
    return re.sub(r"(\.git)?/?$", "", u).lower()


def compare_url(repo, base, branch, title="", body=""):
    q = {"expand": "1"}
    if title:
        q["title"] = title
    if body:
        q["body"] = body
    return (f"https://github.com/{repo}/compare/{urllib.parse.quote(base, safe='')}..."
            f"{urllib.parse.quote(branch, safe='/')}?" + urllib.parse.urlencode(q))


def fetch(a, ask=input, out=print):
    reg = load_registry(a.registry)
    m = read_manifest(a.manifest, reg)
    repo, br = m["repo"], m["branch"]
    if repo not in reg:
        raise Stop(f"{repo} is not in the registry {a.registry}; add it first")
    e = reg[repo]
    mac = Path(e["mac_path"])
    if not (mac / ".git").exists():
        raise Stop(f"registered Mac clone {mac} is not a git checkout")
    got = git(mac, "remote", "get-url", "origin").stdout
    if norm_origin(got) != norm_origin(e["origin"]):
        raise Stop(f"origin of {mac} is {got.strip()!r}, expected {e['origin']!r}: wrong clone, stopping")
    have = git(mac, "rev-parse", "--verify", "-q", f"refs/heads/{br}", check=False).stdout.strip()
    if have and have != m["head_sha"]:
        raise Stop(f"{mac} already has a branch {br} at {have[:10]} (manifest says {m['head_sha'][:10]}); "
                   f"rename or delete it yourself first")
    if not have:
        r = git(mac, "fetch", "--no-tags", e["server"], f"refs/heads/{br}:refs/heads/{br}", check=False)
        if "no common commits" in r.stderr:
            git(mac, "branch", "-D", br, check=False)
            raise Stop(f"'no common commits': {e['server']} is not the same project as {mac}; fetched branch removed")
        if r.returncode != 0:
            raise Stop(f"fetch from {e['server']} failed: {r.stderr.strip()[:300]}")
    tip = git(mac, "rev-parse", f"refs/heads/{br}").stdout.strip()
    if tip != m["head_sha"]:
        raise Stop(f"fetched {br} is at {tip[:10]}, manifest says {m['head_sha'][:10]}: the server moved, prepare again")
    actual = commits(mac, m["base_sha"], br)
    expected = [[c["sha"], c.get("subject", "")] for c in m["commits"]]
    if actual != expected:
        raise Stop(f"commits {m['base_sha'][:10]}..{br} differ from the manifest "
                   f"({len(actual)} found, {len(expected)} listed): not pushing")
    out(f"\n{repo}  {br}  ({len(actual)} commits, base {m['base_sha'][:10]})")
    for s, subj in actual:
        out(f"  {s[:10]} {subj}")
    out(f"diff:  {git(mac, 'diff', '--shortstat', m['base_sha'], br).stdout.strip()}")
    out(f"tests: {m.get('test_cmd') or '(none given)'} -> {m.get('test_result', 'not run')}")
    if m.get("pr_title"):
        out(f"PR title (draft): {m['pr_title']}")
    out(f"review: git -C {mac} diff {m['base_sha'][:10]}..{br}")
    if not a.no_push:
        if ask(f"\npush {br} to origin ({e['origin']})? [y/N] ").strip().lower() != "y":
            out("not pushed. The branch stays local.")
            return 0
        r = git(mac, "push", "origin", f"refs/heads/{br}:refs/heads/{br}", check=False)
        if r.returncode != 0:
            raise Stop(f"push failed: {r.stderr.strip()[:300]}")
        out(f"pushed {br}.")
    if m.get("pr_base"):
        out("open the PR yourself (prefilled, nothing is created until you click):\n  "
            + compare_url(repo, m["pr_base"], br, m.get("pr_title", ""), m.get("pr_body", "")))
    return 0


def in_agent_session():
    sig = [v for v in AGENT_ENV if os.environ.get(v)]
    return sig


# ---- link ----------------------------------------------------------------------------------------
def link(a):
    if not SLUG.fullmatch(a.repo):
        raise Stop("--repo must be OWNER/NAME")
    body = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else ""
    if a.kind == "issue":
        url = f"https://github.com/{a.repo}/issues/new?" + urllib.parse.urlencode({"title": a.title or "", "body": body})
    else:
        if not (a.base and a.branch and BRANCH.fullmatch(a.base) and BRANCH.fullmatch(a.branch)):
            raise Stop("compare needs valid --base and --branch")
        url = compare_url(a.repo, a.base, a.branch, a.title or "", body)
    if len(url) > 8000:
        print("warning: the link is long; GitHub may cut the body. Paste the body by hand.", file=sys.stderr)
    print(url)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("prepare")
    pp.add_argument("--repo", required=True); pp.add_argument("--path", required=True)
    pp.add_argument("--branch", required=True); pp.add_argument("--base", required=True)
    pp.add_argument("--test-cmd"); pp.add_argument("--test-result")
    pp.add_argument("--pr-title"); pp.add_argument("--pr-body-file"); pp.add_argument("--pr-base")
    pp.add_argument("--out", default=DEFAULT_OUT)
    pf = sub.add_parser("fetch")
    pf.add_argument("manifest"); pf.add_argument("--registry", default=DEFAULT_REGISTRY)
    pf.add_argument("--no-push", action="store_true", help="do every check and the fetch, but don't push")
    pl = sub.add_parser("link")
    pl.add_argument("kind", choices=["issue", "compare"]); pl.add_argument("--repo", required=True)
    pl.add_argument("--title"); pl.add_argument("--body-file"); pl.add_argument("--base"); pl.add_argument("--branch")
    a = p.parse_args(argv)
    try:
        if a.cmd == "prepare":
            return prepare(a)
        if a.cmd == "fetch":
            sig = in_agent_session()
            if sig and not a.no_push:
                raise Stop(f"refused: fetch-and-push is for Lodewijk's own terminal (agent environment: {', '.join(sig)}). "
                           f"An agent may run it with --no-push to check a hand-off.")
            if not a.no_push and not sys.stdin.isatty():
                raise Stop("refused: the push question needs a terminal")
            return fetch(a)
        return link(a)
    except Stop as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
