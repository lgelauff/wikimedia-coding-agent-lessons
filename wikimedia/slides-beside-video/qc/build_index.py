#!/usr/bin/env python3
"""Build <out_dir>/index.html: a local overview of a QC run (open it straight from disk).

Usage: python3 build_index.py [--config config.json]
Embeds the per-point data; images and files are linked relatively, so the page must stay in the out_dir.
Reads <work_dir>/<talk>/fetch.json and timeline.json for context (read-only)."""
import csv, glob, html, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qc  # noqa: E402

qc.configure_from_argv(sys.argv[1:])
QC, WORK = qc.QC, qc.WORK
HERE = os.path.dirname(os.path.abspath(__file__))


def rows(p):
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []


second = {(r["talk"], r["item_id"]): r for r in rows(os.path.join(QC, "second_opinion", "second.csv"))}

talks = []
for d in sorted(glob.glob(os.path.join(QC, "[0-9][0-9]_*")) + glob.glob(os.path.join(QC, "tx_[0-9][0-9]_*"))):
    key = os.path.basename(d)
    tx = key.startswith("tx_")
    talk = key[3:] if tx else key
    meta = json.load(open(os.path.join(d, "meta.json")))
    fetch = json.load(open(os.path.join(WORK, talk, "fetch.json")))
    tl = json.load(open(os.path.join(WORK, talk, "timeline.json")))
    decks = [os.path.basename(p) for p in tl["decks"]]
    pts = []
    for kind, fn in (("p", "points.csv"), ("d", "decoys.csv")):
        for r in rows(os.path.join(d, fn)):
            s = second.get((talk, r["item_id"]))
            pts.append({
                "k": kind, "t": float(r["time_s"]), "pg": r["page"], "dk": r["deck"],
                "st": r["stratum"], "v": r["verdict"], "why": r["reason"], "lab": r["pipeline_label"],
                "pk": r["point_kind"], "seg": r["segment"], "scr": r.get("screen", ""), "topic": r.get("topic", ""), "id": r["item_id"],
                "fr": f"{key}/{r['frame']}" if r.get("frame") else "", "words": r.get("words", ""), "ref": [f"{key}/{x}" for x in r["ref"].split(";") if x],
                "dt": (r.get("decoy_talk") or r.get("decoy_source_talk") or "")[:2], "ds": r.get("decoy_of_stratum", ""),
                "dk2": r["stratum"][6:] if r["stratum"].startswith("decoy_") else "",
                "v2": s["second_verdict"] if s else "", "why2": s["second_reason"] if s else "",
            })
    pts.sort(key=lambda x: (x["t"], x["k"]))
    st = meta["stats"]
    talks.append({
        "key": key, "n": ("tx" if tx else "") + talk[:2], "year": talk[3:7],
        "method": "transcript" if tx else "frame", "added": False,
        "title": fetch["video"]["title"].replace("File:", ""),
        "commons": fetch["video"]["page_url"], "deck_pages": [fetch.get("deck", {}).get("page_url", "")],
        "deck_title": fetch.get("deck", {}).get("title", "").replace("File:", ""),
        "decks": decks, "dur": tl["duration_s"], "segments": len(tl["segments"]),
        "bytes": fetch["video"]["size"], "sha1": meta.get("video_sha1", ""), "stats": st, "pts": pts,
    })

files = [(f, d) for f, d in (
    ("SUMMARY.md", "Run summary (write your own)"),
    ("second_opinion/summary.md", "Second judge: agreement and kappa"),
    ("second_opinion/second.csv", "Second judge verdicts per item"),
    ("_state/run.log", "Run log (downloads, frames, finalize)"),
    ("_state/downloads.json", "Download ledger: bytes per file"),
    ("SHA256SUMS", "Checksums over every output file")) if os.path.exists(os.path.join(QC, f))]
sp = os.path.join(QC, "SUMMARY.md")
summary = open(sp).read() if os.path.exists(sp) else ""
data = json.dumps({"talks": talks, "files": files}, separators=(",", ":")).replace("</", "<\\/")

page = open(os.path.join(HERE, "_index_template.html")).read()
page = page.replace("/*DATA*/null", data).replace("<!--SUMMARY-->", html.escape(summary))
with open(os.path.join(QC, "index.html"), "w") as f:
    f.write(page)
print(f"index.html: {len(talks)} talks, {sum(len(t['pts']) for t in talks)} items, {len(page) // 1024} KB")
