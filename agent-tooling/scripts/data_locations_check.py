#!/usr/bin/env python3
"""Check the central data-locations record (what is where, and whether each copy counts).

Usage: data_locations_check.py [PATH_TO_TSV] [--today YYYY-MM-DD] [--no-fs] [--registry REGISTRY_JSON ...] [--data-root DIR]
Default TSV: ~/agent/notes/data-locations/DATA-LOCATIONS.tsv  (public-text: ok, documented default, also in AGENTS.md)
Exit 0 = clean (warnings allowed), 1 = errors found, 2 = file missing or unreadable.

Rules (Lodewijk 2026-10-26, see the README next to the TSV):
- a copy counts if status=present and it was verified; drive is never the only copy;
- a toolforge copy counts only with keep_register=yes;
- paper-output, irreplaceable and pii data need two counting copies.
"""
import argparse
import csv
import json
import os
import re
import sys
from datetime import date, datetime

COLUMNS = ["dataset_id", "project", "owner", "what", "class", "location", "path", "bytes",
           "sha256_manifest", "verified_at", "verified_how", "keep_register", "rebuild",
           "status", "updated_at", "updated_by", "note"]
LOCATIONS = {"mac", "drive", "hague", "hf-private", "hf-public", "toolforge", "github", "other"}
CLASSES = {"paper-output", "irreplaceable", "input", "derived", "cache", "pii"}
STATUSES = {"present", "moving", "removed"}
NEEDS_TWO = {"paper-output", "irreplaceable", "pii"}
DRIVE_ROOT = "/Volumes/Research"
STALE_DAYS = 30
MOVING_DAYS = 2
# verified_at means a byte-level check (P017: size checks were once recorded as verification).
# t5_bucket_deposit.py verify downloads every bucket file back and sha256-compares it locally
# (read 2026-11-07, script sha 4912fe40c9a7); its pass line is "BUCKET VERIFIED" (Lodewijk, 2026-11-07).
# t5_cday_ship.py downloads each shard back and sha256-compares it as it ships, then checks the
# manifest; its BUCKET.VERIFIED line reads "N files sha256 OK manifest <sha>" (Lodewijk, 2026-11-08).
BYTE_CHECK = re.compile(r"sha\d*sum|shasum|md5|b3sum|rsync\s+[^;]*--checksum|lfs|\bdiff\b|\bcmp\b"
                        r"|t5_bucket_deposit\.py verify\b[^;]*BUCKET VERIFIED"
                        r"|t5_cday_ship\.py\b[^;]*\d+ files sha256 OK manifest [0-9a-f]{8}", re.I)
DEFAULT_TSV = os.path.expanduser("~/agent/notes/data-locations/DATA-LOCATIONS.tsv")  # public-text: ok (documented default)


def parse_date(text):
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


def byte_checked(row):
    return bool(row["verified_at"]) and bool(BYTE_CHECK.search(row["verified_how"]))


def counts(row):
    """A copy counts: present, verified byte-level, and (toolforge) on the keep register."""
    if row["status"] != "present" or not byte_checked(row) or row.get("_gone"):
        return False
    if row["location"] == "toolforge" and row["keep_register"] != "yes":
        return False
    return True


