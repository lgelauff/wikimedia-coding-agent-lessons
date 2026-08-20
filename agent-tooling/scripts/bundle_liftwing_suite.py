#!/usr/bin/env python3
"""Pack liftwing_suite.py + its gold data into ONE standalone file.

Toolforge gets a single upload with no repo checkout, no pip install, and no
second sync: the gold CSVs travel inside the script as a zlib+base64 blob.

  bundle_liftwing_suite.py [-o liftwing_suite_standalone.py]

Verifies the result imports and can read its own embedded data before writing.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "liftwing_suite.py")
LOCAL = os.path.expanduser("~/Documents/GitHub/wikimedia-analysis/"
                           "wikipedia-policy-change/data/exploration")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=os.path.join(HERE, "liftwing_suite_standalone.py"))
    ap.add_argument("--data", default=LOCAL)
    args = ap.parse_args()

    sys.path.insert(0, HERE)
    from liftwing_suite import DATA_FILES

    payload, missing = {}, []
    for rel in DATA_FILES:
        p = os.path.join(args.data, rel)
        if not os.path.exists(p):
            missing.append(rel)
            continue
        with open(p, encoding="utf-8") as fh:
            payload[rel] = fh.read()
    if missing:
        sys.exit(f"missing gold data, cannot bundle:\n  " + "\n  ".join(missing))

    blob = base64.b64encode(
        zlib.compress(json.dumps(payload).encode(), 9)).decode()

    with open(SRC, encoding="utf-8") as fh:
        src = fh.read()
    marker = '_DATA_BLOB = ""'
    if marker not in src:
        sys.exit("bundler is out of sync with liftwing_suite.py (no _DATA_BLOB)")
    out = src.replace(marker, f'_DATA_BLOB = "{blob}"', 1)

    # Prove the bundle stands alone before handing it over: run it from a temp
    # dir with no access to the repo or the gold data.
    with tempfile.TemporaryDirectory() as td:
        probe = os.path.join(td, "probe.py")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write(out)
        check = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r); import probe; "
             "print(len(probe.statements()), len(probe.rows("
             "'runs/align_de_en_npov_review.csv')))" % td],
            capture_output=True, text=True, cwd=td, env={**os.environ, "HOME": td})
        if check.returncode != 0:
            sys.exit(f"bundle self-test FAILED:\n{check.stderr[-1500:]}")
        n_stmt, n_align = check.stdout.split()

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(out)
    os.chmod(args.out, 0o755)

    size = os.path.getsize(args.out)
    digest = hashlib.sha256(out.encode()).hexdigest()[:16]
    print(f"wrote {args.out}")
    print(f"  {len(payload)} data files embedded, {size/1024:.0f} KB total")
    print(f"  self-test passed with HOME unset: {n_stmt} gold statements, "
          f"{n_align} alignment rows readable")
    print(f"  sha256: {digest}")
    # Absolute path, no user@ placeholder: the last hand-off failed because a
    # copy-pasteable block contained both.
    print(f"\nUpload once:\n  scp {os.path.abspath(args.out)} login.toolforge.org:~/")


if __name__ == "__main__":
    sys.exit(main())
