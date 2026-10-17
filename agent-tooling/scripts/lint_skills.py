#!/usr/bin/env python3
"""Lint each SKILL.md against the published authoring limits and the cheap smells.

audit_skills.py checks the skill SET (trigger collisions, dangling references). This checks
each skill ALONE. It exists because two skills here sat over the 1,024-character description
limit (pr-check 1,098, e2e-design 1,072) and nothing noticed; a skill over that limit is
rejected by the Agent Skills API, and in Claude Code an over-long listing loses descriptions.

  ERROR  name-format      name != dir, not [a-z0-9-], >64 chars, or a reserved word
  ERROR  desc-length      description empty or > 1024 chars
  ERROR  desc-xml         XML/HTML tag in the description
  WARN   desc-no-when     no "Use when / whenever / Use it …" clause
  WARN   desc-late-when   the first trigger clause starts after char 400; Claude Code truncates
                          the listing entry from the end, so the trigger must come first
  WARN   desc-person      first or second person outside quoted user phrasings
  WARN   desc-markup      markdown emphasis in the description (shows as literal ** in the listing)
  WARN   body-lines       body > 500 lines
  WARN   body-words       body > 5000 words
  WARN   ref-depth        a bundled .md that links on to another bundled .md (Claude may only
                          preview nested files)
  WARN   ref-no-toc       a bundled .md over 100 lines with no Contents heading
  WARN   backslash-path   Windows-style path in prose
  WARN   bare-script      a fenced shell command runs `x.py` / `scripts/x.py` that is neither
                          bundled with the skill nor prefixed with ${AGENT_TOOLING_ROOT}; from a
                          consuming repo it resolves against that repo's cwd or $PATH

A reviewed exception is written into the skill itself, so it stays visible:
    <!-- lint: allow bare-script -->

Sources for the limits: Anthropic "Skill authoring best practices" (platform.claude.com) and the
Claude Code skills page. Research note: ~/agent/review/skill-quality-2026-10-12/NOTES.md.

Usage:  lint_skills.py [SKILLS_DIR | path/to/SKILL.md ...]   (default: agent-tooling/skills)
Exit:   0 no errors (warnings allowed) · 1 errors found · 2 could not complete
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DESC_MAX = 1024          # Agent Skills API hard limit
NAME_MAX = 64            # Agent Skills API hard limit
WHEN_BY = 400            # well inside Claude Code's 1,536-char listing cap; trigger first
BODY_LINES = 500         # Anthropic best-practices guidance
BODY_WORDS = 5000        # the "lengthy skill body" smell threshold (arXiv:2607.01456)
TOC_LINES = 100          # Anthropic best-practices guidance for reference files

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
WHEN_RE = re.compile(
    r"\buse (it |this |me )?(when|whenever|before|for|instead)\b|\buse it\b|\btrigger", re.I)
PERSON_RE = re.compile(r"\b(I can|I will|I'll|you|your|you're)\b")
QUOTED_RE = re.compile(r"\"[^\"]*\"|“[^”]*”|'[^']{6,}'")
XML_RE = re.compile(r"<[A-Za-z/][^>]*>")
MD_EMPH_RE = re.compile(r"\*\*[^*]+\*\*|__[^_]+__")
LINK_RE = re.compile(r"\]\(([^)#]+\.md)\)|`([A-Za-z0-9_./-]+\.md)`")
FENCE_RE = re.compile(r"```(?:bash|sh|shell|zsh)?\n(.*?)```", re.S)
ALLOW_RE = re.compile(r"<!--\s*lint:\s*allow\s+([a-z, -]+?)\s*-->")


def frontmatter(text: str) -> tuple[dict, str]:
    m = FM_RE.match(text)
    if not m:
        return {}, text
    fm: dict = {}
    key = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^[a-zA-Z_-]+:", line):
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            fm[key] = "" if val in (">-", ">", "|", "|-") else val.strip("'\"")
        elif key:
            fm[key] = (fm[key] + " " + line.strip()).strip()
    return fm, text[m.end():]


def bare_script(body: str, d: Path) -> str | None:
    """First fenced shell line whose command is an unbundled, unprefixed script, or None.

    Prose mentions (`the scope.py call`) are not commands an agent copies, so only fenced
    blocks count.
    """
    for block in FENCE_RE.findall(body):
        for line in block.splitlines():
            if "AGENT_TOOLING_ROOT" in line:
                continue
            cmd = re.sub(r"^.*?\|\s*", "", line.strip())        # the piped-to command
            cmd = re.sub(r"^(python3?|bash|sh|uv run)\s+", "", cmd)
            m = re.match(r"[\"']?((?:scripts/)?[\w-]+\.(?:py|sh))\b", cmd)
            if not m:
                continue
            tok = m.group(1)
            if (d / tok).exists() or (d / "scripts" / Path(tok).name).exists():
                continue                                        # bundled: relative is right
            return line.strip()[:70]
    return None


def lint(skill_md: Path) -> list[tuple[str, str, str]]:
    text = skill_md.read_text(encoding="utf-8")
    fm, body = frontmatter(text)
    if not fm:
        return [("ERROR", "frontmatter", "no YAML frontmatter")]
    d = skill_md.parent
    name, desc = fm.get("name", ""), fm.get("description", "")
    allowed = {r.strip() for m in ALLOW_RE.findall(text) for r in m.split(",")}
    out: list[tuple[str, str, str]] = []

    if (name != d.name or not NAME_RE.match(name) or len(name) > NAME_MAX
            or "anthropic" in name or "claude" in name):
        out.append(("ERROR", "name-format", f"name={name!r} dir={d.name!r}"))
    if not desc:
        out.append(("ERROR", "desc-length", "description is empty"))
    elif len(desc) > DESC_MAX:
        out.append(("ERROR", "desc-length", f"{len(desc)} chars > {DESC_MAX}"))
    xml = XML_RE.search(desc)
    if xml:
        out.append(("ERROR", "desc-xml", xml.group(0)))
    when = WHEN_RE.search(desc)
    if desc and not when:
        out.append(("WARN", "desc-no-when", "no 'Use when…' clause"))
    elif when and when.start() > WHEN_BY:
        out.append(("WARN", "desc-late-when", f"first trigger clause at char {when.start()}"))
    # Quoted user phrasings ("what did you change") are trigger examples, not point of view.
    person = PERSON_RE.findall(QUOTED_RE.sub("", desc))
    if person:
        out.append(("WARN", "desc-person", f"{sorted(set(person))}"))
    emph = MD_EMPH_RE.search(desc)
    if emph:
        out.append(("WARN", "desc-markup", emph.group(0)))

    lines, words = body.count("\n"), len(body.split())
    if lines > BODY_LINES:
        out.append(("WARN", "body-lines", f"{lines} lines > {BODY_LINES}"))
    if words > BODY_WORDS:
        out.append(("WARN", "body-words", f"{words} words > {BODY_WORDS}"))

    prose = re.sub(r"```.*?```", "", body, flags=re.S)       # code may show other OS paths
    if re.search(r"\b[\w.-]+\\[\w.-]+\.(md|py|sh|json)\b", prose):
        out.append(("WARN", "backslash-path", "Windows-style path in prose"))
    bare = bare_script(body, d)
    if bare:
        out.append(("WARN", "bare-script", f"`{bare}`"))

    for ref in sorted({a or b for a, b in LINK_RE.findall(body)}):
        rp = d / ref
        if not rp.is_file() or d.resolve() not in rp.resolve().parents:
            continue
        rtext = rp.read_text(encoding="utf-8")
        # A link back up to SKILL.md is navigation, not a deeper level.
        nested = [a or b for a, b in LINK_RE.findall(rtext)
                  if (rp.parent / (a or b)).is_file()
                  and (rp.parent / (a or b)).resolve() != skill_md.resolve()]
        if nested:
            out.append(("WARN", "ref-depth", f"{ref} -> {nested[0]}"))
        if (rtext.count("\n") > TOC_LINES and not
                re.search(r"^#+\s*(Contents|Table of contents)", rtext, re.M | re.I)):
            out.append(("WARN", "ref-no-toc", f"{ref} ({rtext.count(chr(10))} lines)"))

    out = [f for f in out if f[1] not in allowed]
    out.append(("INFO", "size", f"desc={len(desc)}c body={lines}l/{words}w"))
    return out


def collect(args: list[str]) -> list[Path]:
    roots = [Path(a) for a in args] or [Path(__file__).resolve().parent.parent / "skills"]
    files: list[Path] = []
    for r in roots:
        files += [r] if r.name == "SKILL.md" else sorted(r.glob("*/SKILL.md"))
    return files


def main(argv: list[str]) -> int:
    files = collect(argv)
    if not files:
        sys.stderr.write("lint_skills: no SKILL.md found\n")
        return 2
    errors = warns = desc_total = 0
    for f in files:
        try:
            findings = lint(f)
        except (OSError, UnicodeDecodeError) as e:
            sys.stderr.write(f"lint_skills: cannot read {f}: {e}\n")
            return 2
        shown = [x for x in findings if x[0] != "INFO"]
        size = findings[-1][2]
        desc_total += int(size.split("=")[1].split("c")[0])
        print(f"{f.parent.name:24} {size}")
        for sev, rule, msg in shown:
            print(f"  {sev:5} {rule:15} {msg}")
        errors += sum(1 for x in shown if x[0] == "ERROR")
        warns += sum(1 for x in shown if x[0] == "WARN")
    print(f"\n{len(files)} skill(s), {errors} error(s), {warns} warning(s), "
          f"{desc_total} description chars in total")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
