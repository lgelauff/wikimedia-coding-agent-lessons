#!/usr/bin/env python3
"""Agent quality check of the slides-beside-video timelines (whole video, frame + deck page only).

Reads <work_dir>/<talk>/{timeline,fetch,status}.json (never writes there). Writes only under the qc out_dir.
All commands take --config PATH (default config.json).

  qc.py plan [--dense S]           points per talk at a given density
  qc.py prepare TALK [--dense S] [--batch N]
                                    download + sha1 check, frames, page renders, blind batches;
                                    deletes the video afterwards
  qc.py status TALK                 batches done / pending
  qc.py finalize TALK               verdicts -> points.csv, decoys.csv, summary.md; _tmp -> qc/TALK
  qc.py summary                     tables for SUMMARY.md (stdout) + SHA256SUMS

Verdicts are silver (agent). Decoys: points re-paired with a page from another talk's deck.

Kill-safe: prepare builds in _tmp/<talk> and renames items.json last; meta.json holds the sha256 of items.json
and every batch, checked before a prepared talk is reused; finalize writes done.json (sha256 of its outputs)
and renames the folder. A download is charged to the ledger at full size BEFORE curl starts (a kill keeps the
charge), lands as .part, and is renamed only after the sha1 check. prepare holds a pid lock (exit 3 if a live
process has it). Optional config "qc": {"local_media_dir": DIR} copies the video from a local folder instead of
curl (offline tests; same ledger charge and sha1 check).
"""
import csv, glob, hashlib, json, math, os, random, shutil, subprocess, sys, time

import pymupdf
from PIL import Image

QC = WORK = STATE = MEDIA = TMP = UA = None     # set by configure()
CAP_BYTES = 5_000_000_000
EXCLUDE = set()
MIN_FREE_BYTES = 12 * 2 ** 30
LOCAL_MEDIA = None


def configure(cfg):
    """Settings from config.json: work_dir and user_agent (shared with the pipeline) and the "qc" section
    (out_dir, download_cap_gb, exclude)."""
    global QC, WORK, STATE, MEDIA, TMP, UA, CAP_BYTES, EXCLUDE, MIN_FREE_BYTES, LOCAL_MEDIA
    q = cfg.get("qc", {})
    MIN_FREE_BYTES = int(float(cfg.get("min_free_disk_gb", 12)) * 2 ** 30)   # same disk floor as the pipeline
    LOCAL_MEDIA = q.get("local_media_dir")
    WORK = os.path.abspath(cfg["work_dir"])
    QC = os.path.abspath(q.get("out_dir", "qc_out"))
    os.makedirs(QC, exist_ok=True)
    STATE, MEDIA, TMP = (os.path.join(QC, x) for x in ("_state", "_media", "_tmp"))
    UA = cfg["user_agent"]
    CAP_BYTES = int(float(q.get("download_cap_gb", 5)) * 1e9)
    EXCLUDE = set(q.get("exclude", []))


def configure_from_argv(argv):
    """Pop --config PATH (default config.json) from argv and configure."""
    path = "config.json"
    if "--config" in argv:
        i = argv.index("--config")
        path = argv[i + 1]
        del argv[i:i + 2]
    configure(json.load(open(path)))
    return argv
NOSLIDE = {"live_browser", "not_in_deck", "after_talk"}
FRAME_W, PAGE_W, THUMB_W = 960, 800, 300


def jload(p):
    with open(p) as f:
        return json.load(f)


def jdump(o, p):
    tmp = p + ".part"
    with open(tmp, "w") as f:
        json.dump(o, f, indent=1)
    os.replace(tmp, p)


