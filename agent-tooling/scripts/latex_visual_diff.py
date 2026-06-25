#!/usr/bin/env python3
"""latex_visual_diff.py — show a STYLING change visually: before vs after PNGs.

For changes that alter rendering (spacing, fonts, layout, colors) a text diff is
useless. This compiles both versions, rasterizes pages, finds the pages that
actually changed (pixel diff), crops to the changed region, and writes paired
old/new PNGs — so you show only what moved, token-efficiently.

Pipeline: detect build -> compile before+after -> pdftoppm to PNG -> per-page
pixel diff (PIL) -> crop union bbox (padded) -> write {page}-old.png/{page}-new.png.

Runtime deps (Claude Code / a LaTeX env): latexmk or pdflatex/xelatex, pdftoppm
(poppler), and Pillow. In Cowork, ensure these are in the VM. Pure helpers
(_pad_bbox, build detection) are import-safe without them.

Usage:
  latex_visual_diff.py --before before/main.tex --after after/main.tex --out shots/
  latex_visual_diff.py --before old.pdf --after new.pdf --out shots/   # skip compile
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

_DOCCLASS = re.compile(r"\\documentclass")
_BODY = re.compile(r"\\begin\{document\}")
_TEXPROG = re.compile(r"%\s*!TEX\s+program\s*=\s*(\w+)", re.IGNORECASE)


def find_main(path: str) -> str:
    """If path is a dir, find the main .tex (has \\documentclass + \\begin{document})."""
    if os.path.isfile(path):
        return path
    best = None
    for root, _, files in os.walk(path):
        for f in files:
            if not f.endswith(".tex"):
                continue
            fp = os.path.join(root, f)
            txt = open(fp, encoding="utf-8", errors="replace").read()
            if _DOCCLASS.search(txt):
                if _BODY.search(txt):
                    return fp
                best = best or fp
    if not best:
        raise FileNotFoundError(f"no main .tex (with \\documentclass) under {path}")
    return best


def detect_compiler(tex_path: str) -> list[str]:
    """Build command for the PDF. latexmk if present (handles reruns/bib), else direct."""
    prog = "pdflatex"
    m = _TEXPROG.search(open(tex_path, encoding="utf-8", errors="replace").read())
    if m:
        prog = m.group(1).lower()
    base = os.path.basename(tex_path)
    if shutil.which("latexmk"):
        engine = {"xelatex": "-xelatex", "lualatex": "-lualatex"}.get(prog, "-pdf")
        return ["latexmk", engine, "-interaction=nonstopmode", "-halt-on-error", base]
    return [prog, "-interaction=nonstopmode", "-halt-on-error", base]


def compile_pdf(tex_path: str, workdir: str) -> str:
    cmd = detect_compiler(tex_path)
    d = os.path.dirname(os.path.abspath(tex_path)) or "."
    runs = 1 if cmd[0] == "latexmk" else 2          # plain engines need 2 passes for refs
    for _ in range(runs):
        r = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=300)
    pdf = os.path.splitext(os.path.abspath(tex_path))[0] + ".pdf"
    if not os.path.exists(pdf):
        raise RuntimeError(f"compile failed for {tex_path}:\n{r.stdout[-800:]}")
    return pdf


def pdf_to_pngs(pdf: str, outdir: str, dpi: int = 150) -> list[str]:
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.join(outdir, "p")
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), pdf, stem],
                   check=True, capture_output=True, timeout=300)
    return sorted(os.path.join(outdir, f) for f in os.listdir(outdir)
                  if f.startswith("p") and f.endswith(".png"))


def _pad_bbox(bbox, w, h, pad):
    """Expand a (l,t,r,b) bbox by pad px, clamped to the image. Pure/testable."""
    if bbox is None:
        return None
    l, t, r, b = bbox
    return (max(0, l - pad), max(0, t - pad), min(w, r + pad), min(h, b + pad))


def diff_pages(old_pngs, new_pngs, out, pad=24):
    """Write {n}-old.png/{n}-new.png crops for each visually changed page. Returns paths."""
    from PIL import Image, ImageChops
    os.makedirs(out, exist_ok=True)
    pairs = []
    for i in range(max(len(old_pngs), len(new_pngs))):
        o = old_pngs[i] if i < len(old_pngs) else None
        n = new_pngs[i] if i < len(new_pngs) else None
        if o and n:
            a, b = Image.open(o).convert("RGB"), Image.open(n).convert("RGB")
            if a.size == b.size:
                bbox = ImageChops.difference(a, b).getbbox()
                if bbox is None:
                    continue                      # page identical — skip (efficiency)
                box = _pad_bbox(bbox, a.width, a.height, pad)
                op = os.path.join(out, f"page{i+1}-old.png"); a.crop(box).save(op)
                npth = os.path.join(out, f"page{i+1}-new.png"); b.crop(box).save(npth)
                pairs.append((i + 1, op, npth))
                continue
        # size/page-count change → emit whole pages
        if o:
            op = os.path.join(out, f"page{i+1}-old.png"); shutil.copy(o, op)
        if n:
            npth = os.path.join(out, f"page{i+1}-new.png"); shutil.copy(n, npth)
        pairs.append((i + 1, o and op or None, n and npth or None))
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--before", required=True, help=".tex/dir or .pdf")
    ap.add_argument("--after", required=True)
    ap.add_argument("--out", default="/tmp/latex-visual-diff")
    ap.add_argument("--dpi", type=int, default=150)
    a = ap.parse_args()

    def to_pdf(p, tag):
        if p.lower().endswith(".pdf"):
            return p
        return compile_pdf(find_main(p), os.path.join(a.out, tag))

    old_pdf, new_pdf = to_pdf(a.before, "before"), to_pdf(a.after, "after")
    old_pngs = pdf_to_pngs(old_pdf, os.path.join(a.out, "old-pages"), a.dpi)
    new_pngs = pdf_to_pngs(new_pdf, os.path.join(a.out, "new-pages"), a.dpi)
    pairs = diff_pages(old_pngs, new_pngs, a.out, pad=a.dpi // 6)
    if not pairs:
        print("no visual change between the two PDFs", file=sys.stderr)
        return 0
    for pg, o, n in pairs:
        print(f"page {pg}: {o or '(none)'}  |  {n or '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
