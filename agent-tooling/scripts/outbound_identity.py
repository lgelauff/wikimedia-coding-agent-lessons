#!/usr/bin/env python3
"""outbound_identity.py: the one place scripts get their User-Agent and identifying parameters.

Reads settings/outbound-identity.json (public, no secrets) and resolves private values, such as
Lodewijk's contact e-mail, from the environment or the central secrets file via agent_secrets
(never from the repo). A script asks for its service and gets what it is approved to send:

    from outbound_identity import user_agent, params
    headers = {"User-Agent": user_agent("crossref")}
    query = {"query": q, **params("crossref")}

Templates use {identity}; a [bracketed part] is dropped when an identity inside it is unset, so
an unconfigured machine sends anonymous but still descriptive requests. Unknown services get the
default. Values are never printed by the CLI.

CLI:
  outbound_identity.py --check            # every service: which identities resolve (set/unset)
  outbound_identity.py --show crossref    # the UA and params with private values masked
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent_secrets import get_secret  # noqa: E402

DEFAULT_FILE = Path(__file__).resolve().parent.parent / "settings" / "outbound-identity.json"
_OPTIONAL = re.compile(r"\[([^\[\]]*)\]")
_FIELD = re.compile(r"\{([a-z0-9-]+)\}")


def load(path: Path | None = None) -> dict:
    return json.loads(Path(path or os.environ.get("OUTBOUND_IDENTITY_FILE", DEFAULT_FILE)).read_text())


def _resolve(name: str, cfg: dict) -> str | None:
    ident = cfg["identities"].get(name)
    if ident is None:
        raise KeyError(f"unknown identity {name!r} in outbound-identity.json")
    if "value" in ident:
        return ident["value"]
    return get_secret(ident["env_key"])


def render(template: str, cfg: dict) -> str | None:
    """Fill {identity} fields; drop [optional parts] with an unset field. None if a required one is unset."""
    def optional(m):
        part = m.group(1)
        return part if all(_resolve(n, cfg) for n in _FIELD.findall(part)) else ""
    text = _OPTIONAL.sub(optional, template)
    values = {n: _resolve(n, cfg) for n in _FIELD.findall(text)}
    if any(v is None for v in values.values()):
        return None
    return _FIELD.sub(lambda m: values[m.group(1)], text)


def _entry(service: str, cfg: dict) -> dict:
    return cfg["entries"].get(service, cfg["default"])


def user_agent(service: str = "", cfg: dict | None = None) -> str:
    cfg = cfg or load()
    ua = render(_entry(service, cfg)["user_agent"], cfg)
    return ua if ua is not None else render(cfg["default"]["user_agent"], cfg)


def params(service: str = "", cfg: dict | None = None) -> dict:
    """Identifying query parameters the service is approved to receive; unset ones are omitted."""
    cfg = cfg or load()
    out = {}
    for key, template in _entry(service, cfg).get("params", {}).items():
        value = render(template, cfg)
        if value:
            out[key] = value
    return out


def _mask(text: str, cfg: dict) -> str:
    for name, ident in cfg["identities"].items():
        if "env_key" in ident:
            v = get_secret(ident["env_key"])
            if v:
                text = text.replace(v, f"<{name}>")
    return text


def main(argv: list[str]) -> int:
    cfg = load()
    if argv[:1] == ["--check"]:
        for name, ident in cfg["identities"].items():
            state = "value" if "value" in ident else ("set" if get_secret(ident["env_key"]) else "UNSET")
            print(f"{name}: {state}")
        return 0
    if argv[:1] == ["--show"] and len(argv) == 2:
        print("User-Agent:", _mask(user_agent(argv[1], cfg), cfg))
        print("params:", _mask(json.dumps(params(argv[1], cfg)), cfg))
        return 0
    print(__doc__.split("CLI:")[1].strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
