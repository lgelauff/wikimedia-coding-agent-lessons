"""Run the slides-beside-video pipeline for queued recordings, resuming each from its last finished stage.

Usage:
  python -m slides_beside_video.run --config config.json --queue queue.csv --id 1 [--id 2 ...]
  python -m slides_beside_video.run --config config.json --queue queue.csv --all
Options: --stop-after STAGE  --keep-media  --redo-from {fuse,chrome,chrome-keepclef}  --retry-skipped

Queue CSV columns: idx, key, commons_file, deck_title, decoy_idx (see README). Everything for one recording goes to
<work_dir>/<key>/; one log line per stage; exit code 0 = done or skipped with a recorded reason, 1 = a failure
(details in <work_dir>/<key>/status.json), 3 = another live process holds that recording's lock. Nothing is
uploaded anywhere.

Kill-safe: outputs are written atomically; each stage's done marker in status.json carries the sha256 of its
outputs, checked before a resume (a changed or missing output stops that recording instead of being built on);
downloads and API / vision-model calls are charged to the batch budget (config "budget_file", "budget") before
each attempt, retries included.
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import tarfile
import time
import traceback

from . import wmvid as V

STAGES = ["fetch", "transcript", "ocr", "discover", "pair", "visual", "chrome", "refine", "applause", "candidates",
          "clef", "fuse", "evidence", "render", "review", "sidecar", "cleanup"]
# --redo-from fuse: keep transcript/OCR/visual, recompute the timeline and everything after it
REDO_FILES = {"fuse": ["timeline.json", "evidence.json", "render.json"],
              "chrome": ["chrome.json", "ocr_refined.json", "candidates.json", "applause.json", "timeline.json",
                         "timeline_pre.json", "clef.json", "evidence.json", "render.json", "review/review.json"]}
# like chrome, but keep the vision model's cached answers (same schema; the endpoint is rate-limited)
REDO_FILES["chrome-keepclef"] = [f for f in REDO_FILES["chrome"] if f != "clef.json"]
# The files each stage's done marker checksums. sidecar is rebuilt on every run, so it is recorded, not verified.
STAGE_OUT = {"fetch": ["fetch.json"], "transcript": ["transcript.json"], "ocr": ["ocr.json"],
             "discover": ["discover.json"], "pair": ["pair.json"], "visual": ["visual.json"],
             "chrome": ["chrome.json"], "refine": ["ocr_refined.json"], "applause": ["applause.json"],
             "candidates": ["candidates.json"], "clef": ["clef.json"], "fuse": ["timeline.json"],
             "evidence": ["evidence.json"], "render": ["{key}.mp4", "render.json"], "review": ["review/review.json"],
             "sidecar": ["{key}.sidecar.json", "{key}.evidence.tar"]}
NOT_VERIFIED = {"sidecar"}


def stage_hashes(w, key, stage):
    names = [n.format(key=key) for n in STAGE_OUT.get(stage, [])]
    return {n: V.file_hash(os.path.join(w, n)) for n in names if os.path.isfile(os.path.join(w, n))}


def verify_markers(st, w):
    """Outputs whose checksum no longer matches their done marker (or that are gone)."""
    bad = []
    for stage, m in st.get("stages", {}).items():
        if stage in NOT_VERIFIED:
            continue
        for n, h in (m.get("sha256") or {}).items():
            p = os.path.join(w, n)
            if not os.path.isfile(p):
                bad.append(f"{stage}: {n} missing")
            elif V.file_hash(p) != h:
                bad.append(f"{stage}: {n} changed")
    return bad


def load_config(path):
    cfg = json.load(open(path))
    V.configure(cfg)
    return cfg


def load_queue(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pair_override(overrides_csv, commons_file):
    """A person's per-video decision that the queued deck is the right one: a row in the overrides CSV
    (columns commons_file, decision, reason, who, date) with decision = confirm_pair. Returns the row or None."""
    if not overrides_csv or not os.path.exists(overrides_csv):
        return None
    norm = lambda s: s.replace("File:", "").replace(" ", "_").strip()
    with open(overrides_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("decision") == "confirm_pair" and norm(row.get("commons_file", "")) == norm(commons_file):
                return row
    return None


def run_item(cfg, items, idx, keep_media=False, stop_after=None, redo_from=None, retry_skipped=False):
    work = cfg["work_dir"]
    item = items[idx]
    key = item["key"]
    w = os.path.join(work, key)
    os.makedirs(w, exist_ok=True)
    lock = os.path.join(w, ".lock")
    if not V.take_lock(lock):
        V.log(f"{key}: locked by a live process ({open(lock).read().strip()}); not starting a second one")
        return 3
    try:
        return _run_item(cfg, items, idx, w, key, keep_media, stop_after, redo_from, retry_skipped)
    finally:
        if os.path.exists(lock) and open(lock).read().strip() == str(os.getpid()):
            os.remove(lock)


def _run_item(cfg, items, idx, w, key, keep_media, stop_after, redo_from, retry_skipped):
    work = cfg["work_dir"]
    item = items[idx]
    st_path = os.path.join(w, "status.json")
    st = V.jload(st_path) if os.path.exists(st_path) else {"key": key, "stages": {}}
    if redo_from and st.get("final") == "done":
        for name in REDO_FILES[redo_from] + [f"{key}.mp4", f"{key}.sidecar.json", f"{key}.evidence.tar"]:
            path = os.path.join(w, name)
            if os.path.exists(path):
                if name == "timeline.json" and not os.path.exists(os.path.join(w, "timeline.v1.json")):
                    os.replace(path, os.path.join(w, "timeline.v1.json"))
                elif os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
        for s_ in STAGES[STAGES.index(redo_from.split("-")[0]):]:
            st["stages"].pop(s_, None)
        st.setdefault("history", []).append({"final": st.pop("final"), "redo_from": redo_from})
        V.jdump(st, st_path)
    discover = retry_skipped and st.get("final") == "skipped"
    if discover:                                 # deck pair was not confirmed: look for the deck by content
        st.setdefault("history", []).append({"final": st.pop("final"), "reason": st.pop("reason", "")})
        if os.path.exists(os.path.join(w, "pair.json")):
            os.remove(os.path.join(w, "pair.json"))
        st["stages"].pop("pair", None)
        V.jdump(st, st_path)
    override = pair_override(cfg.get("overrides_csv"), item["commons_file"])
    if st.get("final") == "skipped" and st.get("reason") == "pair not confirmed" and override:
        st.setdefault("history", []).append({"final": st.pop("final"), "reason": st.pop("reason"),
                                             "reopened_by": "overrides confirm_pair"})
        V.jdump(st, st_path)
        V.log(f"{key}: reopened, pair confirmed by override ({override['who']}, {override['date']})")
    if st.get("final") in ("done", "skipped"):
        V.log(f"{key}: already {st['final']}")
        return 0
    bad = verify_markers(st, w)
    if bad:                                      # never build on an output that changed after its stage finished
        st["error"] = "checksum check failed: " + "; ".join(bad)
        V.jdump(st, st_path)
        V.log(f"{key}: FAILED {st['error']} (inspect; then --redo-from, or remove the stage from status.json)")
        return 1
    if "error" in st:
        st.setdefault("previous_errors", []).append(st.pop("error"))
        st.pop("traceback", None)
    b = V.budget()
    V.log(f"{key}: budget {V.BUDGET_FILE}: " + ", ".join(
        f"{k} {b.get(k, 0)}/{V.BUDGET_CAPS.get(k, 'uncapped')}" for k in ("download_bytes", "api_calls", "clef_calls")))
    decoy = items[item["decoy_idx"]]
    decoy_deck = os.path.join(work, decoy["key"], "media", "deck.pdf")
    if not os.path.exists(decoy_deck):          # fetch the decoy deck only (small)
        os.makedirs(os.path.dirname(decoy_deck), exist_ok=True)
        info = V.file_info(decoy["deck_title"])
        V.download(info["url"], decoy_deck, info["size"], sha1=info.get("sha1"))

    def mark(stage, t0, **extra):
        st["stages"][stage] = {"ok": True, "seconds": round(time.time() - t0, 1), **extra,
                               "sha256": stage_hashes(w, key, stage)}
        V.jdump(st, st_path)
        V.log(f"{key}: {stage} ok ({st['stages'][stage]['seconds']} s)")
        return stage == stop_after

    try:
        year = int(key.split("_")[1])
        t0 = time.time(); meta = V.stage_fetch(w, item)
        if mark("fetch", t0, duration_s=meta["duration_s"]): return 0
        t0 = time.time(); tr = V.stage_transcript(w, meta)
        if mark("transcript", t0, source=tr["source"], cues=len(tr["cues"]), failures=tr.get("chunk_failures", 0)): return 0
        t0 = time.time(); ocr = V.stage_ocr(w, meta)
        if mark("ocr", t0, frames=len(ocr["frames"])): return 0
        if meta.get("deck") is None or discover or os.path.exists(os.path.join(w, "discover.json")):
            t0 = time.time(); disc = V.stage_discover(w, meta, year, ocr, tr)
            acc = disc["accepted"]
            if mark("discover", t0, accepted=acc["title"] if acc else None,
                    top=[(c["title"][5:60], c["ocr_hits"], c["spoken_hits"], c["density"])
                         for c in sorted(disc["candidates"], key=lambda c: -c["density"])[:3]]): return 0
            if acc is None:
                if meta.get("deck") is None:
                    st["final"], st["reason"] = "skipped", "no deck found by content"
                    V.jdump(st, st_path)
                    V.log(f"{key}: SKIPPED, no deck found by content")
                    cleanup(w, keep_media)
                    return 0
            elif (meta.get("deck") or {}).get("title") != acc["title"]:
                info = acc.get("info") or V.file_info(acc["title"])
                deck_pdf = os.path.join(w, "media", "deck.pdf")
                shutil.copyfile(acc["path"], deck_pdf + ".part")
                os.replace(deck_pdf + ".part", deck_pdf)
                meta["deck"] = dict(info, path=deck_pdf, found_by="content")
                V.jdump(meta, os.path.join(w, "fetch.json"))
                st["stages"]["fetch"]["sha256"] = stage_hashes(w, key, "fetch")   # fetch.json changed on purpose
                if os.path.exists(os.path.join(w, "pair.json")):
                    os.remove(os.path.join(w, "pair.json"))
                st["stages"].pop("pair", None)
                V.jdump(st, st_path)
        t0 = time.time(); pair = V.stage_pair(w, meta, ocr, tr, decoy_deck)
        if mark("pair", t0, verdict=pair["verdict"], deck=pair["deck"], decoy=pair["decoy"]): return 0
        if pair["verdict"] != "CONFIRMED" and override:   # pair.json keeps the automatic verdict
            pair = dict(pair, override={k: override.get(k) for k in ("decision", "reason", "who", "date")})
            st["pair_override"] = pair["override"]
            V.jdump(st, st_path)
            V.log(f"{key}: pair {pair['verdict']} automatically, continuing on override ({override['who']})")
        elif pair["verdict"] != "CONFIRMED":
            st["final"] = "skipped"
            st["reason"] = "pair not confirmed"
            V.jdump(st, st_path)
            V.log(f"{key}: SKIPPED, pair not confirmed {pair['deck']} vs decoy {pair['decoy']}")
            cleanup(w, keep_media)
            return 0
        t0 = time.time(); vis = V.stage_visual(w, meta)
        if mark("visual", t0, samples=len(vis["samples"])): return 0
        t0 = time.time(); chrome = V.stage_chrome(w, meta, ocr)
        if mark("chrome", t0, browser_frames=sum(1 for v in chrome["scores"].values() if v is not None and v >= 15)): return 0
        t0 = time.time(); ocr = V.stage_ocr_refine(w, meta, ocr)
        if mark("refine", t0, extra_frames=ocr.get("refined_frames", 0)): return 0
        t0 = time.time(); app = stage_applause(w, meta)
        if mark("applause", t0, events=len(app)): return 0
        t0 = time.time(); cand = V.stage_candidates(w, meta, year, ocr)
        if mark("candidates", t0, accepted=[c["title"] for c in cand["accepted"]]): return 0
        pre = V.stage_fuse(w, meta, ocr, vis, tr, extra_decks=cand["accepted"], applause=app, chrome=chrome,
                           out_name="timeline_pre.json")
        t0 = time.time()
        if cfg.get("clef", True):
            cl = V.stage_clef(w, meta, ocr, pre, tr)
        else:
            cl = {"screen": {}, "page": {}, "errors": 0}
        if mark("clef", t0, screen=len(cl["screen"]), page=len(cl["page"]), errors=cl["errors"]): return 0
        t0 = time.time(); tl = V.stage_fuse(w, meta, ocr, vis, tr, extra_decks=cand["accepted"], applause=app,
                                            chrome=chrome, clef=cl)
        if mark("fuse", t0, share=tl["share"], segments=len(tl["segments"])): return 0
        t0 = time.time(); ev = V.stage_evidence(w, key, meta, ocr, tl)
        if mark("evidence", t0, records=len(ev["records"])): return 0
        t0 = time.time(); rd = V.stage_render(w, key, meta, tl)
        if mark("render", t0, **{k: rd.get(k) for k in ("duration_s", "duration_ok", "mb")}): return 0
        t0 = time.time(); rv = V.stage_review(w, key, meta, tl, tr)
        if mark("review", t0, shots=rv["n"]): return 0
        t0 = time.time(); sidecar(w, key, item, meta, tr, pair, tl, ev, rd, cand["accepted"])
        if mark("sidecar", t0): return 0
        t0 = time.time(); cleanup(w, keep_media)
        mark("cleanup", t0)
        st["final"] = "done"
        st["code"] = code_version()
        V.jdump(st, st_path)
        return 0
    except Exception as e:                       # noqa: BLE001
        st["error"] = f"{type(e).__name__}: {e}"
        st["traceback"] = traceback.format_exc()[-3000:]
        V.jdump(st, st_path)
        V.log(f"{key}: FAILED {st['error']}")
        return 1


def stage_applause(w, meta):
    """Applause from the local source (speaker/deck-switch cue); cached as applause.json."""
    out = os.path.join(w, "applause.json")
    if os.path.exists(out):
        return V.jload(out)["events"]
    feats = os.path.join(w, "audio_features.npz")
    if os.path.exists(feats):
        import numpy as np
        z = np.load(feats)
        ev = V.applause_events(None, feats=(z["rms"], z["flat"]))
    else:
        ev = V.applause_events(meta["video"]["path"])
    V.jdump({"events": ev}, out)
    return ev


def sidecar(w, key, item, meta, tr, pair, tl, ev, rd, extra_decks=()):
    """Provenance next to the render: sources and licences, pair verdict, evidence shares, render facts."""
    out = os.path.join(w, f"{key}.sidecar.json")
    code = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wmvid.py"), "rb").read()
    gaps, cur = [], None
    for s in tl["segments"]:
        if s["label"] == "unverified":
            cur = cur or {"from_s": s["start"], "to_s": s["end"]}
            cur["to_s"] = s["end"]
        elif cur:
            if cur["to_s"] - cur["from_s"] >= 180:
                gaps.append(cur)
            cur = None
    if cur and cur["to_s"] - cur["from_s"] >= 180:
        gaps.append(cur)
    strip = {k: v for k, v in meta["video"].items() if k not in ("path",)}
    deck = {k: v for k, v in meta["deck"].items() if k not in ("path",)}
    sc = {
        "title": f"Slides beside video: {item['commons_file'].replace('_', ' ')}",
        "status": "machine-made, not human-checked",
        "sources": {"video": strip, "deck": deck,
                    "extra_decks": [{k: d.get(k) for k in ("title", "author", "license", "license_url", "page_url")}
                                    for d in extra_decks]},
        "deck_share": tl.get("deck_share"),
        "licence_note": "Derived from the Commons files above; reuse under their licences, with attribution "
                        "to their authors. Where either source is CC BY-SA, this derivative is CC BY-SA too.",
        "pair": pair,
        "transcript": {"source": tr["source"], "model": tr.get("model"), "chunk_failures": tr.get("chunk_failures", 0)},
        "evidence_share": tl["share"],
        "evidence_classes": V.LABEL_TEXT,
        "unverified_stretches_over_3min": gaps,
        "evidence_records": len(ev["records"]),
        "render": {k: rd.get(k) for k in ("duration_s", "duration_ok", "mb", "panel_w")},
        "pipeline": {"code": "slides_beside_video/wmvid.py", "sha256": hashlib.sha256(code).hexdigest(),
                     "made": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
    }
    V.jdump(sc, out)
    tar = os.path.join(w, f"{key}.evidence.tar")
    with tarfile.open(tar + ".part", "w") as t:
        t.add(os.path.join(w, "evidence"), arcname=f"{key}_evidence")
        for name in ("timeline.json", "pair.json", "evidence.json", "transcript.json"):
            t.add(os.path.join(w, name), arcname=f"{key}_evidence/{name}")
    os.replace(tar + ".part", tar)
    return sc


def code_version():
    """Short hash of the code a recording was finished with (a run can span code changes)."""
    h = hashlib.sha1()
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("wmvid.py", "clef.py", "run.py"):
        with open(os.path.join(here, name), "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:10]


def cleanup(w, keep_media):
    """Delete the downloaded recording (decks are small and kept)."""
    if keep_media:
        return
    media = os.path.join(w, "media")
    for name in os.listdir(media) if os.path.isdir(media) else []:
        if name not in ("deck.pdf", "cand"):
            p = os.path.join(media, name)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--queue", required=True)
    ap.add_argument("--id", action="append", default=[], help="queue idx to run (repeatable)")
    ap.add_argument("--all", action="store_true", help="run every queue item, in order")
    ap.add_argument("--stop-after", choices=STAGES)
    ap.add_argument("--keep-media", action="store_true")
    ap.add_argument("--redo-from", choices=sorted(REDO_FILES))
    ap.add_argument("--retry-skipped", action="store_true", help="look for the deck by content")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    queue = load_queue(a.queue)
    items = {q["idx"]: q for q in queue}
    ids = [q["idx"] for q in queue] if a.all else a.id
    if not ids:
        ap.error("give --id or --all")
    rc = 0
    for idx in ids:
        rc |= run_item(cfg, items, idx, a.keep_media, a.stop_after, a.redo_from, a.retry_skipped)
    return rc


if __name__ == "__main__":
    sys.exit(main())
