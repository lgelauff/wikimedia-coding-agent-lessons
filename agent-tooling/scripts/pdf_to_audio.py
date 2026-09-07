#!/usr/bin/env python3
"""pdf_to_audio.py — turn a laid-out PDF (magazine, multi-column) into listenable audio.

The hard part is not speech, it is reading order. A magazine page is several
columns plus captions, pull quotes, headers and page numbers, and a naive
extractor reads straight across the columns and interleaves the furniture into
the middle of sentences. Coordinates make columns tractable; pull quotes are
worse, because they sit mid-column and repeat body text verbatim, so geometry
alone keeps them and you hear every good sentence twice.

So: PyMuPDF supplies text blocks with their bounding boxes, an LLM puts them in
reading order and labels what each one is, and only the body survives into the
audio. The LLM sees text and geometry — never an image — which keeps each page a
small request.

Provider is whatever AGENT_LLM_PROVIDER selects (default liftwing: free,
WMF-hosted, 100 req/h anonymous — one request per page, so a 40-page magazine
fits). Set AGENT_RATE_WAIT=1 to pace instead of failing when the bucket is dry.

LiftWing has no JSON mode and no tool calling, so the reply is parsed loosely and
anything unusable falls back to a geometric column sort. A page never fails the
run; it just gets read slightly worse.

Usage:
    pdf_to_audio.py IN.pdf --text-only -o out.txt
    pdf_to_audio.py IN.pdf -o out.aiff --voice Daniel
    pdf_to_audio.py IN.pdf --pages 3-9 --text-only
    pdf_to_audio.py IN.pdf --no-llm --text-only     # geometry only, no network

Exit codes: 0 ok, 1 failure (missing dep, unreadable PDF, TTS error), 2 usage.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

BODY_LABELS = {"body", "heading", "subheading"}
DROP_LABELS = {"caption", "pullquote", "furniture", "pagenum", "header", "footer"}

SYSTEM = (
    "You reconstruct the reading order of a laid-out print page. "
    "You are given numbered text blocks with bounding boxes. "
    "Answer with JSON only."
)

PROMPT = """Below are text blocks extracted from one page of a magazine-style PDF,
with bounding boxes as [x0, y0, x1, y1]. Origin is top-left; x grows right, y grows down.
Page is {w:.0f} wide by {h:.0f} tall.

Return the blocks in the order a human would READ them, and label each one:

- "body"       continuous prose that belongs in the article
- "heading"    a title or subheading that should be read aloud
- "caption"    figure/photo caption
- "pullquote"  a quote lifted out and enlarged — it repeats body text, so it must be dropped
- "furniture"  page number, running header/footer, masthead, folio, advert

Reading order matters most: this page is probably multi-column, so finish one column
before starting the next. Do not merge or rewrite any text.

Reply with ONLY a JSON array, one object per block, like:
[{{"i": 3, "label": "heading"}}, {{"i": 0, "label": "body"}}]

Blocks:
{blocks}"""


def extract_blocks(path: str, first: int | None, last: int | None) -> list[dict]:
    """Text blocks with geometry, one list per page. Requires PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        sys.exit("ERROR: PyMuPDF not installed. Run: pip install pymupdf")
    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001 — surface any parse failure plainly
        sys.exit(f"ERROR: cannot open {path}: {exc}")

    pages = []
    for n, page in enumerate(doc, start=1):
        if first and n < first:
            continue
        if last and n > last:
            continue
        blocks = []
        for b in page.get_text("blocks"):
            x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
            text = " ".join(text.split())
            if text:
                blocks.append({"bbox": [x0, y0, x1, y1], "text": text})
        pages.append({"n": n, "w": page.rect.width, "h": page.rect.height,
                      "blocks": blocks})
    doc.close()
    return pages


def column_sort(blocks: list[dict], width: float) -> list[int]:
    """Geometric fallback: split at the page midpoint, then read each column top-down.

    Crude by design — it is what runs when the model is unavailable or its reply
    is unusable, and a two-column guess beats reading straight across.
    """
    mid = width / 2
    left = [i for i, b in enumerate(blocks) if b["bbox"][0] < mid]
    right = [i for i, b in enumerate(blocks) if b["bbox"][0] >= mid]
    key = lambda i: blocks[i]["bbox"][1]  # noqa: E731
    return sorted(left, key=key) + sorted(right, key=key)


