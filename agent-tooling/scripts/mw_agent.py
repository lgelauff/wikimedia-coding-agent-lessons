#!/usr/bin/env python3
"""Run the Wikimedia `mw` CLI the way agents may: read-only, paced, inside the boundary.

    python3 mw_agent.py codesearch search --output json onPageSaveComplete

- HOME is pointed at ~/agent/mwcli-home, so mw's config (it writes one on every
  run) stays inside the agent boundary instead of ~/Library/Application Support.
- --no-interaction is always added: no telemetry consent or login prompt is
  ever answered by an agent.
- Calls are spaced >= 1 s apart across processes (Wikimedia Robot policy,
  "Rules for other resources": concurrency 1, >= 1 s between requests).
- Command groups and verbs that write, authenticate, or open SSH are refused
  (see the wikimedia-dev-cli skill, tier C). Exit 2 with the reason.

Environment: MW_BIN (default ~/agent/bin/mw), MW_AGENT_HOME (default
~/agent/mwcli-home).
"""
import fcntl
import os
import sys
import time

AGENT = os.path.expanduser("~/agent")
MW_BIN = os.environ.get("MW_BIN", os.path.join(AGENT, "bin", "mw"))
MW_HOME = os.environ.get("MW_AGENT_HOME", os.path.join(AGENT, "mwcli-home"))
SPACING_S = 1.0

ALLOWED_GROUPS = {"codesearch", "gerrit", "gitlab", "phabricator", "tools",
                  "analytics", "version", "help", "wiki", "api", "events"}
# `mw wiki`: only these second words; always anonymous (--anon is added).
WIKI_ALLOWED = {"page", "api", "rest"}
WIKI_PAGE_READS = {"categories", "diff", "get", "history", "info", "list"}
# Any of these tokens anywhere in the command path refuses it.
DENY_TOKENS = {
    # auth and secrets
    "auth", "login", "logout", "secrets", "token", "password", "oauthtoken",
    "ssh-key", "gpg-key", "sshkeys", "gpgkeys",
    # writes and state changes
    "create", "edit", "delete", "set", "assign", "mv", "move", "setprio",
    "setstatus", "priority", "status", "rmtag", "abandon", "restore", "rebase",
    "revert", "revert-submission", "submit", "merge", "publish", "ready",
    "private", "star", "unstar", "sign", "attention", "hashtags", "update",
    "approve", "close", "reopen", "note", "retry", "cancel", "run", "trigger",
    "upload", "fork", "clone", "archive", "transfer", "index",
    # generic write verbs in nested groups, and Gerrit change verbs that can set state
    # (refused even where a read form exists; use `gerrit api` GET for those reads)
    "add", "remove", "put", "post", "review", "vote", "reply", "comment",
    "wip", "message", "topic", "patch", "dotgitreview", "put", "bulk",
    # interactive / ssh
    "shell", "browse", "ssh", "mcp", "duo",
}
DENY_FLAGS = {"--password", "--auth-password", "--auth-user", "--password-stdin"}
# `mw wiki …` and `mw api …`: no request bodies, custom headers, tokens or saved logins.
WIKI_API_DENY_FLAGS = {"--input", "-H", "--header", "--token", "--profile",
                       "--username", "--password-file", "--realm"}
# Absolute URLs passed to `mw api` must be on one of these (or a subdomain).
API_HOSTS = {"wikimedia.org", "wikipedia.org", "wikidata.org", "wiktionary.org",
             "wikibooks.org", "wikinews.org", "wikiquote.org", "wikisource.org",
             "wikiversity.org", "wikivoyage.org", "mediawiki.org", "wikifunctions.org",
             "toolforge.org", "wmcloud.org"}


def refuse(reason):
    print(f"mw_agent: REFUSED: {reason}", file=sys.stderr)
    sys.exit(2)


