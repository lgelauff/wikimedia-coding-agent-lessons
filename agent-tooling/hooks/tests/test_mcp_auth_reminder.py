"""Tests for the MCP auth reminder hook's pure decision functions.

`needs_auth` shells out to the CLI and isn't unit-tested here; everything that
decides *whether* to shell out is, because that's what keeps the hook silent on
ordinary prompts.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
from mcp_auth_reminder import configured_servers, servers_mentioned  # noqa: E402


def _write(tmp_path, data):
    p = tmp_path / "claude.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_maps_hostname_to_server_name(tmp_path):
    path = _write(tmp_path, {"mcpServers": {"Jam": {"type": "http", "url": "https://mcp.jam.dev/mcp"}}})
    servers = configured_servers(path)
    assert servers["mcp.jam.dev"] == "Jam"


def test_also_matches_the_registrable_domain(tmp_path):
    # A shared recording lives at jam.dev/c/xxx while the server is at
    # mcp.jam.dev — the link the user pastes must still match.
    path = _write(tmp_path, {"mcpServers": {"Jam": {"type": "http", "url": "https://mcp.jam.dev/mcp"}}})
    assert configured_servers(path)["jam.dev"] == "Jam"


def test_stdio_servers_without_url_are_ignored(tmp_path):
    path = _write(tmp_path, {"mcpServers": {"local": {"type": "stdio", "command": "npx"}}})
    assert configured_servers(path) == {}


def test_missing_or_broken_config_is_not_fatal(tmp_path):
    assert configured_servers(str(tmp_path / "nope.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert configured_servers(str(bad)) == {}


def test_finds_server_from_a_pasted_share_link():
    servers = {"mcp.jam.dev": "Jam", "jam.dev": "Jam"}
    prompt = "here's the repro https://jam.dev/c/9f2a-401b take a look"
    assert servers_mentioned(prompt, servers) == ["Jam"]


def test_unrelated_urls_do_not_match():
    servers = {"mcp.jam.dev": "Jam", "jam.dev": "Jam"}
    prompt = "see https://github.com/lgelauff/wiki-polis/pull/302 and https://example.com"
    assert servers_mentioned(prompt, servers) == []


def test_no_url_at_all_matches_nothing():
    assert servers_mentioned("just talking about jam.dev in prose", {"jam.dev": "Jam"}) == []


def test_each_server_reported_once_even_if_linked_repeatedly():
    servers = {"jam.dev": "Jam"}
    prompt = "https://jam.dev/c/aaa and also https://jam.dev/c/bbb"
    assert servers_mentioned(prompt, servers) == ["Jam"]
