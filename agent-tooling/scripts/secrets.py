#!/usr/bin/env python3
"""secrets.py — resolve API keys from one user-global store, cwd-independent.

So any script, run from any folder or session, authenticates the same way —
and the value is read by the script itself, never passed as an arg or printed,
so an agent that *invokes* the script never sees it.

Resolution order for get_secret(NAME):
  1. os.environ[NAME]              (already exported — wins)
  2. the central secrets file      ($AGENT_SECRETS_FILE, else ~/.config/agent-secrets/.env)

The file is a plain dotenv (`KEY=value` per line, # comments). Keep it chmod 600
and OUTSIDE any git repo.

API:
  get_secret("IA_ACCESS_KEY")                 -> value or None
  get_secret("IA_ACCESS_KEY", required=True)  -> value or RuntimeError
  load_into_environ()                          -> populate os.environ from the file
        (for libraries that read os.environ directly, e.g. spn2.py — call this
         once at startup; it won't overwrite already-set vars unless override=True)

CLI (debug; never prints values):
  secrets.py --check IA_ACCESS_KEY IA_SECRET_KEY   ->  IA_ACCESS_KEY: set (env)
"""
import os
import pathlib
import sys

DEFAULT_FILE = pathlib.Path.home() / ".config" / "agent-secrets" / ".env"


def _secrets_file() -> pathlib.Path:
    return pathlib.Path(os.environ.get("AGENT_SECRETS_FILE", str(DEFAULT_FILE))).expanduser()


def _parse(path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        if k.startswith("export "):
            k = k[len("export "):].strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def get_secret(name: str, *, required: bool = False, default: str | None = None) -> str | None:
    """Env first, then the central file. Never logs the value."""
    val = os.environ.get(name)
    if val:
        return val
    val = _parse(_secrets_file()).get(name)
    if val:
        return val
    if required:
        raise RuntimeError(
            f"secret {name!r} not found in env or {_secrets_file()}. "
            "Add it to the central secrets file (chmod 600, outside any repo).")
    return default


def load_into_environ(names: list[str] | None = None, *, override: bool = False) -> int:
    """Populate os.environ from the central file for libs that read it directly.
    Returns how many vars were set (count only — never the values)."""
    data = _parse(_secrets_file())
    n = 0
    for k, v in data.items():
        if names is not None and k not in names:
            continue
        if override or not os.environ.get(k):
            os.environ[k] = v
            n += 1
    return n


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Check secret availability (never prints values).")
    ap.add_argument("--check", nargs="+", metavar="NAME", required=True)
    a = ap.parse_args()
    rc = 0
    for name in a.check:
        if os.environ.get(name):
            print(f"{name}: set (env)")
        elif _parse(_secrets_file()).get(name):
            print(f"{name}: set (file)")
        else:
            print(f"{name}: MISSING")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