def check(rows, today, check_fs=True):
    errors, warnings = [], []
    by_id = {}
    for n, row in enumerate(rows, start=2):
        where = "line %d (%s @ %s)" % (n, row.get("dataset_id", "?"), row.get("location", "?"))
        bad = []
        if not row["dataset_id"]:
            bad.append("empty dataset_id")
        if row["location"] not in LOCATIONS:
            bad.append("unknown location %r" % row["location"])
        if row["class"] not in CLASSES:
            bad.append("unknown class %r" % row["class"])
        if row["status"] not in STATUSES:
            bad.append("unknown status %r" % row["status"])
        if row["bytes"] and not row["bytes"].isdigit():
            bad.append("bytes not a whole number: %r" % row["bytes"])
        for col in ("verified_at", "updated_at"):
            if row[col]:
                try:
                    parse_date(row[col])
                except ValueError:
                    bad.append("bad date in %s: %r" % (col, row[col]))
        if row["location"] == "toolforge" and row["keep_register"] not in ("yes", "no"):
            bad.append("toolforge row needs keep_register yes/no")
        if bad:
            errors.append("%s: %s" % (where, "; ".join(bad)))
            continue
        by_id.setdefault(row["dataset_id"], []).append(row)
        if row["verified_at"] and not byte_checked(row):
            errors.append("%s: verified_at set but verified_how names no byte-level check "
                          "(sha256sum -c, shasum -c, md5, rsync --checksum, lfs, diff, cmp, t5_bucket_deposit.py verify … BUCKET VERIFIED, "
                          "t5_cday_ship.py … N files sha256 OK manifest <sha>): %r; "
                          "a size check is not verification, does not count" % (where, row["verified_how"]))

        if row["status"] == "present" and check_fs and row["location"] in ("mac", "drive"):
            link = row["path"].rstrip("/")
            if os.path.islink(link) and not os.path.exists(link):
                # 2026-11-08: 9 laptop "copies" were links into a failing drive (Lodewijk, D-1108-05).
                row["_gone"] = True
                errors.append("%s: path is a broken link (-> %s); it is not a copy" % (where, os.readlink(link)))
            elif not os.path.exists(row["path"]):
                if row["location"] == "drive" and not os.path.isdir(DRIVE_ROOT):
                    warnings.append("%s: drive not mounted, path not checked" % where)
                else:
                    row["_gone"] = True
                    warnings.append("%s: path missing, does not count: %s" % (where, row["path"]))
            elif row["location"] == "mac" and os.path.islink(link) and \
                    os.path.realpath(link).startswith("/Volumes/"):
                warnings.append("%s: mac path is a link to %s; record that location instead"
                                % (where, os.path.realpath(link)))
        if row["status"] == "present":
            if not row["verified_at"]:
                warnings.append("%s: never verified, does not count as a copy" % where)
            elif (today - parse_date(row["verified_at"])).days > STALE_DAYS:
                warnings.append("%s: last verified %s (> %d days)" % (where, row["verified_at"], STALE_DAYS))
        if row["status"] == "moving" and row["updated_at"]:
            if (today - parse_date(row["updated_at"])).days > MOVING_DAYS:
                warnings.append("%s: 'moving' since %s" % (where, row["updated_at"]))

    for ds, ds_rows in sorted(by_id.items()):
        counting = [r for r in ds_rows if counts(r)]
        classes = {r["class"] for r in ds_rows}
        rebuild = any(r["rebuild"] and r["rebuild"] != "none" for r in ds_rows)
        if not any(r["status"] in ("present", "moving") for r in ds_rows):
            continue  # fully retired dataset: history only
        if not counting:
            if classes <= {"cache"} and rebuild:
                continue
            errors.append("%s: no counting copy (present + verified%s)" % (
                ds, "; toolforge needs keep_register=yes" if any(r["location"] == "toolforge" for r in ds_rows) else ""))
            continue
        if {r["location"] for r in counting} == {"drive"}:
            errors.append("%s: only counting copy is on the drive; the drive is never the only copy" % ds)
            continue
        if classes & NEEDS_TWO and len(counting) < 2:
            errors.append("%s: %s needs two counting copies, has %d (%s)" % (
                ds, "/".join(sorted(classes & NEEDS_TWO)), len(counting), counting[0]["location"]))
        elif len(counting) < 2 and not rebuild and classes & {"input", "derived"}:
            warnings.append("%s: single copy (%s) and rebuild=none" % (ds, counting[0]["location"]))
    return errors, warnings


PLAIN_PATH = re.compile(r"^[^*(){}\s+]+$")  # after brace expansion: skip globs and annotated paths
BRACE = re.compile(r"\{([^{}]*,[^{}]*)\}")
NOT_LIVE = ("removed", "partially_removed")  # registry copy fields that mean "no longer all there"


def expand_braces(path):
    """data/{a,b}/x -> [data/a/x, data/b/x] (any number of groups, no nesting)."""
    m = BRACE.search(path)
    if not m:
        return [path]
    out = []
    for alt in m.group(1).split(","):
        out += expand_braces(path[:m.start()] + alt.strip() + path[m.end():])
    return out


def norm(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def repo_root(path):
    """The checkout that holds the data: for a git worktree, its main checkout
    (worktrees hold no gitignored data; WDR-00, 2026-11-08)."""
    d = os.path.dirname(os.path.abspath(path))
    while d != os.path.dirname(d):
        dot_git = os.path.join(d, ".git")
        if os.path.isdir(dot_git):
            return d
        if os.path.isfile(dot_git):
            with open(dot_git, encoding="utf-8") as fh:
                line = fh.read().strip()
            m = re.match(r"gitdir:\s*(.+?)/\.git/worktrees/[^/]+/?$", line)
            return m.group(1) if m else d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.abspath(path))


