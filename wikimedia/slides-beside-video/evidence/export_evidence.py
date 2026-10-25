#!/usr/bin/env python3
"""Export a processed recording's transcript, OCR and timeline for publication, with a privacy pass.

  export_evidence.py [--config C] review-inputs TALK DIR [--speakers speakers.txt]
      writes DIR/{transcript.txt, ocr.txt, screen_text.txt, speakers.txt} for a privacy reviewer (REDACT.md);
      the reviewer writes DIR/redact.json
  export_evidence.py [--config C] export TALK DIR OUT
      reads DIR/redact.json; writes OUT/{transcript.srt, ocr.json, timeline.json[, timeline_auto.json]} with names
      replaced by [name], private-screen OCR blanked and local paths stripped; prints the number of replacements

TALK is the folder name under work_dir. Nothing is uploaded.
"""
import json, os, re, sys

PRIVATE = "[redacted: private screen]"


def secs(mmss):
    m, s = mmss.split(":")
    return int(m) * 60 + int(s)


def mm(t):
    t = int(t)
    return f"{t // 60:02d}:{t % 60:02d}"


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def review_inputs(work, talk, d, speakers=None):
    w = os.path.join(work, talk)
    os.makedirs(d, exist_ok=True)
    cues = json.load(open(os.path.join(w, "transcript.json")))["cues"]
    open(os.path.join(d, "transcript.txt"), "w").write("\n".join(f"[{mm(c[0])}] {c[-1]}" for c in cues) + "\n")
    frames = json.load(open(os.path.join(w, "ocr_refined.json")))["frames"]
    open(os.path.join(d, "ocr.txt"), "w").write("\n".join(f"[{mm(f['t'])}] " + " ".join(f["tokens"]) for f in frames) + "\n")
    tl = json.load(open(os.path.join(w, "timeline.json")))
    st = [e for e in tl.get("evidence_log", []) if e.get("screen_text")]
    open(os.path.join(d, "screen_text.txt"), "w").write("\n".join(f"[{mm(e['t'])}] {e['screen_text']}" for e in st) + "\n")
    names = open(speakers).read() if speakers else ""
    open(os.path.join(d, "speakers.txt"), "w").write(names)
    print(f"{talk}: {len(cues)} cues, {len(frames)} OCR frames, {len(st)} on-screen texts -> {d}")


def redactor(rv):
    terms = []
    for t in rv.get("terms", []):
        terms += [t["term"]] + list(t.get("variants", []))
    terms = sorted({x for x in terms if x.strip()}, key=len, reverse=True)
    pats = [re.compile(r"(?<!\w)" + re.escape(x) + r"(?!\w)", re.I) for x in terms]
    single = {x.lower() for x in terms if " " not in x}
    windows = [(secs(b["from"]), secs(b["to"])) for b in rv.get("ocr_blank", [])]
    count = {"n": 0}

    def red(s):
        if not isinstance(s, str):
            return s
        new = s
        for p in pats:
            new = p.sub("[name]", new)
        if new != s:
            count["n"] += 1
        return new

    def red_token(t):
        tl = t.lower()
        # OCR tokens are single words; long names (e.g. an e-mail user name) also match as a prefix
        return tl in single or any(len(s) > 6 and tl.startswith(s) for s in single)

    in_win = lambda t: any(a - 15 <= t <= b + 15 for a, b in windows)   # OCR frames are sampled; pad 15 s
    return red, red_token, in_win, count


def walk(o, red):
    if isinstance(o, dict):
        return {k: walk(v, red) for k, v in o.items()}
    if isinstance(o, list):
        return [walk(v, red) for v in o]
    if isinstance(o, str):
        return os.path.basename(o) if os.path.isabs(o) else red(o)   # no local paths in public files
    return o


def export(work, talk, d, out):
    w = os.path.join(work, talk)
    rv = json.load(open(os.path.join(d, "redact.json")))
    red, red_token, in_win, count = redactor(rv)
    os.makedirs(out, exist_ok=True)
    cues = json.load(open(os.path.join(w, "transcript.json")))["cues"]
    srt = []
    for i, c in enumerate(cues, 1):
        srt += [str(i), f"{srt_time(c[0])} --> {srt_time(c[1])}", red(c[-1]), ""]
    open(os.path.join(out, "transcript.srt"), "w", encoding="utf-8").write("\n".join(srt))
    ocr = json.load(open(os.path.join(w, "ocr_refined.json")))
    frames, blanked = [], 0
    for f in ocr["frames"]:
        if in_win(f["t"]):
            frames.append({"t": f["t"], "tokens": [PRIVATE]})
            blanked += 1
            continue
        toks = ["[name]" if red_token(t) else t for t in f["tokens"]]
        count["n"] += toks != f["tokens"]
        frames.append({"t": f["t"], "tokens": toks})
    json.dump({"note": "Tesseract OCR tokens of sampled video frames (pipeline input; noisy). Private screens and "
                       "personal names are redacted.", "every_s": ocr.get("every_s"), "frames": frames},
              open(os.path.join(out, "ocr.json"), "w"), ensure_ascii=False)
    for name in ("timeline.json", "timeline.auto.json"):
        p = os.path.join(w, name)
        if not os.path.exists(p):
            continue
        tl = json.load(open(p))
        for e in tl.get("evidence_log", []):
            if e.get("screen_text") and in_win(e.get("t", -999)):
                e["screen_text"] = PRIVATE
                blanked += 1
        json.dump(walk(tl, red), open(os.path.join(out, name.replace(".auto", "_auto")), "w"), indent=1, ensure_ascii=False)
    print(f"{talk}: {count['n']} replacements, {blanked} private-screen records blanked -> {out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    cfg_path = "config.json"
    if "--config" in a:
        i = a.index("--config")
        cfg_path = a[i + 1]
        del a[i:i + 2]
    work = json.load(open(cfg_path))["work_dir"]
    if a[0] == "review-inputs":
        spk = a[a.index("--speakers") + 1] if "--speakers" in a else None
        review_inputs(work, a[1], a[2], spk)
    elif a[0] == "export":
        export(work, a[1], a[2], a[3])
    else:
        sys.exit(__doc__)
