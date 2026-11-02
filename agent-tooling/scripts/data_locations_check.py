#!/usr/bin/env python3
"""Check the central data-locations record (what is where, and whether each copy counts).

Usage: data_locations_check.py [PATH_TO_TSV] [--today YYYY-MM-DD] [--no-fs]
Default TSV: ~/agent/notes/data-locations/DATA-LOCATIONS.tsv  (public-text: ok, documented default, also in AGENTS.md)
Exit 0 = clean (warnings allowed), 1 = errors found, 2 = file missing or unreadable.

Rules (Lodewijk 2026-10-26, see the README next to the TSV):
- a copy counts if status=present and it was verified; drive is never the only copy;
- a toolforge copy counts only with keep_register=yes;
- paper-output, irreplaceable and pii data need two counting copies.
"""
import argparse
import csv
import os
import re
import sys
from datetime import date, datetime

COLUMNS = ["dataset_id", "project", "owner", "what", "class", "location", "path", "bytes",
           "sha256_manifest", "verified_at", "verified_how", "keep_register", "rebuild",
           "status", "updated_at", "updated_by", "note"]
LOCATIONS = {"mac", "drive", "hague", "hf-private", "toolforge", "github", "other"}
CLASSES = {"paper-output", "irreplaceable", "input", "derived", "cache", "pii"}
STATUSES = {"present", "moving", "removed"}
NEEDS_TWO = {"paper-output", "irreplaceable", "pii"}
DRIVE_ROOT = "/Volumes/Research"
STALE_DAYS = 30
MOVING_DAYS = 2
# verified_at means a byte-level check (P017: size checks were once recorded as verification).
BYTE_CHECK = re.compile(r"sha\d*sum|shasum|md5|b3sum|rsync\s+[^;]*--checksum|lfs|\bdiff\b|\bcmp\b", re.I)
DEFAULT_TSV = os.path.expanduser("~/agent/notes/data-locations/DATA-LOCATIONS.tsv")  # public-text: ok (documented default)


def parse_date(text):
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


def byte_checked(row):
    return bool(row["verified_at"]) and bool(BYTE_CHECK.search(row["verified_how"]))


def counts(row):
    """A copy counts: present, verified byte-level, and (toolforge) on the keep register."""
    if row["status"] != "present" or not byte_checked(row):
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
                          "(sha256sum -c, shasum -c, md5, rsync --checksum, lfs, diff, cmp): %r; "
                          "a size check is not verification, does not count" % (where, row["verified_how"]))

        if row["status"] == "present" and check_fs and row["location"] in ("mac", "drive"):
            if not os.path.exists(row["path"]):
                if row["location"] == "drive" and not os.path.isdir(DRIVE_ROOT):
                    warnings.append("%s: drive not mounted, path not checked" % where)
                else:
                    warnings.append("%s: path missing: %s" % (where, row["path"]))
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tsv", nargs="?", default=DEFAULT_TSV)
    ap.add_argument("--today", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--no-fs", action="store_true", help="skip path-exists checks")
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
    datasets = len({r["dataset_id"] for r in rows})
    print("%d rows, %d datasets: %d errors, %d warnings" % (len(rows), datasets, len(errors), len(warnings)))
    for e in errors:
        print("ERROR " + e)
    for w in warnings:
        print("WARN  " + w)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
