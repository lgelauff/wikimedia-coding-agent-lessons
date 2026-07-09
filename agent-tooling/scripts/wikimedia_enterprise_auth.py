#!/usr/bin/env python3
"""Get a valid Wikimedia Enterprise API access token, caching it so repeated
calls don't re-authenticate every time.

The password is only needed twice: the first login, and again whenever the
cached refresh token expires or is exhausted (every 90 days / 90 refreshes —
see REFRESH_TOKEN_LIFETIME_SECONDS / MAX_REFRESH_COUNT below). Because it's
needed so rarely, this script never persists it to disk: it's read from the
environment if present (for non-interactive/CI use, e.g. a real secrets
manager injecting it at runtime); otherwise it prompts for it interactively —
via a terminal (getpass, no echo) if attached to one, or via a native macOS
GUI dialog (hidden-answer AppleScript, like ssh-askpass) if not — and holds
it in memory just long enough for the login request.

Usage:
    python3 wikimedia_enterprise_auth.py
Prints the access token to stdout on success; all other output (including
the credential prompt) goes to stderr. Non-zero exit + a clear message on
failure (missing credentials in a non-interactive context, auth request
rejected, etc).
"""

import getpass
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import secrets as _agent_secrets  # noqa: E402 (sibling module, not stdlib `secrets`)

AUTH_BASE = "https://auth.enterprise.wikimedia.com/v1"
CACHE_FILE = os.path.expanduser(
    os.environ.get("WIKIMEDIA_ENTERPRISE_TOKEN_CACHE", "~/.cache/wikimedia-enterprise/token.json")
)

# Refresh a bit before actual expiry to avoid races.
EXPIRY_SAFETY_MARGIN_SECONDS = 60
# Per Wikimedia Enterprise docs: a refresh token is valid 90 days and good
# for up to 90 refreshes before a fresh login is required.
REFRESH_TOKEN_LIFETIME_SECONDS = 90 * 86400
MAX_REFRESH_COUNT = 90


def log(msg):
    print(msg, file=sys.stderr)


def post_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Wikimedia Enterprise auth request to {url} failed: {e.code} {body}")


def load_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_cache(cache):
    cache_dir = os.path.dirname(CACHE_FILE)
    if cache_dir and not os.path.isdir(cache_dir):
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)
    os.chmod(CACHE_FILE, 0o600)


def is_valid(expiry_ts):
    return expiry_ts is not None and time.time() < (expiry_ts - EXPIRY_SAFETY_MARGIN_SECONDS)


def gui_prompt(message, hidden=False):
    """Native macOS dialog (AppleScript `display dialog`), like ssh-askpass.
    Returns the entered text, or None if cancelled / osascript unavailable."""
    hidden_clause = "with hidden answer " if hidden else ""
    script = (
        f'display dialog "{message}" with title "Wikimedia Enterprise login" '
        f'default answer "" {hidden_clause}buttons {{"Cancel", "OK"}} default button "OK"'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=300
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None  # cancelled, or osascript not available
    for part in result.stdout.strip().split(", "):
        if part.startswith("text returned:"):
            return part[len("text returned:"):]
    return None


def get_credentials():
    username, password = _prompt_credentials()
    # The login endpoint is case-sensitive on username and rejects a capitalized
    # one with a generic "Incorrect username or password" (looks like a wrong
    # password, not a case mismatch) — normalize here so callers never hit that.
    return username.lower(), password


def _prompt_credentials():
    _agent_secrets.load_into_environ()
    username = os.environ.get("WIKIMEDIA_ENTERPRISE_USERNAME")
    password = os.environ.get("WIKIMEDIA_ENTERPRISE_PASSWORD")
    if username and password:
        return username, password

    prompt_note = (
        "Wikimedia Enterprise login needed (this happens roughly every 90 days). "
        "Pull the credentials from your password manager — nothing is written to disk."
    )

    if sys.stdin.isatty():
        log(prompt_note)
        username = username or input("Wikimedia Enterprise username: ").strip()
        password = password or getpass.getpass("Wikimedia Enterprise password: ")
        return username, password

    if sys.platform == "darwin":
        log(f"{prompt_note} No terminal attached; prompting via a macOS dialog instead.")
        username = username or gui_prompt("Wikimedia Enterprise username:")
        password = password or gui_prompt("Wikimedia Enterprise password:", hidden=True)
        if username and password:
            return username, password
        raise SystemExit("Wikimedia Enterprise login cancelled, or no dialog could be shown.")

    raise SystemExit(
        "No Wikimedia Enterprise credentials available and no terminal/GUI to prompt on. "
        "Set WIKIMEDIA_ENTERPRISE_USERNAME/WIKIMEDIA_ENTERPRISE_PASSWORD in the "
        "environment for non-interactive use, or run this interactively."
    )


def login():
    log("No valid cached token; logging in.")
    username, password = get_credentials()
    resp = post_json(f"{AUTH_BASE}/login", {"username": username, "password": password})
    del password  # not persisted, not logged
    now = time.time()
    cache = {
        "username": username,
        "access_token": resp["access_token"],
        "access_token_expiry": now + resp["expires_in"],
        "refresh_token": resp["refresh_token"],
        "refresh_token_expiry": now + REFRESH_TOKEN_LIFETIME_SECONDS,
        "refresh_count": 0,
    }
    save_cache(cache)
    log("Logged in and cached a new access + refresh token.")
    return cache["access_token"]


def refresh(cache):
    log("Cached access token expired; refreshing with cached refresh token.")
    resp = post_json(
        f"{AUTH_BASE}/token-refresh",
        {"username": cache["username"], "refresh_token": cache["refresh_token"]},
    )
    now = time.time()
    cache["access_token"] = resp["access_token"]
    cache["access_token_expiry"] = now + resp["expires_in"]
    cache["refresh_count"] = cache.get("refresh_count", 0) + 1
    save_cache(cache)
    log("Refreshed access token (no login needed).")
    return cache["access_token"]


def get_access_token():
    cache = load_cache()
    if cache and is_valid(cache.get("access_token_expiry")):
        log("Using cached access token.")
        return cache["access_token"]

    if (
        cache
        and is_valid(cache.get("refresh_token_expiry"))
        and cache.get("refresh_count", 0) < MAX_REFRESH_COUNT
    ):
        return refresh(cache)

    return login()


if __name__ == "__main__":
    print(get_access_token())
