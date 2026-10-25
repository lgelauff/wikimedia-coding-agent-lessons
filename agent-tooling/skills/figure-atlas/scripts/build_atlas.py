#!/usr/bin/env python3
"""Build a figure-atlas page (index.html + figs/) ready to publish as one Artifact.

Inputs
  --atlas atlas.json   {"title": ..., "lede": ..., "footer": ...,
                        "groups": [{"id": "F1-mechanism", "title": "Fig. 1 · ...", "where": "Background", "intro": "..."}],
                        "status": {"REBUILT": ["ok", "Rebuilt 24 Oct"], ...},          (optional; defaults below)
                        "caveats": {"file.png": "Stamped preliminary."}}                  (optional)
  --figures figures.tsv  group_id, filename, status, abs_path   (one row per figure to show; header optional)
  --captions captions.tsv group_id, filename, caption            (optional; header optional)
  --out DIR             written fresh: DIR/index.html and DIR/figs/<group>/<file>

Copies figures (never moves them). SVG copies get any <!DOCTYPE> line removed, because Artifact publishing refuses
XML supporting files with DTD declarations. Prints the publish `files` list as JSON on stdout.
"""
import argparse
import html
import json
import os
import re
import shutil

DEFAULT_STATUS = {
    'REBUILT': ['ok', 'Rebuilt'],
    'REBUILT-DIFFERS-VISIBLY': ['warn', 'Rebuilt, differs'],
    'FAILED': ['off', 'Rebuild failed'],
    'SKIPPED-HEAVY': ['off', 'Not rebuilt: too heavy'],
    'SKIPPED-INPUT-DELETED': ['off', 'Not rebuilt: input deleted'],
    'SKIPPED-INPUT-MISSING': ['off', 'Not rebuilt: input missing'],
    'SKIPPED-NO-SCRIPT': ['off', 'Not rebuilt: no script'],
    'SKIPPED-NOT-A-BUILT-FIGURE': ['off', 'Screenshot'],
    'COPIED': ['off', 'Copy, not rebuilt'],
}


