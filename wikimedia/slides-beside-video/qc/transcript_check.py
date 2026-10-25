#!/usr/bin/env python3
"""Transcript-vs-slide agent check, for talks where the camera never shows the screen (frame QC is unmeasurable).

Same points and strata as qc.py; each judge sees the transcript 20 s before/after the point and the chosen slide.
Two decoys: `cross` (page of another talk's deck) and `near` (another content page of the same deck).
Silver labels, method = transcript; kept apart from the frame+page QC.

  transcript_check.py [--config C] prepare TALK [--dense 10] [--batch 30]   -> <out_dir>/_tmp_tx/TALK/
  transcript_check.py [--config C] finalize TALK                             -> <out_dir>/tx_TALK/
"""
import csv, glob, json, math, os, random, shutil, sys, time

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qc  # noqa: E402

TMP = lambda: os.path.join(qc.QC, "_tmp_tx")
WIN = 20.0


def mm(t):
    t = int(t)
    return f"{t // 60:02d}:{t % 60:02d}"


def words_at(cues, t):
    lines, marked = [], False
    for c in cues:
        a, b, txt = c[0], c[1], c[-1]
        if b < t - WIN or a > t + WIN:
            continue
        if not marked and a > t:
            lines.append(">>> MOMENT <<<")
            marked = True
        lines.append(f"[{mm(a)}] {txt}")
    if not marked:
        lines.append(">>> MOMENT <<<")
    return "\n".join(lines) if len(lines) > 1 else "(no speech in this window)\n>>> MOMENT <<<"