def check(args):
    words = [a for a in args if not a.startswith("-")]
    if not words:
        refuse("no command given")
    if words[0] not in ALLOWED_GROUPS:
        refuse(f"command group {words[0]!r} is not agent-allowed")
    if words[0] == "wiki" and (len(words) < 2 or words[1] not in WIKI_ALLOWED):
        refuse("mw wiki: only page/api/rest reads are agent-allowed")
    # (flag values count as words here, so a flag before the verb refuses: safe side)
    if words[0] == "wiki" and words[1] == "page" and (len(words) < 3 or words[2] not in WIKI_PAGE_READS):
        refuse(f"mw wiki page: only {sorted(WIKI_PAGE_READS)}; put the verb before any flags")
    if words[0] == "wiki" and words[1] == "rest" and (len(words) < 3 or words[2].lower() != "get"):
        refuse("mw wiki rest: GET only (mw wiki rest get PATH)")
    # only the command path is checked, not search terms or API paths
    path = words[:2] if words[0] in ("codesearch", "help", "version") else words[:4]
    if words[0] in ("gerrit", "gitlab") and len(words) > 1 and words[1] == "api":
        path = words[:2]
    for w in path:
        if w in DENY_TOKENS:
            refuse(f"{w!r} writes, authenticates or opens a shell (tier C)")
    for a in args:
        if a.split("=", 1)[0] in DENY_FLAGS:
            refuse(f"{a.split('=', 1)[0]} would put a credential on the command line")
    if words[0] in ("wiki", "api"):
        for a in args:
            name = a.split("=", 1)[0]
            if name in WIKI_API_DENY_FLAGS:
                refuse(f"{name} would send a body, a header, a token or a saved login")
    if words[0] == "api":
        method_get = False
        for i, a in enumerate(args):
            if a in ("-X", "--method") and i + 1 < len(args):
                method_get = args[i + 1].upper() == "GET"
            elif a.startswith("--method="):
                method_get = a.split("=", 1)[1].upper() == "GET"
        has_fields = any(a in ("-f", "--field") or a.startswith("--field=") for a in args)
        if has_fields and not method_get:
            refuse("mw api: fields select POST unless -X GET is given")
        target = words[1] if len(words) > 1 else ""
        if "://" in target:
            host = target.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].lower()
            if not any(host == s or host.endswith("." + s) for s in API_HOSTS):
                refuse(f"mw api: host {host!r} is not a Wikimedia API host")
    if words[0] == "events" and len(words) > 1 and words[1] not in ("list", "info"):
        refuse("mw events: only list/info (tail is an unbounded stream)")
    # `mw gerrit api` / `mw gitlab api` / `mw api` / `mw wiki api`: GET only
    if "api" in words[:3]:
        for i, a in enumerate(args):
            if a in ("-X", "--method") and i + 1 < len(args) and args[i + 1].upper() != "GET":
                refuse("api calls are GET only")
            if a.startswith("--method=") and a.split("=", 1)[1].upper() != "GET":
                refuse("api calls are GET only")


def pace():
    os.makedirs(MW_HOME, exist_ok=True)
    lock_path = os.path.join(MW_HOME, ".mw_agent.lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)  # one mw call at a time across processes
    try:
        last = float(os.read(fd, 64) or b"0")
    except ValueError:
        last = 0.0
    wait = last + SPACING_S - time.time()
    if wait > 0:
        time.sleep(wait)
    return fd


def main():
    args = sys.argv[1:]
    check(args)
    if not os.access(MW_BIN, os.X_OK):
        refuse(f"{MW_BIN} not installed")
    fd = pace()
    env = dict(os.environ, HOME=MW_HOME)
    pid = os.fork()
    if pid == 0:
        first = next((a for a in args if not a.startswith("-")), "")
        extra = ["--anon"] if first == "wiki" and "--anon" not in args else []
        os.execve(MW_BIN, [MW_BIN, *args, "--no-interaction", *extra], env)
    _, status = os.waitpid(pid, 0)
    os.lseek(fd, 0, 0)
    os.ftruncate(fd, 0)
    os.write(fd, str(time.time()).encode())
    os.close(fd)  # releases the lock
    sys.exit(os.waitstatus_to_exitcode(status))


if __name__ == "__main__":
    main()