def read_tsv(path, ncols):
    rows = []
    if not path or not os.path.exists(path):
        return rows
    for line in open(path, encoding='utf8').read().splitlines():
        c = line.split('\t')
        if len(c) >= ncols and c[0] not in ('slot', 'group', 'group_id'):
            rows.append(c)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--atlas', required=True)
    ap.add_argument('--figures', required=True)
    ap.add_argument('--captions')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    cfg = json.load(open(a.atlas, encoding='utf8'))
    status_map = {**DEFAULT_STATUS, **cfg.get('status', {})}
    caveats = cfg.get('caveats', {})
    groups = cfg['groups']
    caps = {(r[0], r[1]): r[2] for r in read_tsv(a.captions, 3)}
    figs = read_tsv(a.figures, 4)

    if os.path.exists(a.out):
        shutil.rmtree(a.out)
    os.makedirs(a.out)
    by, files = {}, []
    known = {g['id'] for g in groups}
    skipped = sorted({r[0] for r in figs if r[0] not in known})
    if skipped:
        import sys
        print(f'warning: groups not in atlas.json, their figures are left out: {", ".join(skipped)}', file=sys.stderr)
    for gid, name, status, src in (r[:4] for r in figs if r[0] in known):
        rel = f'figs/{gid}/{name}'
        dst = os.path.join(a.out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if name.lower().endswith('.svg'):
            s = open(src, encoding='utf8').read()
            open(dst, 'w', encoding='utf8').write(re.sub(r'<!DOCTYPE[^>]*>\s*', '', s, flags=re.S))
        else:
            shutil.copy2(src, dst)
        by.setdefault(gid, []).append((name, status, rel))
        files.append({'path': rel})

    e = html.escape
    present = [g for g in groups if g['id'] in by]
    nav = ''.join(f'<a href="#{e(g["id"])}">{e(g["title"].split(" · ")[0])}</a>' for g in present)
    secs = []
    for g in present:
        cards = []
        for name, status, rel in by[g['id']]:
            cls, lab = status_map.get(status, ['off', status])
            cap = caps.get((g['id'], name), '')
            cav = caveats.get(name, '')
            cards.append(
                f'<figure class="card"><a class="shot" href="{rel}" target="_blank" rel="noopener">'
                f'<img src="{rel}" alt="{e(cap or name)}" loading="lazy"></a><figcaption>'
                f'<div class="meta"><code>{e(name)}</code><span class="pill {cls}">{e(lab)}</span></div>'
                + (f'<p>{e(cap)}</p>' if cap else '') + (f'<p class="cav">{e(cav)}</p>' if cav else '')
                + '</figcaption></figure>')
        secs.append(f'<section id="{e(g["id"])}"><header class="sh"><span class="where">{e(g.get("where", ""))}</span>'
                    f'<h2>{e(g["title"])}</h2><p>{e(g.get("intro", ""))}</p></header><div class="grid">{"".join(cards)}</div></section>')

    page = TEMPLATE.format(title=e(cfg.get('title', 'Figure atlas')), lede=e(cfg.get('lede', '')),
                           footer=e(cfg.get('footer', '')), nav=nav, sections=''.join(secs))
    open(os.path.join(a.out, 'index.html'), 'w', encoding='utf8').write(page)
    print(json.dumps(files))


TEMPLATE = '''<title>{title}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono&display=swap">
<style>
/* Layout: one reading column of sections; each a short explanation above a responsive grid of figure cards; group chips stick to the top. */
:root {{ --bg:#f6f7f9; --panel:#fff; --ink:#1c2330; --muted:#5a6475; --line:#dde2ea; --accent:#2457a6;
  --ok:#1f7a4d; --ok-bg:#e3f3ea; --warn:#8a5a00; --warn-bg:#fbf0d9; --off:#5a6475; --off-bg:#eceff4;
  --display:"Fraunces",Georgia,serif; --body:"Source Sans 3","Segoe UI",system-ui,sans-serif; --mono:"JetBrains Mono",ui-monospace,Menlo,monospace; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#12161d; --panel:#1a202a; --ink:#e6e9ef; --muted:#9aa4b5; --line:#2b3340; --accent:#7fa8ea;
  --ok:#7fd3a6; --ok-bg:#173126; --warn:#f0c46b; --warn-bg:#3a2e14; --off:#a3acbb; --off-bg:#232a35; color-scheme:dark; }} }}
:root[data-theme="dark"] {{ --bg:#12161d; --panel:#1a202a; --ink:#e6e9ef; --muted:#9aa4b5; --line:#2b3340; --accent:#7fa8ea;
  --ok:#7fd3a6; --ok-bg:#173126; --warn:#f0c46b; --warn-bg:#3a2e14; --off:#a3acbb; --off-bg:#232a35; color-scheme:dark; }}
body {{ background:var(--bg); color:var(--ink); font:16px/1.55 var(--body); }}
.wrap {{ max-width:1180px; margin:0 auto; padding-left:max(16px, env(safe-area-inset-left, 0px)); padding-right:max(16px, env(safe-area-inset-right, 0px)); padding-block:32px 64px; }}
h1,h2 {{ font-family:var(--display); font-weight:600; text-wrap:balance; margin:0; }}
h1 {{ font-size:clamp(1.8rem,4vw,2.6rem); line-height:1.15; }} h2 {{ font-size:1.45rem; line-height:1.25; }}
.lede {{ max-width:68ch; color:var(--muted); margin:12px 0 0; }}
.legend {{ display:flex; flex-wrap:wrap; gap:8px 16px; margin-top:16px; font-size:.9rem; color:var(--muted); }}
nav {{ position:sticky; top:env(safe-area-inset-top, 0px); z-index:5; background:var(--bg); border-bottom:1px solid var(--line); margin-top:24px; }}
body::before {{ content:""; position:fixed; inset:0 0 auto; height:env(safe-area-inset-top, 0px); z-index:10; background:var(--bg); }}
nav .in {{ display:flex; gap:6px; overflow-x:auto; padding-block:10px; }}
nav a {{ flex:none; font:600 .82rem var(--body); color:var(--accent); text-decoration:none; padding:4px 10px; border:1px solid var(--line); border-radius:999px; background:var(--panel); }}
a:focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; }}
section {{ padding-top:40px; scroll-margin-top:64px; }}
.sh {{ display:grid; gap:6px; max-width:75ch; }} .sh p {{ margin:0; color:var(--muted); }}
.where {{ font:.75rem var(--mono); text-transform:uppercase; letter-spacing:.08em; color:var(--accent); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 440px), 1fr)); gap:20px; margin-top:18px; }}
.card {{ margin:0; background:var(--panel); border:1px solid var(--line); border-radius:6px; overflow:hidden; display:flex; flex-direction:column; min-width:0; }}
.shot {{ display:block; background:#fff; padding:8px; border-bottom:1px solid var(--line); }}
.shot img {{ display:block; width:100%; height:auto; max-height:520px; object-fit:contain; }}
figcaption {{ padding:12px 14px 14px; display:grid; gap:6px; min-width:0; }} figcaption p {{ margin:0; font-size:.95rem; }}
.meta {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px 10px; justify-content:space-between; }}
code {{ font:.78rem var(--mono); color:var(--muted); overflow-wrap:anywhere; }}
.pill {{ font:600 .72rem var(--body); padding:2px 8px; border-radius:999px; white-space:nowrap; }}
.pill.ok {{ color:var(--ok); background:var(--ok-bg); }} .pill.warn {{ color:var(--warn); background:var(--warn-bg); }} .pill.off {{ color:var(--off); background:var(--off-bg); }}
.cav {{ color:var(--warn); font-size:.88rem !important; }}
footer {{ margin-top:48px; color:var(--muted); font-size:.88rem; max-width:75ch; }}
</style>
<div class="wrap">
<header><h1>{title}</h1><p class="lede">{lede}</p>
<div class="legend"><span class="pill ok">Rebuilt</span><span class="pill warn">Rebuilt, differs</span><span class="pill off">Not rebuilt (reason given)</span><span>Click a figure to open it full size.</span></div></header>
<nav aria-label="Figure groups"><div class="in">{nav}</div></nav>
{sections}
<footer>{footer}</footer>
</div>
'''

if __name__ == '__main__':
    main()