def parse_order(reply: str, n_blocks: int) -> list[tuple[int, str]] | None:
    """Pull [{i,label},...] out of a reply that may be wrapped in prose or fences.

    No JSON mode on LiftWing, so the model may add commentary either side. Take
    the outermost bracketed span and validate; return None to trigger fallback.
    """
    m = re.search(r"\[.*\]", reply, re.S)
    if not m:
        return None
    try:
        rows = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        i, label = r.get("i"), str(r.get("label", "body")).lower().strip()
        if isinstance(i, int) and 0 <= i < n_blocks:
            out.append((i, label))
    return out or None


def order_page(page: dict, use_llm: bool, verbose: bool) -> list[str]:
    """Return the readable lines for one page, body and headings only."""
    blocks = page["blocks"]
    if not blocks:
        return []

    if use_llm:
        listing = "\n".join(
            f'{i}: bbox={[round(v) for v in b["bbox"]]} text={b["text"][:220]!r}'
            for i, b in enumerate(blocks)
        )
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from llm_provider import query_llm

            reply = query_llm(
                PROMPT.format(w=page["w"], h=page["h"], blocks=listing),
                system=SYSTEM, timeout=120,
            )
            parsed = parse_order(reply, len(blocks))
        except Exception as exc:  # noqa: BLE001 — a bad page must not kill the run
            if verbose:
                print(f"  page {page['n']}: LLM failed ({exc}); using geometry",
                      file=sys.stderr)
            parsed = None
        if parsed:
            return [blocks[i]["text"] for i, label in parsed if label in BODY_LABELS]
        if verbose:
            print(f"  page {page['n']}: unusable reply; using geometry", file=sys.stderr)

    return [blocks[i]["text"] for i in column_sort(blocks, page["w"])]


def speak(text: str, out: str, voice: str | None) -> None:
    cmd = ["say", "-o", out]
    if voice:
        cmd += ["-v", voice]
    try:
        subprocess.run(cmd, input=text, text=True, check=True)
    except FileNotFoundError:
        sys.exit("ERROR: 'say' not found (macOS only). Use --text-only and your own TTS.")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"ERROR: say failed ({exc.returncode})")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Magazine-style PDF -> reading-ordered text or audio.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Provider via AGENT_LLM_PROVIDER (default liftwing, free). "
               "AGENT_RATE_WAIT=1 paces instead of failing on the rate bucket.",
    )
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", help="output file (.aiff for audio, .txt for text)")
    ap.add_argument("--text-only", action="store_true", help="stop after extraction")
    ap.add_argument("--no-llm", action="store_true",
                    help="geometry only — no network, no rate limit, worse order")
    ap.add_argument("--pages", help="page range, e.g. 3-9")
    ap.add_argument("--voice", help="say(1) voice, e.g. Daniel")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    first = last = None
    if a.pages:
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", a.pages.strip())
        if not m:
            ap.error("--pages must look like 5 or 3-9")
        first = int(m.group(1))
        last = int(m.group(2) or m.group(1))

    pages = extract_blocks(a.pdf, first, last)
    if not pages:
        sys.exit("ERROR: no pages in range")

    chunks = []
    for p in pages:
        if a.verbose:
            print(f"page {p['n']}: {len(p['blocks'])} blocks", file=sys.stderr)
        chunks.extend(order_page(p, use_llm=not a.no_llm, verbose=a.verbose))
    text = "\n\n".join(chunks)

    if not text.strip():
        sys.exit("ERROR: no readable text found (scanned PDF? try OCR first)")

    if a.text_only:
        if a.out:
            with open(a.out, "w") as fh:
                fh.write(text)
            print(f"wrote {a.out} ({len(text):,} chars, {len(pages)} pages)")
        else:
            print(text)
        return 0

    out = a.out or "out.aiff"
    speak(text, out, a.voice)
    print(f"wrote {out} ({len(text):,} chars, {len(pages)} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