def sha256_of(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def take_lock(path):
    """Exclusive pid lock; a lock left by a killed process (dead pid) is taken over."""
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(open(path).read().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            alive = False
            if pid and pid != os.getpid():
                try:
                    os.kill(pid, 0)
                    alive = True
                except ProcessLookupError:
                    pass
                except PermissionError:
                    alive = True
            if alive:
                return False
            os.remove(path)
            continue
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    return False


def log(msg):
    os.makedirs(STATE, exist_ok=True)
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    with open(os.path.join(STATE, "run.log"), "a") as f:
        f.write(line + "\n")


def talks():
    out = []
    for d in sorted(os.listdir(WORK)):
        st = os.path.join(WORK, d, "status.json")
        if os.path.exists(st) and jload(st).get("final") in ("done", "done-local") and d not in EXCLUDE:
            out.append(d)
    return out


def all_decks():
    """Every finished talk's decks (incl. the excluded talk 13: its deck is a valid decoy source)."""
    res = {}
    for d in sorted(os.listdir(WORK)):
        tl = os.path.join(WORK, d, "timeline.json")
        st = os.path.join(WORK, d, "status.json")
        if os.path.exists(tl) and os.path.exists(st) and jload(st).get("final") in ("done", "done-local"):
            res[d] = jload(tl)["decks"]
    return res


# ---------------------------------------------------------------- points
def state_of(seg):
    return ("none",) if seg["label"] in NOSLIDE else (seg["deck"], seg["page"])


def build_points(talk, dense):
    tl = jload(os.path.join(WORK, talk, "timeline.json"))
    dur = float(tl["duration_s"])
    segs = [s for s in tl["segments"] if s["start"] < dur - 0.5]
    pts = []
    for i, s in enumerate(segs):
        a, b = float(s["start"]), min(float(s["end"]), dur - 0.5)
        L = b - a
        prev_change = i > 0 and state_of(segs[i - 1]) != state_of(s)
        next_change = i + 1 < len(segs) and state_of(segs[i + 1]) != state_of(s)
        cand = []
        if L < 3:
            cand.append(((a + b) / 2, "mid", prev_change or next_change))
        else:
            cand.append((a + 1, "start", prev_change))
            cand.append(((a + b) / 2, "mid", False))
            cand.append((b - 1, "end", next_change))
            if dense:
                t = a + dense
                while t < b - dense / 2:
                    cand.append((t, "dense", False))
                    t += dense
        cand.sort()
        kept = []
        for t, kind, boundary in cand:
            if kept and t - kept[-1][0] < 2.0:
                if boundary:  # boundary points win over a dense neighbour
                    kept[-1] = (t, kind, boundary)
                continue
            kept.append((t, kind, boundary))
        for t, kind, boundary in kept:
            if s["label"] in NOSLIDE:
                stratum = "no_slide"
            elif boundary:
                stratum = "page_change"
            elif s["label"] == "unverified":
                stratum = "low_confidence"
            else:
                stratum = "rest"
            pts.append({"time_s": round(t, 1), "seg": i, "kind": kind, "stratum": stratum,
                        "label": s["label"], "noslide": s["label"] in NOSLIDE,
                        "deck": s["deck"], "page": None if s["label"] in NOSLIDE else s["page"]})
    return pts, tl


def cmd_plan(dense):
    tot = 0
    for t in talks():
        pts, tl = build_points(t, dense)
        n = len(pts)
        tot += n
        by = {}
        for p in pts:
            by[p["stratum"]] = by.get(p["stratum"], 0) + 1
        print(f"{t[:40]:40s} {round(tl['duration_s']):5d}s {n:4d} pts {by}")
    print("TOTAL", tot)


# ---------------------------------------------------------------- download
def ledger():
    p = os.path.join(STATE, "downloads.json")
    return jload(p) if os.path.exists(p) else {"bytes": 0, "files": []}


def sha1_of(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_video(talk):
    meta = jload(os.path.join(WORK, talk, "fetch.json"))["video"]
    url = meta["url"].split("?")[0]
    host = url.split("/")[2]
    assert host in ("upload.wikimedia.org", "commons.wikimedia.org"), host
    os.makedirs(MEDIA, exist_ok=True)
    for old in os.listdir(MEDIA):  # one talk's media at a time
        os.remove(os.path.join(MEDIA, old))
    dst = os.path.join(MEDIA, talk + os.path.splitext(url)[1])
    part = dst + ".part"
    free = shutil.disk_usage(MEDIA).free
    if free < MIN_FREE_BYTES:
        raise SystemExit(f"DISK: {free / 1e9:.1f} GB free, below the {MIN_FREE_BYTES / 2 ** 30:.0f} GiB floor")
    led = ledger()
    if led["bytes"] + meta["size"] > CAP_BYTES:
        raise SystemExit(f"CAP: {led['bytes']} + {meta['size']} would exceed {CAP_BYTES}")
    # charge the full size before the attempt: a download killed mid-way stays counted
    led["bytes"] += meta["size"]
    entry = {"talk": talk, "url": url, "bytes": meta["size"], "expected": meta["size"], "rc": "in flight",
             "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    led["files"].append(entry)
    os.makedirs(STATE, exist_ok=True)
    jdump(led, os.path.join(STATE, "downloads.json"))
    t0 = time.time()
    local = LOCAL_MEDIA
    if local:                                    # offline: same ledger charge and sha1 check, no network
        src = os.path.join(local, os.path.basename(url))
        rc = subprocess.run(["cp", src, part]).returncode
    else:
        rc = subprocess.run(["nice", "-n", "19", "curl", "-sS", "--fail", "-L", "--max-time", "1800",
                             "-A", UA, "-o", part, url]).returncode
    got = os.path.getsize(part) if os.path.exists(part) else 0
    led["bytes"] += min(got, meta["size"]) - meta["size"]      # refund what a failed attempt did not fetch
    entry.update({"bytes": min(got, meta["size"]), "rc": rc, "s": round(time.time() - t0, 1)})
    jdump(led, os.path.join(STATE, "downloads.json"))
    if rc != 0 or got != meta["size"]:
        if os.path.exists(part):
            os.remove(part)
        raise SystemExit(f"download failed rc={rc} got={got}")
    sh = sha1_of(part)
    if sh != meta["sha1"]:
        os.remove(part)
        raise SystemExit(f"sha1 mismatch {sh} != {meta['sha1']}")
    os.replace(part, dst)
    log(f"{talk}: downloaded {got} B in {time.time() - t0:.0f}s, sha1 ok; ledger {led['bytes']} B")
    return dst, sh


# ---------------------------------------------------------------- images
def render_page(pdf, pno, width, out):
    with pymupdf.open(pdf) as doc:
        page = doc[pno - 1]
        z = width / page.rect.width
        pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img.save(out, "JPEG", quality=85)


def contact_sheets(pdf, prefix):
    """Unnumbered thumbnail grids of every page (max 30 per sheet)."""
    outs = []
    with pymupdf.open(pdf) as doc:
        n = len(doc)
        thumbs = []
        for page in doc:
            z = THUMB_W / page.rect.width
            pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
            thumbs.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    for k in range(0, n, 30):
        chunk = thumbs[k:k + 30]
        cols = min(len(chunk), 5 if len(chunk) <= 20 else 6)
        rows = math.ceil(len(chunk) / cols)
        th = max(t.height for t in chunk)
        sheet = Image.new("RGB", (cols * (THUMB_W + 8) + 8, rows * (th + 8) + 8), (128, 128, 128))
        for j, t in enumerate(chunk):
            sheet.paste(t, (8 + (j % cols) * (THUMB_W + 8), 8 + (j // cols) * (th + 8)))
        out = f"{prefix}_{k // 30}.jpg"
        sheet.save(out, "JPEG", quality=85)
        outs.append(out)
    return outs


def extract_frame(video, t, out):
    r = subprocess.run(["nice", "-n", "19", "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                        "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                        "-vf", f"scale='min({FRAME_W},iw)':-2", "-q:v", "3", out])
    return r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0


def hid(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


# ---------------------------------------------------------------- prepare
def cmd_prepare(talk, dense, batch):
    final = os.path.join(QC, talk)
    if os.path.exists(final):
        bad = check_done(final)
        if bad:
            raise SystemExit(f"{talk}: finished folder fails its checksums: {bad}")
        log(f"{talk}: already finished, skip")
        return
    w = os.path.join(TMP, talk)
    if os.path.exists(os.path.join(w, "items.json")):
        bad = check_prepared(w)
        if bad:
            raise SystemExit(f"{talk}: prepared folder fails its checksums: {bad}")
        log(f"{talk}: already prepared, skip")
        return
    os.makedirs(STATE, exist_ok=True)
    lock = os.path.join(STATE, "prepare.lock")
    if not take_lock(lock):
        log(f"{talk}: prepare lock held by a live process ({open(lock).read().strip()}); not starting")
        raise SystemExit(3)
    try:
        _prepare(talk, dense, batch, w)
    finally:
        if os.path.exists(lock) and open(lock).read().strip() == str(os.getpid()):
            os.remove(lock)


def check_prepared(w):
    """Files of a prepared talk that no longer match the checksums in meta.json (old folders: none recorded)."""
    meta = jload(os.path.join(w, "meta.json"))
    sums = meta.get("sha256") or {}
    return [n for n, h in sums.items() if not os.path.isfile(os.path.join(w, n)) or sha256_of(os.path.join(w, n)) != h]


def check_done(final):
    p = os.path.join(final, "done.json")
    if not os.path.exists(p):
        return []                                # finished before done markers existed
    sums = jload(p)["sha256"]
    return [n for n, h in sums.items()
            if not os.path.isfile(os.path.join(final, n)) or sha256_of(os.path.join(final, n)) != h]


def _prepare(talk, dense, batch, w):
    if os.path.exists(w):
        shutil.rmtree(w)
    img = os.path.join(w, "img")
    os.makedirs(img)
    os.makedirs(os.path.join(w, "batches"))
    os.makedirs(os.path.join(w, "verdicts"))
    t_start = time.time()
    pts, tl = build_points(talk, dense)
    decks = tl["decks"]
    rng = random.Random(f"qc-{talk}")

    # decoys: re-pair settled slide points with a page from another talk's deck
    others = {k: v for k, v in all_decks().items() if k != talk}
    pool = [p for p in pts if p["label"] == "confirmed"] or [p for p in pts if not p["noslide"]]
    n_dec = min(len(pool), max(8, round(0.05 * len(pts))))
    dec_src = rng.sample(pool, n_dec)
    decoys = []
    for p in dec_src:
        ot = rng.choice(sorted(others))
        di = rng.randrange(len(others[ot]))
        with pymupdf.open(others[ot][di]) as doc:
            pg = rng.randrange(1, len(doc) + 1)
        decoys.append({**p, "decoy": True, "decoy_talk": ot, "decoy_deck": di, "decoy_page": pg})

    video, sh = fetch_video(talk)
    t_dl = time.time()

    # frames
    times = sorted({p["time_s"] for p in pts})
    fmap = {}
    for t in times:
        out = os.path.join(img, f"f_{hid(talk, 'f', t)}.jpg")
        ok = extract_frame(video, t, out)
        fmap[t] = out if ok else None
    os.remove(video)  # media gone once the points are extracted
    t_fr = time.time()
    bad = [t for t, v in fmap.items() if v is None]
    log(f"{talk}: {len(times)} frames in {t_fr - t_dl:.0f}s ({len(bad)} failed); video deleted")

    # reference images (names carry no page/deck/decoy information)
    rmap = {}

    def ref_page(pdf, pno):
        key = (pdf, pno)
        if key not in rmap:
            out = os.path.join(img, f"r_{hid(talk, pdf, pno)}.jpg")
            render_page(pdf, pno, PAGE_W, out)
            rmap[key] = out
        return rmap[key]

    sheets = []
    for di, pdf in enumerate(decks):
        sheets += contact_sheets(pdf, os.path.join(img, f"s_{hid(talk, 'sheet', di)}"))

    items = []
    for p in pts + decoys:
        fr = fmap[p["time_s"]]
        iid = hid(talk, "item", p["time_s"], p.get("decoy_talk", ""), p.get("decoy_page", ""), p["seg"])
        if p.get("decoy"):
            q, refs = "page", [ref_page(others[p["decoy_talk"]][p["decoy_deck"]], p["decoy_page"])]
        elif p["noslide"]:
            q, refs = "deck", sheets
        else:
            q, refs = "page", [ref_page(decks[p["deck"]], p["page"])]
        items.append({**p, "id": iid, "q": q, "frame": fr, "refs": refs, "decoy": p.get("decoy", False)})
    jdump(items, os.path.join(w, "items.json.part2"))

    judgeable = [it for it in items if it["frame"]]
    rng.shuffle(judgeable)
    nb = math.ceil(len(judgeable) / batch)
    for b in range(nb):
        chunk = judgeable[b * batch:(b + 1) * batch]
        jdump({"talk_code": hid(talk)[:6], "batch": b + 1,
               "items": [{"id": it["id"], "q": it["q"], "frame": it["frame"], "refs": it["refs"]}
                         for it in chunk]},
              os.path.join(w, "batches", f"b{b + 1:03d}.json"))
    sums = {"items.json": sha256_of(os.path.join(w, "items.json.part2"))}
    for b in range(nb):
        n = os.path.join("batches", f"b{b + 1:03d}.json")
        sums[n] = sha256_of(os.path.join(w, n))
    meta = {"talk": talk, "dense_s": dense, "batch": batch, "points": len(pts), "decoys": len(decoys), "sha256": sums,
            "frames": len(times), "frames_failed": len(bad), "batches": nb, "video_sha1": sh,
            "prepare_s": round(time.time() - t_start), "download_s": round(t_dl - t_start),
            "frames_s": round(t_fr - t_dl), "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    jdump(meta, os.path.join(w, "meta.json"))
    os.replace(os.path.join(w, "items.json.part2"), os.path.join(w, "items.json"))
    log(f"{talk}: prepared {len(pts)} points + {len(decoys)} decoys in {nb} batches")


def cmd_status(talk):
    w = os.path.join(TMP, talk)
    bs = sorted(glob.glob(os.path.join(w, "batches", "b*.json")))
    pend, invalid = [], []
    for b in bs:
        v = os.path.join(w, "verdicts", os.path.basename(b))
        if not os.path.exists(v):
            pend.append(os.path.basename(b))
        elif not verdict_ok(b, v):              # a truncated or incomplete verdict file is not done
            pend.append(os.path.basename(b))
            invalid.append(os.path.basename(b))
    print(json.dumps({"batches": len(bs), "pending": pend, "invalid": invalid}))


def verdict_ok(batch_file, verdict_file):
    try:
        got = {a["id"] for a in jload(verdict_file)}
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return {it["id"] for it in jload(batch_file)["items"]} <= got


# ---------------------------------------------------------------- finalize
def verdict_of(it, ans):
    a = (ans or {}).get("answer")
    if a not in ("yes", "no", "unmeasurable"):
        return "unmeasurable", "no valid agent answer"
    if a == "unmeasurable":
        return "unmeasurable", ans.get("reason", "")
    if it["q"] == "page":
        return ("match" if a == "yes" else "no match"), ans.get("reason", "")
    # no-slide point: a deck page on screen contradicts "no slide"
    return ("no match" if a == "yes" else "match"), ans.get("reason", "")


def cmd_finalize(talk):
    w = os.path.join(TMP, talk)
    items = jload(os.path.join(w, "items.json"))
    meta = jload(os.path.join(w, "meta.json"))
    answers = {}
    for vf in sorted(glob.glob(os.path.join(w, "verdicts", "b*.json"))):
        for a in jload(vf):
            answers[a["id"]] = a
    missing = [it["id"] for it in items if it["frame"] and it["id"] not in answers]
    if missing:
        raise SystemExit(f"{len(missing)} items without a verdict; not finalizing")
    rows, drows = [], []
    for it in sorted(items, key=lambda x: (x["time_s"], x["decoy"])):
        if it["frame"] is None:
            v, why, scr = "unmeasurable", "frame extraction failed", ""
        else:
            v, why = verdict_of(it, answers[it["id"]])
            scr = answers[it["id"]].get("screen", "")
        rel = lambda p: os.path.relpath(p, w) if p else ""
        base = {"time_s": it["time_s"],
                "page": "" if it["noslide"] else it["page"],
                "stratum": it["stratum"], "verdict": v, "reason": why.replace("\n", " "),
                "silver": "true", "deck": "" if it["noslide"] else it["deck"] + 1,
                "pipeline_label": it["label"], "point_kind": it["kind"], "segment": it["seg"],
                "screen": scr, "item_id": it["id"], "frame": rel(it["frame"]),
                "ref": ";".join(rel(r) for r in it["refs"])}
        if it["decoy"]:
            base.update({"stratum": "decoy", "decoy_of_stratum": it["stratum"],
                         "decoy_talk": it["decoy_talk"], "decoy_deck": it["decoy_deck"] + 1,
                         "page": it["decoy_page"], "deck": ""})
            drows.append(base)
        else:
            rows.append(base)
    cols = ["time_s", "page", "stratum", "verdict", "reason", "silver", "deck", "pipeline_label",
            "point_kind", "segment", "screen", "item_id", "frame", "ref"]
    with open(os.path.join(w, "points.csv"), "w", newline="") as f:
        cw = csv.DictWriter(f, cols)
        cw.writeheader()
        cw.writerows(rows)
    with open(os.path.join(w, "decoys.csv"), "w", newline="") as f:
        cw = csv.DictWriter(f, cols + ["decoy_of_stratum", "decoy_talk", "decoy_deck"])
        cw.writeheader()
        cw.writerows(drows)
    st = stats(rows, drows)
    meta["finalized_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta["stats"] = st
    jdump(meta, os.path.join(w, "meta.json"))
    write_talk_summary(talk, w, meta, st, rows)
    names = ["points.csv", "decoys.csv", "summary.md", "meta.json", "items.json"]
    names += sorted(os.path.relpath(v, w) for v in glob.glob(os.path.join(w, "verdicts", "b*.json")))
    jdump({"sha256": {n: sha256_of(os.path.join(w, n)) for n in names},
           "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, os.path.join(w, "done.json"))
    os.replace(w, os.path.join(QC, talk))
    log(f"{talk}: finalized ({len(rows)} points, {len(drows)} decoys)")


def tally(rows):
    c = {"match": 0, "no match": 0, "unmeasurable": 0}
    for r in rows:
        c[r["verdict"]] += 1
    m = c["match"] + c["no match"]
    c["n"] = len(rows)
    c["agree"] = round(c["match"] / m, 3) if m else None
    return c


def stats(rows, drows):
    st = {"all": tally(rows), "decoy": tally(drows)}
    for s in ("page_change", "no_slide", "low_confidence", "rest"):
        st[s] = tally([r for r in rows if r["stratum"] == s])
    return st


def fmt(c):
    ag = "–" if c["agree"] is None else f"{100 * c['agree']:.0f} %"
    return f"| {c['n']} | {c['match']} | {c['no match']} | {c['unmeasurable']} | {ag} |"


def write_talk_summary(talk, w, meta, st, rows):
    L = [f"# QC {talk}", "",
         "Silver labels (agent, vision): each point shows only the raw recording frame and the chosen deck page "
         "(or, for no-slide stretches, unnumbered contact sheets of the talk's decks). No label bar, transcript or "
         "confidence colour in the input.", "",
         f"- points: {meta['points']} (frame every {meta['dense_s']} s inside long segments, plus each segment's "
         f"start/middle/end), decoys: {meta['decoys']}",
         f"- video sha1 {meta['video_sha1']} verified, deleted after frame extraction",
         "", "| stratum | n | match | no match | unmeasurable | agreement (match / measurable) |",
         "|---|---|---|---|---|---|"]
    for s in ("page_change", "no_slide", "low_confidence", "rest", "all"):
        L.append(f"| {s} " + fmt(st[s]))
    d = st["decoy"]
    L += ["", f"Decoy control (page from another talk's deck; should be no match): {d['no match']}/{d['n']} no match, "
              f"{d['match']} match (false positive), {d['unmeasurable']} unmeasurable.", "",
          "## Disagreements (no match)", "", "| time | page | stratum | pipeline label | reason |", "|---|---|---|---|---|"]
    for r in rows:
        if r["verdict"] == "no match":
            mm, ss = divmod(int(float(r["time_s"])), 60)
            L.append(f"| {mm:02d}:{ss:02d} | {r['page'] or 'none'} | {r['stratum']} | {r['pipeline_label']} | "
                     f"{r['reason'].replace('|', '/')} |")
    with open(os.path.join(w, "summary.md"), "w") as f:
        f.write("\n".join(L) + "\n")


# ---------------------------------------------------------------- run summary
def cmd_summary():
    out = []
    agg_rows, agg_d = [], []
    for t in talks():
        d = os.path.join(QC, t)
        if not os.path.exists(os.path.join(d, "points.csv")):
            out.append(f"| {t[:2]} | not done |")
            continue
        rows = list(csv.DictReader(open(os.path.join(d, "points.csv"))))
        drows = list(csv.DictReader(open(os.path.join(d, "decoys.csv"))))
        agg_rows += rows
        agg_d += drows
        st = stats(rows, drows)
        a = lambda c: "–" if c["agree"] is None else f"{100 * c['agree']:.0f} %"
        out.append(f"| {t[:2]} | {st['all']['n']} | {st['all']['match']} | {st['all']['no match']} | "
                   f"{st['all']['unmeasurable']} | {a(st['all'])} | {a(st['page_change'])} | {a(st['no_slide'])} | "
                   f"{a(st['low_confidence'])} | {a(st['rest'])} | {st['decoy']['no match']}/{st['decoy']['n']} |")
    print("| talk | points | match | no match | unmeasurable | agreement | page change | no slide | low conf. | rest | decoys no match |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    print("\n".join(out))
    st = stats(agg_rows, agg_d)
    print("\n| stratum | n | match | no match | unmeasurable | agreement |\n|---|---|---|---|---|---|")
    for s in ("page_change", "no_slide", "low_confidence", "rest", "all"):
        print(f"| {s} " + fmt(st[s]))
    print(f"\nDECOY {json.dumps(st['decoy'])}")


def cmd_sums():
    lines = []
    for root, dirs, files in os.walk(QC):
        dirs[:] = sorted(d for d in dirs if d not in ("_tmp", "_media", "__pycache__"))
        for fn in sorted(files):
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, QC)
            if rel == "SHA256SUMS":
                continue
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
            lines.append(f"{h}  {rel}")
    with open(os.path.join(QC, "SHA256SUMS.part"), "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(os.path.join(QC, "SHA256SUMS.part"), os.path.join(QC, "SHA256SUMS"))
    print(f"SHA256SUMS: {len(lines)} files")


if __name__ == "__main__":
    a = configure_from_argv(sys.argv[1:])
    opt = lambda k, d: int(a[a.index(k) + 1]) if k in a else d
    if a[0] == "plan":
        cmd_plan(opt("--dense", 10))
    elif a[0] == "prepare":
        cmd_prepare(a[1], opt("--dense", 10), opt("--batch", 30))
    elif a[0] == "status":
        cmd_status(a[1])
    elif a[0] == "finalize":
        cmd_finalize(a[1])
    elif a[0] == "summary":
        cmd_summary()
    elif a[0] == "sums":
        cmd_sums()
    elif a[0] == "talks":
        print("\n".join(talks()))
