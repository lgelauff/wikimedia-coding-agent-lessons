"""Print (and optionally write) a status table for every recording in a queue.

Usage: python -m slides_beside_video.status --config config.json --queue queue.csv [--out status.md]
"""
import argparse
import csv
import json
import os
import shutil
import time

from .run import STAGES


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    work = json.load(open(a.config))["work_dir"]
    queue = list(csv.DictReader(open(a.queue, encoding="utf-8")))
    lines = [f"# Status {time.strftime('%Y-%m-%d %H:%M:%S')}", "",
             f"free disk: {shutil.disk_usage(work if os.path.isdir(work) else '.').free / 1e9:.1f} GB", "",
             "| idx | key | final | last stage | pair | share confirmed/audio/visual/unverified | error |",
             "|---|---|---|---|---|---|---|"]
    for q in queue:
        p = os.path.join(work, q["key"], "status.json")
        st = json.load(open(p)) if os.path.exists(p) else {"stages": {}}
        done = [s for s in STAGES if s in st["stages"]]
        pair = st["stages"].get("pair", {}).get("verdict", "")
        sh = st["stages"].get("fuse", {}).get("share")
        share = "/".join(f"{sh.get(k, 0):.0%}" for k in ("confirmed", "audio", "visual", "unverified")) if sh else ""
        lines.append(f"| {q['idx']} | {q['key']} | {st.get('final', '')} | {done[-1] if done else '-'} "
                     f"| {pair} | {share} | {st.get('error', '')[:80]} |")
    text = "\n".join(lines) + "\n"
    if a.out:
        open(a.out, "w").write(text)
    print(text)


if __name__ == "__main__":
    main()