def prepare(talk, dense, batch):
    if os.path.exists(os.path.join(qc.QC, "tx_" + talk)):
        qc.log(f"tx {talk}: already finished, skip")
        return
    w = os.path.join(TMP(), talk)
    if os.path.exists(w):
        shutil.rmtree(w)
    img = os.path.join(w, "img")
    for d in ("img", "batches", "verdicts"):
        os.makedirs(os.path.join(w, d))
    pts, tl = qc.build_points(talk, dense)
    cues = json.load(open(os.path.join(qc.WORK, talk, "transcript.json")))["cues"]
    decks = tl["decks"]
    rng = random.Random(f"tx-{talk}")
    rmap = {}

    def ref_page(pdf, pno):
        if (pdf, pno) not in rmap:
            out = os.path.join(img, f"r_{qc.hid(talk, pdf, pno)}.jpg")
            qc.render_page(pdf, pno, qc.PAGE_W, out)
            rmap[(pdf, pno)] = out
        return rmap[(pdf, pno)]

    sheets = []
    for di, pdf in enumerate(decks):
        sheets += qc.contact_sheets(pdf, os.path.join(img, f"s_{qc.hid(talk, 'sheet', di)}"))

    slide_pts = [p for p in pts if not p["noslide"]]
    others = {k: v for k, v in qc.all_decks().items() if k != talk}
    decoys = []
    for p in rng.sample(slide_pts, min(len(slide_pts), max(8, round(0.05 * len(pts))))):
        ot = rng.choice(sorted(others))
        di = rng.randrange(len(others[ot]))
        with pymupdf.open(others[ot][di]) as doc:
            pg = rng.randrange(1, len(doc) + 1)
        decoys.append({**p, "decoy": "cross", "dpdf": others[ot][di], "dpage": pg, "dsrc": ot[:2]})
    for p in rng.sample(slide_pts, min(len(slide_pts), max(10, round(0.10 * len(pts))))):
        with pymupdf.open(decks[p["deck"]]) as doc:
            content = [i + 1 for i, pg in enumerate(doc) if len(pg.get_text().split()) >= 8 and i + 1 != p["page"]]
        if content:
            decoys.append({**p, "decoy": "near", "dpdf": decks[p["deck"]], "dpage": rng.choice(content), "dsrc": talk[:2]})

    items = []
    for p in pts + decoys:
        iid = qc.hid(talk, "tx", p["time_s"], p.get("decoy", ""), p.get("dpage", ""), p["seg"])
        if p.get("decoy"):
            q, refs = "page", [ref_page(p["dpdf"], p["dpage"])]
        elif p["noslide"]:
            q, refs = "deck", sheets
        else:
            q, refs = "page", [ref_page(decks[p["deck"]], p["page"])]
        items.append({**p, "id": iid, "q": q, "refs": refs, "words": words_at(cues, p["time_s"]),
                      "decoy": p.get("decoy", "")})
    judge = items[:]
    rng.shuffle(judge)
    nb = math.ceil(len(judge) / batch)
    for b in range(nb):
        qc.jdump({"batch": b + 1, "items": [{k: it[k] for k in ("id", "q", "words", "refs")}
                                            for it in judge[b * batch:(b + 1) * batch]]},
                 os.path.join(w, "batches", f"b{b + 1:03d}.json"))
    for it in items:
        it.pop("dpdf", None)
    qc.jdump({"talk": talk, "method": "transcript", "dense_s": dense, "window_s": WIN, "points": len(pts),
              "decoys": len(decoys), "batches": nb, "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
             os.path.join(w, "meta.json"))
    qc.jdump(items, os.path.join(w, "items.json"))
    qc.log(f"tx {talk}: prepared {len(pts)} points + {len(decoys)} decoys in {nb} batches")


def finalize(talk):
    w = os.path.join(TMP(), talk)
    items = json.load(open(os.path.join(w, "items.json")))
    meta = json.load(open(os.path.join(w, "meta.json")))
    ans = {}
    for f in glob.glob(os.path.join(w, "verdicts", "b*.json")):
        for a in json.load(open(f)):
            ans[a["id"]] = a
    miss = [i["id"] for i in items if i["id"] not in ans]
    if miss:
        raise SystemExit(f"{len(miss)} items without a verdict")
    rel = lambda p: os.path.relpath(p, w)
    rows, drows = [], []
    for it in sorted(items, key=lambda x: (x["time_s"], x["decoy"])):
        a = ans[it["id"]]
        v, why = qc.verdict_of(it, a)
        r = {"time_s": it["time_s"], "page": "" if it["noslide"] else it["page"], "stratum": it["stratum"],
             "verdict": v, "reason": why.replace("\n", " "), "silver": "true", "method": "transcript",
             "deck": "" if it["noslide"] else it["deck"] + 1, "pipeline_label": it["label"],
             "point_kind": it["kind"], "segment": it["seg"], "topic": a.get("topic", ""), "item_id": it["id"],
             "ref": ";".join(rel(x) for x in it["refs"]), "words": it["words"].replace("\n", " | ")}
        if it["decoy"]:
            r.update({"stratum": "decoy_" + it["decoy"], "page": it["dpage"], "decoy_of_stratum": it["stratum"],
                      "decoy_source_talk": it["dsrc"]})
            drows.append(r)
        else:
            rows.append(r)
    cols = list(rows[0])
    for name, data, extra in (("points.csv", rows, []), ("decoys.csv", drows, ["decoy_of_stratum", "decoy_source_talk"])):
        with open(os.path.join(w, name), "w", newline="") as f:
            cw = csv.DictWriter(f, cols + extra)
            cw.writeheader()
            cw.writerows(data)
    st = qc.stats(rows, [])
    near = qc.tally([r for r in drows if r["stratum"] == "decoy_near"])
    cross = qc.tally([r for r in drows if r["stratum"] == "decoy_cross"])
    L = [f"# Transcript check {talk}", "",
         "**Method: transcript vs slide (not the frame+page QC).** The camera never shows the screen in this talk, so each "
         "judge saw the automatic transcript from 20 s before to 20 s after the point, and the chosen slide (no-slide "
         "points: contact sheets of the deck). Verdicts are silver. The transcript is Whisper (large-v3-turbo) output.", "",
         f"- points: {meta['points']} (same points as the frame QC: segment start/middle/end, every 10 s, page changes)",
         "", "| stratum | n | match | no match | unmeasurable | agreement |", "|---|---|---|---|---|---|"]
    for s in ("page_change", "no_slide", "low_confidence", "rest", "all"):
        L.append(f"| {s} " + qc.fmt(st[s]))
    L += ["", "Decoys (should be no match):",
          f"- cross (page of another talk's deck): {cross['no match']}/{cross['n']} no match, {cross['match']} match, "
          f"{cross['unmeasurable']} unmeasurable",
          f"- near (another content page of the same deck): {near['no match']}/{near['n']} no match, {near['match']} match, "
          f"{near['unmeasurable']} unmeasurable", "",
          "## Disagreements (no match)", "", "| time | page | stratum | pipeline label | speaker's topic | reason |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        if r["verdict"] == "no match":
            L.append(f"| {mm(float(r['time_s']))} | {r['page'] or 'none'} | {r['stratum']} | {r['pipeline_label']} | "
                     f"{r['topic'].replace('|', '/')} | {r['reason'].replace('|', '/')} |")
    open(os.path.join(w, "summary.md"), "w").write("\n".join(L) + "\n")
    meta.update({"finalized_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "stats": st, "decoy_near": near, "decoy_cross": cross})
    qc.jdump(meta, os.path.join(w, "meta.json"))
    os.replace(w, os.path.join(qc.QC, "tx_" + talk))
    qc.log(f"tx {talk}: finalized ({len(rows)} points, {len(drows)} decoys)")
    print("\n".join(L[:16]))


if __name__ == "__main__":
    a = qc.configure_from_argv(sys.argv[1:])
    opt = lambda k, d: int(a[a.index(k) + 1]) if k in a else d
    {"prepare": lambda: prepare(a[1], opt("--dense", 10), opt("--batch", 30)),
     "finalize": lambda: finalize(a[1])}[a[0]]()
