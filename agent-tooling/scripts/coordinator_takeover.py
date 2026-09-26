#!/usr/bin/env python3
"""coordinator_takeover.py — the coordinator takeover in one approved call.

A new sessions coordinator must read the rolling STATE.md, compute its sha256, add its own row to
AGENT-LOG.md with `pred` set to the previous coordinator, and log an `ack` event carrying that hash.
Done by hand that is five tool calls and five permission prompts; this does it as one.

  coordinator_takeover.py --pred S002 --where "mac/lodewijk · wikimedia-coding-agent-lessons (main checkout)"
  coordinator_takeover.py --pred S002 --where ... --dry-run     # show the rows, write nothing

Prints the hash, the rows it appended, and then STATE.md itself, so the session needs no separate
read. Rows are appended, never edited (agent-log-design-2026-09-25.md), so a row in the wrong place
cannot be fixed afterwards: the script refuses rather than guesses. It refuses on an unknown
predecessor, a predecessor that already has a successor (an `ack`/`handoff` from it), a taken or malformed id,
and a log whose `## Sessions` / `## Custody events` tables cannot be found.

Only the coordinator writes the log (one writer), so there is no lock.
"""
import argparse
import datetime
import hashlib
import os
import pathlib
import re
import sys
import tempfile

NOTES = pathlib.Path.home() / "agent" / "notes"
DEFAULT_STATE = NOTES / "wikimedia-coding-agent-lessons" / "STATE.md"
DEFAULT_LOG = NOTES / "AGENT-LOG.md"

SESSIONS_HEADING = "## Sessions"
EVENTS_HEADING = "## Custody events"
_SESSION_ID = re.compile(r"^S\d{3,}$")
_SESSION_ROW = re.compile(r"^\| (S\d{3,}) \|")
_EVENT_ROW = re.compile(r"^\| (E\d{3,}) \|")


class TakeoverError(Exception):
    pass


def _section_rows(lines, heading, pattern):
    """(index, id) of the table rows in the section under `heading` (up to the next `## `).

    Scoped to the section so a row-shaped line elsewhere (an example in a code block, a later
    table) can never capture the insert position.
    """
    starts = [i for i, l in enumerate(lines) if l.rstrip() == heading]
    if len(starts) != 1:
        raise TakeoverError("expected exactly one %r heading, found %d" % (heading, len(starts)))
    rows, fenced = [], False
    for i in range(starts[0] + 1, len(lines)):
        line = lines[i]
        if line.startswith("## "):
            break
        if line.startswith("```"):
            fenced = not fenced
            continue
        m = None if fenced else pattern.match(line)
        if m:
            rows.append((i, m.group(1)))
    if not rows:
        raise TakeoverError("no table rows under %r" % heading)
    return rows


def _next_id(ids, prefix):
    width = max(len(i) for i in ids) - len(prefix)
    return "%s%0*d" % (prefix, width, max(int(i[len(prefix):]) for i in ids) + 1)


def _cell(text):
    # A pipe or line break inside a cell would break the markdown table.
    if "|" in text or "\n" in text or "\r" in text:
        raise TakeoverError("table cell may not contain '|' or a line break: %r" % text)
    return text


def plan(log_text, state_path, state_hash, pred, where, name, date, session_id=None):
    """Return (new_log_text, session_row, event_row). Pure; touches no file."""
    newline = "\r\n" if "\r\n" in log_text else "\n"
    lines = log_text.split(newline)
    sessions = _section_rows(lines, SESSIONS_HEADING, _SESSION_ROW)
    events = _section_rows(lines, EVENTS_HEADING, _EVENT_ROW)

    session_ids = [s for _, s in sessions]
    if pred not in session_ids:
        raise TakeoverError("predecessor %s has no row in the log" % pred)
    # Either event type records a succession: E001 is a `handoff`, later takeovers an `ack`.
    successor = re.compile(r"\| (?:ack|handoff) \| %s → (S\d{3,}) \|" % re.escape(pred))
    for i, _ in events:
        m = successor.search(lines[i])
        if m:
            raise TakeoverError("%s already handed over to %s; take over from %s instead"
                                % (pred, m.group(1), m.group(1)))
    sid = session_id or _next_id(session_ids, "S")
    if not _SESSION_ID.match(sid):
        raise TakeoverError("session id must look like S013, got %r" % sid)
    if sid in session_ids:
        raise TakeoverError("session id %s is already taken" % sid)
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        raise TakeoverError("date must be YYYY-MM-DD, got %r" % date)
    eid = _next_id([e for _, e in events], "E")

    session_row = "| %s | %s | claude-code | %s | coordinator | %s | %s | active |" % (
        sid, _cell(name), _cell(where), date, pred)
    event_row = "| %s | %s | ack | %s → %s | read %s · %s | %s |" % (
        eid, date, pred, sid, _cell(str(state_path)), state_hash[:8], sid)

    # Insert bottom-up so the first insert cannot shift the second's index, whichever table is first.
    for index, row in sorted([(sessions[-1][0] + 1, session_row), (events[-1][0] + 1, event_row)],
                             reverse=True):
        lines.insert(index, row)
    return newline.join(lines), session_row, event_row


def _atomic_write(path, text):
    path = pathlib.Path(os.path.realpath(str(path)))  # write through a symlink, never replace it
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pred", required=True, help="previous coordinator's session id, e.g. S002")
    ap.add_argument("--where", required=True, help="machine/user · repo (checkout)")
    ap.add_argument("--name", default="sessions coordinator")
    ap.add_argument("--id", dest="session_id", help="session id (default: next free S number)")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument("--dry-run", action="store_true", help="print the rows, write nothing")
    args = ap.parse_args(argv)

    # Read and decode STATE.md once, before any write: the hash logged is the hash of the text
    # printed, and a decode failure cannot leave rows behind.
    state_bytes = pathlib.Path(args.state).read_bytes()
    state_text = state_bytes.decode("utf-8")
    state_hash = hashlib.sha256(state_bytes).hexdigest()
    log_text = pathlib.Path(args.log).read_bytes().decode("utf-8")
    try:
        new_text, srow, erow = plan(log_text, args.state, state_hash, args.pred, args.where,
                                    args.name, args.date, args.session_id)
    except TakeoverError as e:
        print("coordinator_takeover: refused: %s" % e, file=sys.stderr)
        return 2

    if not args.dry_run:
        _atomic_write(args.log, new_text)

    print("STATE.md sha256: %s" % state_hash)
    print("%s AGENT-LOG.md:" % ("would append to" if args.dry_run else "appended to"))
    print("  " + srow)
    print("  " + erow)
    print("\n" + "=" * 20 + " STATE.md " + "=" * 20)
    sys.stdout.write(state_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