def registry_check(reg_path, rows, check_fs=True, data_root=None):
    """Cross-check a project registry.json (artifacts with copies[]) against the TSV.

    DATA-LOCATIONS.tsv is the master for where copies are (Lodewijk, 2026-11-08, D-1108-05).
    Flags: a registry artifact with no TSV row (by name or path), and a laptop copy in the
    registry that is a broken link or missing.
    """
    errors, warnings = [], []
    with open(reg_path, encoding="utf-8") as fh:
        arts = json.load(fh).get("artifacts", {})
    root = data_root or repo_root(reg_path)
    ids = {norm(r["dataset_id"].split("/")[-1]) for r in rows}
    tsv_paths = {r["path"].rstrip("/") for r in rows if r["path"].startswith("/")}
    tag = os.path.basename(root)
    unmatched = []
    for key, art in sorted(arts.items()):
        if not isinstance(art, dict) or art.get("status") == "retired":
            continue
        laptop, live = [], []
        for c in art.get("copies") or []:
            if not (isinstance(c, dict) and c.get("host") == "laptop" and isinstance(c.get("path"), str)):
                continue
            # A copy the registry itself marks removed or not usable is history, not a claim.
            claimed = not any(c.get(f) for f in NOT_LIVE) and c.get("status") != "NOT USABLE"
            for one in expand_braces(c["path"]):
                if PLAIN_PATH.match(one):
                    p = (one if one.startswith("/") else os.path.join(root, one)).rstrip("/")
                    laptop.append(p)
                    if claimed:
                        live.append(p)
        if check_fs:
            for p in live:
                if os.path.islink(p) and not os.path.exists(p):
                    errors.append("registry %s %s: laptop copy is a broken link (%s -> %s); it is not a copy"
                                  % (tag, key, os.path.relpath(p, root), os.readlink(p)))
                elif not os.path.lexists(p):
                    warnings.append("registry %s %s: laptop copy listed but missing: %s"
                                    % (tag, key, os.path.relpath(p, root)))
        folder = art.get("folder") if isinstance(art.get("folder"), str) else ""
        candidates = set(laptop) | ({folder.rstrip("/")} if folder.startswith("/") else set())
        if norm(key) not in ids and not candidates & tsv_paths:
            unmatched.append(key)
    if unmatched:
        # One line, so the per-copy errors above stay visible.
        warnings.append("registry %s: %d artifacts have no DATA-LOCATIONS row (by name or path): %s"
                        % (tag, len(unmatched), ", ".join(unmatched)))
    return errors, warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tsv", nargs="?", default=DEFAULT_TSV)
    ap.add_argument("--today", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--no-fs", action="store_true", help="skip path-exists checks")
    ap.add_argument("--registry", action="append", default=[], metavar="REGISTRY_JSON",
                    help="also cross-check a project registry.json against the TSV (repeatable)")
    ap.add_argument("--data-root", help="checkout that holds the registry's data "
                    "(default: the registry's git checkout, or the main one for a worktree)")
    args = ap.parse_args(argv)
    today = parse_date(args.today) if args.today else date.today()
    try:
        with open(args.tsv, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
            if reader.fieldnames != COLUMNS:
                print("ERROR: header does not match the README columns: %s" % reader.fieldnames)
                return 2
            rows = [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in reader]
    except OSError as exc:
        print("ERROR: cannot read %s: %s" % (args.tsv, exc))
        return 2
    errors, warnings = check(rows, today, check_fs=not args.no_fs)
    for reg in args.registry:
        try:
            e, w = registry_check(reg, rows, check_fs=not args.no_fs, data_root=args.data_root)
        except (OSError, ValueError) as exc:
            print("ERROR: cannot read registry %s: %s" % (reg, exc))
            return 2
        errors += e
        warnings += w
    datasets = len({r["dataset_id"] for r in rows})
    print("%d rows, %d datasets: %d errors, %d warnings" % (len(rows), datasets, len(errors), len(warnings)))
    for e in errors:
        print("ERROR " + e)
    for w in warnings:
        print("WARN  " + w)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
