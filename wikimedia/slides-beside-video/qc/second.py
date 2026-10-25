#!/usr/bin/env python3
"""Second, independent agent judgement on a subset of finished talks' points (inter-judge agreement).

Subset per talk: every `no match` point, a random 10 % (min 5) of `match`, a random 5 % (min 2) of
`unmeasurable`. Same JUDGE.md, same blind inputs, new shuffled batches. Second judges never see the
first verdict.

  second.py [--config C] build      -> <out_dir>/_second/batches/bNNN.json, items.json
  second.py [--config C] finalize   -> <out_dir>/second_opinion/{second.csv, summary.md}
"""
import csv, glob, json, math, os, random, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qc  # noqa: E402

QC = W = OUT = None      # set from the config in main
ANS_OF = {("page", "match"): "yes", ("page", "no match"): "no",
          ("deck", "match"): "no", ("deck", "no match"): "yes"}


def finished():
    return sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(QC, "*", "points.csv"))
                  if not os.path.basename(os.path.dirname(p)).startswith(("_", "second", "tx_")))


def build(batch=30):
    if os.path.exists(os.path.join(W, "items.json")):
        print("already built")
        return
    os.makedirs(os.path.join(W, "batches"), exist_ok=True)
    os.makedirs(os.path.join(W, "verdicts"), exist_ok=True)
    rng = random.Random("qc-second")
    items = []
    for t in finished():
        d = os.path.join(QC, t)
        rows = list(csv.DictReader(open(os.path.join(d, "points.csv"))))
        by = {v: [r for r in rows if r["verdict"] == v] for v in ("match", "no match", "unmeasurable")}
        pick = by["no match"][:]
        pick += rng.sample(by["match"], min(len(by["match"]), max(5, round(0.10 * len(by["match"])))))
        pick += rng.sample(by["unmeasurable"], min(len(by["unmeasurable"]), max(2, round(0.05 * len(by["unmeasurable"])))))
        for r in pick:
            q = "deck" if r["stratum"] == "no_slide" else "page"
            items.append({"id": "s" + r["item_id"], "talk": t, "item_id": r["item_id"], "q": q,
                          "frame": os.path.join(d, r["frame"]),
                          "refs": [os.path.join(d, x) for x in r["ref"].split(";")],
                          "first_verdict": r["verdict"], "stratum": r["stratum"]})
    rng.shuffle(items)
    nb = math.ceil(len(items) / batch)
    for b in range(nb):
        chunk = items[b * batch:(b + 1) * batch]
        json.dump({"batch": b + 1, "items": [{k: it[k] for k in ("id", "q", "frame", "refs")} for it in chunk]},
                  open(os.path.join(W, "batches", f"b{b + 1:03d}.json"), "w"), indent=1)
    json.dump(items, open(os.path.join(W, "items.json"), "w"), indent=1)
    print(f"{len(items)} items in {nb} batches; first verdicts: {Counter(i['first_verdict'] for i in items)}")


def verdict(q, a):
    if a == "unmeasurable" or a not in ("yes", "no"):
        return "unmeasurable"
    if q == "page":
        return "match" if a == "yes" else "no match"
    return "no match" if a == "yes" else "match"


def kappa(pairs):
    cats = ("match", "no match", "unmeasurable")
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[c] * cb[c] for c in cats) / n / n
    return None if pe == 1 else round((po - pe) / (1 - pe), 3)


def finalize():
    items = json.load(open(os.path.join(W, "items.json")))
    ans = {}
    for f in glob.glob(os.path.join(W, "verdicts", "b*.json")):
        for a in json.load(open(f)):
            ans[a["id"]] = a
    miss = [i["id"] for i in items if i["id"] not in ans]
    if miss:
        raise SystemExit(f"{len(miss)} items without a second verdict")
    rows = []
    for it in items:
        a = ans[it["id"]]
        rows.append({"talk": it["talk"], "item_id": it["item_id"], "stratum": it["stratum"],
                     "first_verdict": it["first_verdict"], "second_verdict": verdict(it["q"], a.get("answer")),
                     "second_screen": a.get("screen", ""), "second_reason": a.get("reason", "").replace("\n", " "),
                     "silver": "true"})
    rows.sort(key=lambda r: (r["talk"], r["item_id"]))
    os.makedirs(W, exist_ok=True)
    with open(os.path.join(W, "second.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    L = ["# Second judge (inter-agent agreement)", "",
         "A second, independent agent judged a subset with the same blind inputs and instructions: every point the "
         "first judge called `no match`, a random 10 % of `match`, a random 5 % of `unmeasurable`. Both are silver. "
         "The subset is enriched for disagreements, so the agreement below is NOT a talk-level accuracy.", "",
         "| first verdict | n | second: match | second: no match | second: unmeasurable | same |", "|---|---|---|---|---|---|"]
    for fv in ("no match", "match", "unmeasurable"):
        sub = [r for r in rows if r["first_verdict"] == fv]
        c = Counter(r["second_verdict"] for r in sub)
        same = sum(r["second_verdict"] == fv for r in sub)
        L.append(f"| {fv} | {len(sub)} | {c['match']} | {c['no match']} | {c['unmeasurable']} | "
                 f"{same} ({100 * same / len(sub):.0f} %) |" if sub else f"| {fv} | 0 | | | | |")
    k = kappa([(r["first_verdict"], r["second_verdict"]) for r in rows])
    L += ["", f"Cohen's kappa over the whole subset (3 categories): {k}", "",
          "## Per talk: share of first-judge `no match` that the second judge also calls `no match`", "",
          "| talk | first no match | confirmed | second says match | second says unmeasurable |", "|---|---|---|---|---|"]
    for t in sorted({r["talk"] for r in rows}):
        sub = [r for r in rows if r["talk"] == t and r["first_verdict"] == "no match"]
        c = Counter(r["second_verdict"] for r in sub)
        L.append(f"| {t[:2]} | {len(sub)} | {c['no match']} | {c['match']} | {c['unmeasurable']} |")
    open(os.path.join(W, "summary.md"), "w").write("\n".join(L) + "\n")
    for p in ("batches", "verdicts"):  # keep provenance
        pass
    os.replace(W, OUT)
    print("\n".join(L))


if __name__ == "__main__":
    args = qc.configure_from_argv(sys.argv[1:])
    QC = qc.QC
    W = os.path.join(QC, "_second")
    OUT = os.path.join(QC, "second_opinion")
    {"build": build, "finalize": finalize}[args[0]]()
