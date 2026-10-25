#!/usr/bin/env python3
"""List figure files across one or more checkouts, deduplicated by path relative to each checkout.

Read-only. Output (TSV on stdout): relpath, newest_checkout, file_time (YYYY-MM-DD), bytes, all_checkouts, abs_path.

Example:
  python3 inventory.py --root main=/path/repo --root WT=/path/repo/.claude/worktrees/x \
      --since 2026-09-01 --keep 'analysis/hy13|analysis/section_model|^\\.claude/(?!rescue)' > inventory.tsv
"""
import argparse
import os
import re
import sys
import time

EXT = ('.png', '.svg', '.pdf')
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', 'site-packages', '.venv', 'venv'}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', action='append', required=True, help='NAME=PATH of a checkout; repeatable')
    ap.add_argument('--since', help='only files modified on/after this date (YYYY-MM-DD)')
    ap.add_argument('--keep', help='regex on the relative path; only matching files are listed')
    ap.add_argument('--drop', help='regex on the relative path; matching files are excluded')
    a = ap.parse_args()

    roots = dict(r.split('=', 1) for r in a.root)
    # nested checkouts (worktrees under the main repo) are walked as their own root, not as part of the parent
    nested = {os.path.realpath(p) for p in roots.values()}
    since = time.mktime(time.strptime(a.since, '%Y-%m-%d')) if a.since else 0
    keep = re.compile(a.keep) if a.keep else None
    drop = re.compile(a.drop) if a.drop else None

    seen = {}
    for name, root in roots.items():
        rroot = os.path.realpath(root)
        for dp, dns, fns in os.walk(rroot):
            dns[:] = [d for d in dns if d not in SKIP_DIRS and os.path.realpath(os.path.join(dp, d)) not in nested - {rroot}]
            for fn in fns:
                if not fn.lower().endswith(EXT):
                    continue
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, rroot)
                if keep and not keep.search(rel):
                    continue
                if drop and drop.search(rel):
                    continue
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if st.st_mtime < since:
                    continue
                seen.setdefault(rel, []).append((name, st.st_mtime, st.st_size, p))

    w = sys.stdout.write
    for rel in sorted(seen):
        v = sorted(seen[rel], key=lambda x: -x[1])
        name, mt, size, p = v[0]
        w(f"{rel}\t{name}\t{time.strftime('%Y-%m-%d', time.localtime(mt))}\t{size}\t{','.join(x[0] for x in v)}\t{p}\n")


if __name__ == '__main__':
    main()
