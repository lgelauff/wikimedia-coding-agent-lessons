#!/usr/bin/env python3
"""mandated_services.py — validate the Mandated Services Registry and catch drift.

The registry (`agent-tooling/settings/mandated-services.json`) is the single allow-list
that `policies/webfetch_mandated.py` enforces. It has two jobs:

  1. **Validate** the registry against its own schema, so a malformed entry cannot
     silently produce a rule that matches nothing while reading as protection.
  2. **Catch drift** against the connector library in
     `skills/source-connectors/SKILL.md`. That library is the human-readable source of
     truth for data connectors; the registry must mirror its endpoints exactly. Add a
     connector row and this fails until the registry follows; remove one and it fails
     the other way. That is what keeps the two from diverging.

The registry is not generated wholesale from the skill, because most of its entries
(Wikimedia data APIs, LiftWing, Enterprise, docs/tool hosts) are documented in other
skills and scripts. The connector-derived subset *is* checked mechanically, and every
entry must name an existing source file.

Agent-agnostic: knows nothing about any agent's event format.

  mandated_services.py                # validate + drift check; exit 0 clean, 1 problem
  mandated_services.py --emit-hosts   # print the flattened allow-list
  mandated_services.py --json         # the allow-list as JSON {hosts, host_suffixes}
  mandated_services.py --skill P --registry Q   # check alternate files (tests)

Exit codes: 0 clean · 1 invalid/drift · 2 could not complete.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]                       # .../agent-tooling/scripts -> repo
DEFAULT_REGISTRY = REPO_ROOT / "agent-tooling" / "settings" / "mandated-services.json"
DEFAULT_SKILL = REPO_ROOT / "agent-tooling" / "skills" / "source-connectors" / "SKILL.md"

CONNECTOR_LIBRARY = "agent-tooling/skills/source-connectors/SKILL.md"

# A hostname: at least one dot, alphabetic TLD of 2+ chars. Deliberately rejects
# version strings ("2.0", "v1.1") that appear in the same table cells.
HOSTNAME = re.compile(
    r"(?<![\w.-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,})(?![\w.-])",
    re.IGNORECASE,
)
LIBRARY_START = re.compile(r"^##\s+4\.\s+The library", re.IGNORECASE)
LIBRARY_END = re.compile(r"^##\s+Kept out of the library", re.IGNORECASE)


def parse_connector_hosts(skill_path: Path) -> set[str]:
    """Endpoint hosts named in the §4 connector-library tables.

    Reads the **endpoint column** (column 2), falling back to the name column only
    when the endpoint cell carries no host (the `open.overheid.nl` row). The recipe,
    access-policy and fallback columns are deliberately not read: they name front-ends
    and archive paths (e.g. `zoek.officielebekendmakingen.nl`) that are not the
    connector's own endpoint, and would over-collect. A host that legitimately sits
    outside the endpoint cell (Flickr's image CDN) is declared as an `auxiliary_hosts`
    entry in the registry instead.
    """
    text = skill_path.read_text(encoding="utf-8")
    hosts: set[str] = set()
    in_library = False
    for line in text.splitlines():
        if LIBRARY_START.match(line):
            in_library = True
            continue
        if LIBRARY_END.match(line):
            break
        if not in_library or not line.lstrip().startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) < 3:
            continue
        endpoint = {m.group(1).lower() for m in HOSTNAME.finditer(cells[2])}
        if endpoint:
            hosts |= endpoint
        else:
            hosts |= {m.group(1).lower() for m in HOSTNAME.finditer(cells[1])}
    return hosts


def connector_hosts(registry: dict) -> set[str]:
    """Hosts of services sourced from the connector library."""
    out: set[str] = set()
    for svc in registry.get("services", []):
        if CONNECTOR_LIBRARY in (svc.get("sources") or []):
            out.update(h.lower() for h in svc.get("hosts", []))
    return out


def _suffix_ok(suffix: str) -> bool:
    return bool(re.fullmatch(r"\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", suffix))


def validate(registry: dict, repo_root: Path) -> list[str]:
    """Schema + cross-entry validation. Returns a list of human-readable problems."""
    problems: list[str] = []

    if not isinstance(registry, dict):
        return ["registry is not a JSON object"]
    if not isinstance(registry.get("services"), list) or not registry["services"]:
        return ["registry has no `services` list"]

    seen_ids: set[str] = set()
    exact: dict[str, str] = {}
    suffixes: dict[str, str] = {}

    for i, svc in enumerate(registry["services"]):
        where = f"services[{i}] ({svc.get('id', '?')})"
        for key in ("id", "service", "kind", "hosts", "sources", "verified"):
            if key not in svc:
                problems.append(f"{where}: missing required key `{key}`")
        sid = svc.get("id", "")
        if sid in seen_ids:
            problems.append(f"{where}: duplicate id `{sid}`")
        seen_ids.add(sid)

        hosts = svc.get("hosts", [])
        if not isinstance(hosts, list):
            problems.append(f"{where}: `hosts` must be a list")
            hosts = []
        aux = svc.get("auxiliary_hosts", [])
        if not isinstance(aux, list):
            problems.append(f"{where}: `auxiliary_hosts` must be a list")
            aux = []
        for h in list(hosts) + list(aux):
            h = str(h).lower()
            if not HOSTNAME.fullmatch(h):
                problems.append(f"{where}: `{h}` is not a bare hostname")
            if h in exact:
                problems.append(f"{where}: host `{h}` already claimed by `{exact[h]}`")
            exact[h] = sid

        suf_list = svc.get("host_suffixes", [])
        if not isinstance(suf_list, list):
            problems.append(f"{where}: `host_suffixes` must be a list")
            suf_list = []
        for s in suf_list:
            s = str(s).lower()
            if not _suffix_ok(s):
                problems.append(f"{where}: suffix `{s}` is not a leading-dot domain")
            if s in suffixes:
                problems.append(f"{where}: suffix `{s}` already claimed by `{suffixes[s]}`")
            suffixes[s] = sid

        if not hosts and not suf_list:
            problems.append(f"{where}: has neither `hosts` nor `host_suffixes`")

        sources = svc.get("sources", [])
        if not isinstance(sources, list):
            problems.append(f"{where}: `sources` must be a list")
            sources = []
        elif not sources:
            problems.append(f"{where}: `sources` must name at least one file")
        for src in sources:
            if not (repo_root / src).exists():
                problems.append(f"{where}: source `{src}` does not exist")

        verified = str(svc.get("verified", ""))
        if not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", verified):
            problems.append(f"{where}: `verified` must be YYYY-MM or YYYY-MM-DD, got `{verified}`")

    # An exact host covered by another entry's suffix is ambiguous: which entry owns it?
    for h, sid in exact.items():
        for s, owner in suffixes.items():
            if owner != sid and (h == s[1:] or h.endswith(s)):
                problems.append(f"host `{h}` ({sid}) is also covered by suffix `{s}` ({owner})")

    return problems


def drift(registry: dict, skill_path: Path) -> list[str]:
    """Differences between the skill's connector endpoints and the registry's."""
    problems: list[str] = []
    if not skill_path.exists():
        return [f"connector library not found at {skill_path}"]
    parsed = parse_connector_hosts(skill_path)
    declared = connector_hosts(registry)

    missing = sorted(parsed - declared)
    extra = sorted(declared - parsed)
    for h in missing:
        problems.append(f"drift: `{h}` is a connector endpoint in the library but not in the registry")
    for h in extra:
        problems.append(f"drift: `{h}` is in the registry as a connector but not in the library")
    return problems


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def allow_list(registry: dict) -> dict:
    hosts, suffixes = set(), set()
    for svc in registry.get("services", []):
        hosts.update(h.lower() for h in svc.get("hosts", []))
        hosts.update(h.lower() for h in svc.get("auxiliary_hosts", []))
        suffixes.update(s.lower() for s in svc.get("host_suffixes", []))
    return {"hosts": sorted(hosts), "host_suffixes": sorted(suffixes)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--skill", default=str(DEFAULT_SKILL))
    ap.add_argument("--emit-hosts", action="store_true", help="print the flattened allow-list")
    ap.add_argument("--json", action="store_true", help="with --emit-hosts: emit JSON")
    a = ap.parse_args()

    try:
        registry = load(Path(a.registry))
    except Exception as e:
        print(f"COULD NOT COMPLETE: cannot read {a.registry}: {e}")
        return 2

    if a.emit_hosts:
        data = allow_list(registry)
        if a.json:
            print(json.dumps(data, indent=2))
        else:
            for h in data["hosts"]:
                print(h)
            for s in data["host_suffixes"]:
                print(s)
        return 0

    problems = validate(registry, REPO_ROOT) + drift(registry, Path(a.skill))
    if problems:
        print(f"mandated-services: {len(problems)} problem(s)")
        for p in problems:
            print(f"  {p}")
        return 1
    n_svc = len(registry.get("services", []))
    al = allow_list(registry)
    print(f"mandated-services: OK — {n_svc} services, "
          f"{len(al['hosts'])} hosts + {len(al['host_suffixes'])} suffixes; "
          f"connector library in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
