#!/usr/bin/env python3
"""Rebuild a recording's timeline from its transcript, for talks where the camera never shows the screen.

  rebuild_timeline.py [--config C] prepare TALK DIR
      writes DIR/{transcript.txt, pages/pNN.png, pages.txt, ASSIGN.md} for an assigning agent
      (run two agents independently: they write DIR/assign_A.json and DIR/assign_B.json)
  rebuild_timeline.py [--config C] compare TALK DIR     per-second agreement A vs B (and A vs the current timeline)
  rebuild_timeline.py [--config C] apply TALK DIR A     write <work>/<TALK>/timeline.json from assign_A.json (the old
                                                        one is kept as timeline.auto.json) and clear the render
                                                        outputs, so the pipeline re-renders on its next run
Labels: transcript_agent (a page) / transcript_none (no slide). The result is silver (agent-made).
"""
import hashlib, json, os, shutil, sys, time

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
NOSLIDE = ("live_browser", "not_in_deck", "after_talk", "transcript_none")


def secs(s):
    m, x = s.split(":")
    return int(m) * 60 + int(x)


def mm(t):
    t = int(t)
    return f"{t // 60:02d}:{t % 60:02d}"


def prepare(w, d):
    os.makedirs(os.path.join(d, "pages"), exist_ok=True)
    cues = json.load(open(os.path.join(w, "transcript.json")))["cues"]
    open(os.path.join(d, "transcript.txt"), "w").write(
        "\n".join(f"[{mm(c[0])}–{mm(c[1])}] {c[-1]}" for c in cues) + "\n")
    fetch = json.load(open(os.path.join(w, "fetch.json")))
    doc = pymupdf.open(fetch["deck"]["path"])
    texts = []
    for i, p in enumerate(doc):
        z = 1000 / p.rect.width
        p.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False).save(os.path.join(d, "pages", f"p{i + 1:02d}.png"))
        texts.append(f"page {i + 1}: " + " ".join(p.get_text().split()))
    open(os.path.join(d, "pages.txt"), "w").write("\n".join(texts) + "\n")
    dur = json.load(open(os.path.join(w, "timeline.json")))["duration_s"]
    tpl = open(os.path.join(HERE, "ASSIGN.md")).read()
    title = fetch["video"]["title"].replace("File:", "").rsplit(".", 1)[0]
    open(os.path.join(d, "ASSIGN.md"), "w").write(
        tpl.replace("{TITLE}", title).replace("{DURATION}", mm(dur)).replace("{PAGES}", str(len(doc))))
    print(f"prepared {d}: {len(cues)} cues, {len(doc)} pages, {mm(dur)}")


def load(d, tag, dur):
    j = json.load(open(os.path.join(d, f"assign_{tag}.json")))
    segs = []
    for s in j["segments"]:
        a, b = secs(s["start"]), min(secs(s["end"]), dur)
        if b > a:
            segs.append({"start": a, "end": b, "page": s.get("page"), "confidence": s.get("confidence", ""),
                         "evidence": s.get("evidence", "")})
    segs[-1]["end"] = dur                       # transcript times are whole seconds; close to the real end
    gaps = [(x["end"], y["start"]) for x, y in zip(segs, segs[1:]) if x["end"] != y["start"]]
    assert segs[0]["start"] == 0 and not gaps, f"assign_{tag}: not contiguous: {gaps[:3]}"
    return segs, j.get("notes", "")


def per_second(segs, dur):
    out = []
    for s in segs:
        out += [s["page"]] * (int(round(s["end"])) - int(s["start"]))
    return out[:int(dur)]


def compare(w, d):
    auto = os.path.join(w, "timeline.auto.json")
    base = json.load(open(auto if os.path.exists(auto) else os.path.join(w, "timeline.json")))
    dur = base["duration_s"]
    a, b = per_second(load(d, "A", dur)[0], dur), per_second(load(d, "B", dur)[0], dur)
    n = min(len(a), len(b))
    cur = per_second([{"start": s["start"], "end": s["end"], "page": None if s["label"] in NOSLIDE else s["page"]}
                      for s in base["segments"]], dur)
    print(json.dumps({"seconds": n, "A_eq_B": round(sum(a[i] == b[i] for i in range(n)) / n, 3),
                      "A_within_1_page_of_B": round(sum(1 for i in range(n) if a[i] and b[i] and abs(a[i] - b[i]) <= 1) / n, 3),
                      "A_eq_current": round(sum(a[i] == cur[i] for i in range(min(n, len(cur)))) / n, 3)}))


def apply(w, d, tag, key):
    path = os.path.join(w, "timeline.json")
    auto = os.path.join(w, "timeline.auto.json")
    if not os.path.exists(auto):
        shutil.copyfile(path, auto)
    base = json.load(open(auto))
    dur = base["duration_s"]
    segs, notes = load(d, tag, dur)
    tl = dict(base)
    tl["segments"] = [{"start": s["start"], "end": s["end"], "deck": 0, "page": s["page"] or 0,
                       "label": "transcript_agent" if s["page"] else "transcript_none",
                       "confidence": s["confidence"], "evidence": s["evidence"]} for s in segs]
    share = {}
    for s in tl["segments"]:
        share[s["label"]] = share.get(s["label"], 0) + (s["end"] - s["start"]) / dur
    tl["share"] = {k: round(v, 3) for k, v in share.items()}
    tl["deck_share"] = {"0": 1.0}
    tl["method"] = (f"Rebuilt from the transcript by an agent (assign_{tag}.json, silver); the automatic timeline is "
                    "kept as timeline.auto.json.")
    tl["rebuilt"] = {"source": f"assign_{tag}.json", "notes": notes, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    dump_atomic(tl, path)
    for name in (f"{key}.mp4", f"{key}.sidecar.json", f"{key}.evidence.tar", "render.json", "evidence.json"):
        if os.path.exists(os.path.join(w, name)):
            os.remove(os.path.join(w, name))
    for name in ("review", "evidence", os.path.join("media", "panels")):
        if os.path.isdir(os.path.join(w, name)):
            shutil.rmtree(os.path.join(w, name))
    st_path = os.path.join(w, "status.json")
    st = json.load(open(st_path))
    st.setdefault("history", []).append({"final": st.pop("final", None), "rebuilt_timeline": tl["rebuilt"]})
    for k in ("evidence", "render", "review", "sidecar", "cleanup"):
        st["stages"].pop(k, None)
    if "sha256" in st["stages"].get("fuse", {}):  # timeline.json changed on purpose: refresh its done marker
        st["stages"]["fuse"]["sha256"] = {"timeline.json": hashlib.sha256(open(path, "rb").read()).hexdigest()}
    dump_atomic(st, st_path)
    print(f"timeline.json rebuilt from assign_{tag}: {len(segs)} segments, share {tl['share']}")


def dump_atomic(obj, path):
    with open(path + ".tmp", "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(path + ".tmp", path)


if __name__ == "__main__":
    a = sys.argv[1:]
    cfg = "config.json"
    if "--config" in a:
        i = a.index("--config")
        cfg = a[i + 1]
        del a[i:i + 2]
    work = json.load(open(cfg))["work_dir"]
    cmd, talk, d = a[0], a[1], a[2]
    w = os.path.join(work, talk)
    if cmd == "prepare":
        prepare(w, d)
    elif cmd == "compare":
        compare(w, d)
    elif cmd == "apply":
        apply(w, d, a[3], talk)
    else:
        sys.exit(__doc__)
