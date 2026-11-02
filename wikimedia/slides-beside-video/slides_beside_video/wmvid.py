"""wmvid: slides-beside-video pipeline for Wikimania recordings (one recording at a time).

Recordings and decks come from Wikimedia Commons; OCR is tesseract, speech-to-text is whisper.cpp
(whisper-cli). Stages are idempotent: each writes one output and is skipped when that output exists.
Configure once with configure(dict) (see config.example.json) before running any stage.

Evidence classes per second of the rendered video:
  confirmed   distinctive deck phrases read (OCR) in the video frame near this moment
  audio       the transcript window matches distinctive words of this page
  visual      image matching (ORB/RANSAC) picks this page, >= 15 inliers
  unverified  best guess from the timeline model, no direct evidence
"""
import gzip
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request

import cv2
import numpy as np
import pymupdf

UA = None                # set by configure(): a descriptive User-Agent with contact info (Wikimedia policy)
API = "https://commons.wikimedia.org/w/api.php"
MODEL = None             # whisper.cpp model file (e.g. ggml-large-v3-turbo-q5_0.bin)
WHISPER = "whisper-cli"  # whisper.cpp command-line binary
INVENTORY = None         # optional JSON list of candidate Commons decks (deck discovery); see README
MIN_FREE_BYTES = 12 * 2 ** 30   # refuse to download a recording below this much free disk


def configure(cfg):
    """Set the module settings from a config dict (keys as in config.example.json)."""
    global UA, MODEL, WHISPER, INVENTORY, MIN_FREE_BYTES, BUDGET_FILE, BUDGET_CAPS
    UA = cfg["user_agent"]
    BUDGET_FILE = cfg.get("budget_file") or os.path.join(cfg["work_dir"], "_budget.json")
    BUDGET_CAPS = {k: float(v) for k, v in (cfg.get("budget") or {}).items() if v is not None}
    MODEL = cfg.get("whisper_model")
    WHISPER = cfg.get("whisper_cli") or shutil.which("whisper-cli") or "whisper-cli"
    INVENTORY = cfg.get("deck_inventory")
    MIN_FREE_BYTES = int(float(cfg.get("min_free_disk_gb", 12)) * 2 ** 30)
    from . import clef
    clef.UA = UA
INTRO_SKIP = 90
OCR_EVERY = 30          # seconds between OCR frames
ORB_EVERY = 6           # seconds between image-matching frames (2 s cost 15 min per 42-min talk for ~0 % more labels)
PANEL_H = 720
GENERIC = {"wikimedia", "wikipedia", "wikisource", "commons", "mediawiki", "foundation", "wikimania",
           "conference", "session", "wikidata", "wiktionary", "introduction", "technical", "collaboration",
           "community", "communities", "editors", "developers", "thank", "thanks", "questions", "question",
           "license", "licensed", "attribution", "sharealike", "creative", "slide", "slides"}
STOP = set("""about above after again against because before being below between both could does doing
during each further having here hers herself himself itself just more most other ought ours ourselves
over same should some such than that their theirs them themselves then there these they this those
through under until very what when where which while whom with would your yours yourself yourselves
also into only like make made many much need using used want will well were have from been http https
www com org html""".split())
COLORS = {"confirmed": (60, 150, 60), "audio": (190, 110, 40), "visual": (30, 140, 200), "unverified": (120, 120, 120),
          "live_browser": (90, 60, 140), "not_in_deck": (40, 40, 160), "after_talk": (70, 70, 70),
          "vision": (130, 130, 0),
          # timelines rebuilt by an agent reading the transcript (talks without the screen in shot)
          "transcript_agent": (150, 80, 170), "transcript_none": (80, 60, 110)}
LABEL_TEXT = {"transcript_agent": "transcript read by an agent: words fit this slide (silver)",
              "transcript_none": "transcript read by an agent: no slide fits (silver)","confirmed": "confirmed: slide text read in the video",
              "audio": "audio: the speaker's words match this slide",
              "visual": "visual: image match with the recording",
              "unverified": "unverified: best guess",
              "live_browser": "live browser on screen: no slide shown",
              "not_in_deck": "screen shows text not in this deck: no slide shown",
              "after_talk": "the talk is over: no slide shown",
              "vision": "vision model: this slide matches the frame"}
# Interface text of a browser or a MediaWiki page (a live browser on screen -> show no slide).
BROWSER_PHRASES = ["main page", "recent changes", "random article", "village pump", "upload file", "what links here",
                   "related changes", "special pages", "permanent link", "printable version", "view history",
                   "create account", "log in", "page information", "cite this page", "download as pdf",
                   "create a book", "search wikipedia", "view source", "edit source", "talk contributions",
                   "from wikipedia the free encyclopedia", "jump to navigation", "new tab", "bookmarks",
                   "translate this page", "this page contains", "page contains changes", "marked for translation",
                   "other languages", "do brasil", "nederlands", "francais", "deutsch"]
WEB_TOKENS = {"http", "https", "www"}


def browser_score(toks):
    """Browser/MediaWiki page markers read in one OCR frame: distinct interface phrases plus URL tokens."""
    joined = " " + " ".join(toks) + " "
    return sum(1 for p in BROWSER_PHRASES if f" {p} " in joined) + min(2, sum(1 for t in toks if t in WEB_TOKENS))


# ---------------------------------------------------------------- utilities
def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def jdump(obj, path):
    """Atomic JSON write (tmp + rename). An identical rewrite is skipped, so a cached stage that saves its
    unchanged result again keeps the checksum recorded in status.json."""
    text = json.dumps(obj, indent=1, ensure_ascii=False)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return
    except (OSError, UnicodeDecodeError):
        pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def imwrite_atomic(path, img, params=()):
    """cv2.imwrite to a temp name with the same extension, then rename: a killed write never leaves a truncated
    image under the final name (several stages reuse an image when the file exists)."""
    base, ext = os.path.splitext(path)
    tmp = base + ".part" + ext
    if not cv2.imwrite(tmp, img, list(params)):
        raise IOError(f"imwrite failed: {path}")
    os.replace(tmp, path)


def file_hash(path, algo="sha256"):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dump_marked(obj, path):
    """A chunk's done marker: the payload plus the sha256 of its canonical JSON."""
    body = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    jdump({"sha256": hashlib.sha256(body.encode()).hexdigest(), "data": obj}, path)


def load_marked(path):
    """The payload of a done marker, or None when it is missing, unreadable or fails its checksum."""
    try:
        d = jload(path)
    except (OSError, ValueError):
        return None
    body = json.dumps(d.get("data"), sort_keys=True, ensure_ascii=False)
    return d["data"] if hashlib.sha256(body.encode()).hexdigest() == d.get("sha256") else None


# Budget ledger for one batch: every attempt is charged BEFORE it is made, retries included, so a kill -9
# mid-download still counts it. configure() sets the file ("budget_file", default <work_dir>/_budget.json; use a
# fresh one per batch) and the caps ("budget": {"download_bytes", "api_calls", "clef_calls"}; a missing cap means
# counted, not capped).
BUDGET_FILE = None
BUDGET_CAPS = {}


class BudgetExceeded(RuntimeError):
    pass


def budget():
    return jload(BUDGET_FILE) if os.path.exists(BUDGET_FILE) else {"started": time.strftime("%Y-%m-%dT%H:%M:%S")}


def charge(kind, n=1):
    if not BUDGET_FILE:
        raise RuntimeError("configure() first: no budget file set")
    b = budget()
    cap = BUDGET_CAPS.get(kind)
    if n > 0 and cap and b.get(kind, 0) + n > float(cap):
        raise BudgetExceeded(f"{kind}: {b.get(kind, 0)} + {n} would exceed the budget {cap} ({BUDGET_FILE})")
    b[kind] = b.get(kind, 0) + n
    os.makedirs(os.path.dirname(BUDGET_FILE), exist_ok=True)
    jdump(b, BUDGET_FILE)


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def take_lock(path):
    """Exclusive pid lock. A lock left by a killed process (dead pid) is taken over; a live one is refused."""
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(open(path).read().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if pid and pid != os.getpid() and pid_alive(pid):
                return False
            os.remove(path)
            continue
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    return False


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Throttled(Exception):
    pass


def api(params, tries=5):
    """MediaWiki API GET. Throttling never comes back as data: an HTTP 429/503 or an
    API error 'ratelimited'/'maxlag' is waited out (Retry-After when given) and retried, then raised."""
    params = dict(params, format="json", formatversion="2", maxlag="5")
    url = API + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        wait = 5 * 2 ** i
        charge("api_calls")                      # every attempt counts against the batch budget
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})  # Robot Policy
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                d = json.loads(raw.decode())
            code = (d.get("error") or {}).get("code")
            if code in ("ratelimited", "maxlag", "readonly", "internal_api_error_DBQueryTimeoutError"):
                raise Throttled(code)
            return d
        except urllib.error.HTTPError as e:
            ra = e.headers.get("Retry-After")
            if e.code not in (429, 503) or i == tries - 1:
                raise
            wait = min(int(ra), 900) if ra and ra.isdigit() else wait
        except Throttled:
            if i == tries - 1:
                raise
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(wait)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def probe_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path]).stdout
    return float(out.strip() or 0)


def tokens(text):
    return re.findall(r"[a-zà-ÿ]{2,}", text.lower())


FUNCTION_WORDS = set("of the and to in for on is with by an at as or from be it we our you are this that".split())


def ctokens(toks):
    """Content tokens: function words removed on BOTH sides, so 'anatomy of editing a page' -> anatomy editing page."""
    return [t for t in toks if t not in FUNCTION_WORDS]


# ---------------------------------------------------------------- stage: fetch
def file_info(title):
    d = api({"action": "query", "prop": "imageinfo", "titles": title,
             "iiprop": "url|size|mime|extmetadata|sha1"})
    page = d["query"]["pages"][0]
    ii = page["imageinfo"][0]
    em = ii.get("extmetadata", {})
    strip = lambda s: re.sub(r"<[^>]+>", "", html.unescape(s or "")).strip()
    return {"title": page["title"], "url": ii["url"], "size": ii["size"], "mime": ii.get("mime"),
            "sha1": ii.get("sha1"), "page_url": ii.get("descriptionurl"),
            "author": strip(em.get("Artist", {}).get("value")),
            "license": strip(em.get("LicenseShortName", {}).get("value")),
            "license_url": strip(em.get("LicenseUrl", {}).get("value")),
            "credit": strip(em.get("Credit", {}).get("value"))[:300]}


def download(url, path, size, tries=3, sha1=None):
    """.part + rename; size and (when given) the Commons sha1 are checked before the rename. Each attempt is
    charged in full before it starts (a kill -9 keeps the charge); a failed attempt is refunded what it did not
    fetch."""
    for i in range(tries):
        charge("download_bytes", size)
        charge("download_attempts")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=600) as r, open(path + ".part", "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            if os.path.getsize(path + ".part") != size:
                raise IOError(f"size {os.path.getsize(path + '.part')} != {size}")
            if sha1 and file_hash(path + ".part", "sha1") != sha1:
                raise IOError(f"sha1 mismatch for {os.path.basename(path)}")
            os.replace(path + ".part", path)
            return
        except Exception:
            got = os.path.getsize(path + ".part") if os.path.exists(path + ".part") else 0
            charge("download_bytes", min(got, size) - size)
            if i == tries - 1:
                raise
            time.sleep(30 * 2 ** i)


def stage_fetch(w, item):
    out = os.path.join(w, "fetch.json")
    media = os.path.join(w, "media")
    os.makedirs(media, exist_ok=True)
    meta = jload(out) if os.path.exists(out) else {
        "video": file_info("File:" + item["commons_file"]),
        "deck": file_info(item["deck_title"]) if item.get("deck_title") else None}   # no deck: found by content later
    for kind, name in (("video", "video" + os.path.splitext(meta["video"]["title"])[1].lower()), ("deck", "deck.pdf")):
        if meta.get(kind) is None:
            continue
        path = os.path.join(media, name)
        meta[kind]["path"] = path
        if not os.path.exists(path):
            free = shutil.disk_usage(media).free
            if free < MIN_FREE_BYTES:           # disk floor, checked before each download
                raise RuntimeError(f"disk floor: {free/1e9:.1f} GB free")
            t0 = time.time()
            download(meta[kind]["url"], path, meta[kind]["size"], sha1=meta[kind].get("sha1"))
            meta[kind]["download_s"] = round(time.time() - t0, 1)
    meta["duration_s"] = probe_duration(meta["video"]["path"])
    jdump(meta, out)
    return meta


# ---------------------------------------------------------------- stage: transcript
SRT_TIME = r"(\d\d:\d\d:\d\d[,.]\d\d\d) --> (\d\d:\d\d:\d\d[,.]\d\d\d)"


def _secs(t):
    h, m, rest = t.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def parse_srt(text):
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        m = re.search(SRT_TIME, block)
        if m and block[m.end():].strip():
            cues.append([_secs(m.group(1)), _secs(m.group(2)), re.sub(r"\s+", " ", block[m.end():].strip())])
    return cues


def timedtext(file_title):
    """Exact-title lookup of TimedText subtitles. Not found -> None. API trouble after
    retries -> None as well (Whisper is a fine fallback), but logged and recorded as 'lookup_error' by the caller,
    so a throttle is never mistaken for 'no subtitles on Commons'."""
    name = file_title.replace("File:", "")
    try:
        titles = [f"TimedText:{name}.{lang}.srt" for lang in ("en", "fr", "es", "de", "pt", "it", "nl", "ar", "ru", "zh")]
        d = api({"action": "query", "prop": "info", "titles": "|".join(titles)})
        found = [p["title"] for p in d.get("query", {}).get("pages", []) if "missing" not in p and "invalid" not in p]
        if not found:
            return None
        r = api({"action": "query", "prop": "revisions", "titles": found[0], "rvprop": "content", "rvslots": "main"})
        content = r["query"]["pages"][0]["revisions"][0]["slots"]["main"]["content"]
        return {"source": "timedtext", "page": found[0], "cues": parse_srt(content)}
    except BudgetExceeded:
        raise
    except Exception as e:
        log(f"timedtext lookup failed, falling back to whisper: {e}")
        return {"lookup_error": f"{type(e).__name__}: {e}"[:200]}


def whisper_chunk(wav, base):
    r = subprocess.run([WHISPER, "-m", MODEL, "-f", wav, "-l", "auto", "-t", "8", "-osrt", "-of", base],
                       capture_output=True, text=True)
    srt = base + ".srt"
    if r.returncode == 0 and os.path.exists(srt):
        with open(srt, encoding="utf-8") as f:
            cues = parse_srt(f.read())
        os.remove(srt)
        lang = re.search(r"auto-detected language: (\w+)", r.stderr or "")
        return cues, (lang.group(1) if lang else None)
    return None, None


def stage_transcript(w, meta, chunk_s=300):
    out = os.path.join(w, "transcript.json")
    if os.path.exists(out):
        return jload(out)
    tt = timedtext(meta["video"]["title"])
    if tt and len(tt.get("cues", [])) > 20:
        jdump(tt, out)
        return tt
    video, dur = meta["video"]["path"], meta["duration_s"]
    cues, langs, failed, t0 = [], [], 0, time.time()
    for i in range(int(math.ceil(dur / chunk_s))):
        marker = os.path.join(w, "media", f"tx_chunk_{i:03d}.json")   # checksummed done marker per chunk
        got = load_marked(marker)
        if got and got.get("model") == os.path.basename(MODEL) and got.get("chunk_s") == chunk_s:
            cues += got["cues"]
            langs.append(got["lang"])
            failed += got["failed"]
            continue
        wav = os.path.join(w, "media", f"chunk_{i:03d}.wav")
        run(["ffmpeg", "-y", "-v", "error", "-ss", str(i * chunk_s), "-t", str(chunk_s), "-i", video,
             "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav])
        c, lang = whisper_chunk(wav, wav[:-4])
        chunk_failed = 0
        if c is None:                         # split-retry once
            parts, c = [], []
            half = chunk_s / 2
            for j in range(2):
                hw = wav[:-4] + f"_h{j}.wav"
                run(["ffmpeg", "-y", "-v", "error", "-ss", str(j * half), "-t", str(half), "-i", wav, "-c", "copy", hw])
                cj, lang = whisper_chunk(hw, hw[:-4])
                os.remove(hw)
                if cj is None:
                    chunk_failed += 1
                else:
                    c += [[a + j * half, b + j * half, t] for a, b, t in cj]
        chunk_cues = [[a + i * chunk_s, b + i * chunk_s, t] for a, b, t in c]
        dump_marked({"model": os.path.basename(MODEL), "chunk_s": chunk_s, "cues": chunk_cues, "lang": lang,
                     "failed": chunk_failed}, marker)
        cues += chunk_cues
        langs.append(lang)
        failed += chunk_failed
        os.remove(wav)
    res = {"source": "whisper", "model": os.path.basename(MODEL), "cues": cues, "languages": langs,
           "chunk_failures": failed, "seconds": round(time.time() - t0, 1),
           "words": sum(len(t.split()) for _, _, t in cues),
           "timedtext": (tt or {}).get("lookup_error") or ("too short" if tt else "none on Commons")}
    jdump(res, out)
    return res


# ---------------------------------------------------------------- applause (speaker-switch cue)
def audio_features(source, win=0.5):
    """Per-window loudness (dB) and spectral flatness 300-6000 Hz. source: path or URL (streamed, nothing stored)."""
    ua = ["-user_agent", UA] if str(source).startswith("http") else []   # the option is only valid for URLs
    pcm = subprocess.run(["ffmpeg", "-v", "error", *ua, "-i", source, "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(16000 * win)
    frames = x[: len(x) // n * n].reshape(-1, n)
    rms = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    spec = np.abs(np.fft.rfft(frames * np.hanning(n), axis=1)) ** 2 + 1e-12
    band = spec[:, int(300 * n / 16000): int(6000 * n / 16000)]
    flat = np.exp(np.log(band).mean(axis=1)) / band.mean(axis=1)
    return rms, flat


def applause_events(source, min_s=2.0, win=0.5, feats=None):
    """Stretches of applause: loud, broadband (spectrally flat) sound lasting >= min_s.
    Returns list of [start, end, peak_flatness]."""
    rms, flat = feats if feats is not None else audio_features(source, win)
    loud = rms > np.median(rms) + 3
    score = np.convolve(flat * loud, np.ones(6) / 6, mode="same")     # 3-s smoothed loud flatness
    mask = score >= 0.10          # e.g. end-of-session applause 0.145, speech peaks <= 0.07
    events, start = [], None
    for i, m in enumerate(np.append(mask, False)):
        if m and start is None:
            start = i
        elif not m and start is not None:
            if (i - start) * win >= min_s:
                events.append([round(start * win, 1), round(i * win, 1), round(float(flat[start:i].max()), 2)])
            start = None
    return events


# ---------------------------------------------------------------- deck text
def deck_text(deck_path):
    with pymupdf.open(deck_path) as doc:
        return [" ".join(p.get_text().split()) for p in doc], [(p.rect.width, p.rect.height) for p in doc]


def page_phrases(texts, max_per_page=15, topic=frozenset()):
    """Distinctive contiguous word pairs per page (no generic words, rare across the deck)."""
    toks = [ctokens(tokens(t)) for t in texts]
    df = {}
    for tk in toks:
        for p in {tuple(tk[i:i + 2]) for i in range(len(tk) - 1)}:
            df[p] = df.get(p, 0) + 1
    out = []
    for tk in toks:
        cand, seen = [], set()
        for j in range(len(tk) - 1):
            pair = (tk[j], tk[j + 1])
            if any(x in GENERIC for x in pair) or all(x in topic for x in pair) or sum(map(len, pair)) < 10 or df.get(pair, 0) > 2 or pair in seen:
                continue
            seen.add(pair)
            cand.append(pair)
        out.append(cand[:max_per_page])
    return out


def page_fragments(texts, topic=frozenset()):
    """Short word pairs that occur on exactly one page, function words kept (a zoomed-in
    camera shows one part of one slide, e.g. 'co-fund it.' -> 'co fund', 'fund it'). Matched contiguously on raw
    OCR tokens; at least 6 letters per pair so single letters and noise do not count."""
    toks = [tokens(t) for t in texts]
    df = {}
    for tk in toks:
        for p in {tuple(tk[i:i + 2]) for i in range(len(tk) - 1)}:
            df[p] = df.get(p, 0) + 1
    out = []
    for tk in toks:
        seen = []
        for j in range(len(tk) - 1):
            pair = (tk[j], tk[j + 1])
            if df[pair] == 1 and sum(map(len, pair)) >= 6 and not all(x in GENERIC or x in topic or x in FUNCTION_WORDS for x in pair) \
                    and pair not in seen:
                seen.append(pair)
        out.append(seen)
    return out


def raw_hits(frags, toks):
    joined = " " + " ".join(toks) + " "
    return [p for p in frags if " " + " ".join(p) + " " in joined]


def page_words(texts):
    """Distinctive single words per page for the audio channel (len >= 5, on at most 2 pages)."""
    sets = [{t for t in tokens(x) if len(t) >= 5 and t not in GENERIC and t not in STOP} for x in texts]
    df = {}
    for s in sets:
        for t in s:
            df[t] = df.get(t, 0) + 1
    return [{t for t in s if df[t] <= 2} for s in sets]


def contiguous_hits(phrases, toks):
    joined = " " + " ".join(ctokens(toks)) + " "
    return [p for p in phrases if " " + " ".join(p) + " " in joined]


def strong(hits):
    """Confirmation: two contiguous phrases, or one of at least 12 letters."""
    return len(hits) >= 2 or any(sum(map(len, p)) >= 12 for p in hits)


# ---------------------------------------------------------------- stage: ocr frames
def screen_crop(png, out_png, upscale=True):
    """Crop to the largest bright region (a projected or edited-in slide), upscale for OCR."""
    img = cv2.imread(png)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thr = max(150, int(np.percentile(gray, 85)))
    mask = cv2.morphologyEx((gray >= thr).astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    H, W = gray.shape
    crop = img
    if cnts:
        x, y, w, h = cv2.boundingRect(max(cnts, key=cv2.contourArea))
        if w * h >= 0.04 * W * H:
            crop = img[y:y + h, x:x + w]
    if upscale:
        scale = max(1.0, 2200 / crop.shape[1])
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(out_png, crop)
    return out_png


def ocr_png(png):
    crop = screen_crop(png, png[:-4] + "_crop.png")
    toks = []
    for src, psm in ((crop, "6"), (crop, "11"), (png, "11")):
        r = subprocess.run(["tesseract", src, "-", "--psm", psm], capture_output=True, text=True)
        toks += tokens(r.stdout) + ["|"]          # '|' separates passes so phrases never span them
    return toks


def stage_ocr(w, meta):
    out = os.path.join(w, "ocr.json")
    if os.path.exists(out):
        return jload(out)
    video, dur = meta["video"]["path"], meta["duration_s"]
    png = os.path.join(w, "media", "ocr.png")
    frames, t0, t = [], time.time(), float(INTRO_SKIP)
    while t < dur - 1:
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.1f}", "-i", video, "-frames:v", "1", png])
        frames.append({"t": t, "tokens": ocr_png(png)})
        t += OCR_EVERY
    res = {"every_s": OCR_EVERY, "frames": frames, "seconds": round(time.time() - t0, 1)}
    jdump(res, out)
    return res


# ---------------------------------------------------------------- stage: browser chrome (by sight)
def chrome_score(png):
    """Edge density of the top strip of the projected screen: a browser's tab/address bar is busy, a slide's top
    margin is empty (tabs at the top, a dock at the bottom = browser). On 11 labelled frames:
    browsers 20-31, slides 0-6. None when no screen is found."""
    img = cv2.imread(png)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thr = max(150, int(np.percentile(gray, 85)))
    mask = cv2.morphologyEx((gray >= thr).astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    x, y, w, h = cv2.boundingRect(max(cnts, key=cv2.contourArea))
    if w * h < 0.04 * gray.size:
        return None
    top = gray[y:y + max(4, h // 14), x:x + w]
    if top.shape[1] > 800:                       # same scale as the calibration (800-px-wide frames)
        top = cv2.resize(top, (800, max(4, int(top.shape[0] * 800 / top.shape[1]))))
    return round(float(cv2.Canny(top, 50, 150).mean()), 1)


def stage_chrome(w, meta, ocr):
    out = os.path.join(w, "chrome.json")
    if os.path.exists(out):
        return jload(out)
    png = os.path.join(w, "media", "chrome.png")
    fdir = os.path.join(w, "media", "frames")    # kept for the CLEF stage (deleted with the media at cleanup)
    os.makedirs(fdir, exist_ok=True)
    scores = {}
    for f in ocr["frames"]:
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{f['t']:.1f}", "-i", meta["video"]["path"], "-frames:v", "1", png])
        scores[str(int(f["t"]))] = chrome_score(png)
        img = cv2.imread(png)
        if img is not None:
            img = cv2.resize(img, (1280, int(img.shape[0] * 1280 / img.shape[1]))) if img.shape[1] > 1280 else img
            imwrite_atomic(os.path.join(fdir, f"{int(f['t'])}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    res = {"threshold": 15, "scores": scores}
    jdump(res, out)
    return res


def stage_ocr_refine(w, meta, ocr):
    """Slide switches fall between 30-s OCR frames (G15: browser 10 s before the next frame). Where two
    neighbouring frames point to different slides (or slide vs browser), OCR two extra frames in between."""
    out = os.path.join(w, "ocr_refined.json")
    if os.path.exists(out):
        return jload(out)
    texts, _ = deck_text(meta["deck"]["path"])
    phr = page_phrases(texts)

    def state(f):
        if browser_score(f["tokens"]) >= 2:
            return "browser"
        best = max(((len(contiguous_hits(ph, f["tokens"])), pg) for pg, ph in enumerate(phr)), default=(0, None))
        return best[1] if best[0] >= 1 else None

    frames = list(ocr["frames"])
    png = os.path.join(w, "media", "refine.png")
    extra = []
    for f0, f1 in zip(frames, frames[1:]):
        s0, s1 = state(f0), state(f1)
        if s0 is not None and s1 is not None and s0 != s1:
            for dt in (OCR_EVERY / 3, 2 * OCR_EVERY / 3):
                t = f0["t"] + dt
                run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.1f}", "-i", meta["video"]["path"], "-frames:v", "1", png])
                extra.append({"t": t, "tokens": ocr_png(png), "refined": True})
    res = dict(ocr, frames=sorted(frames + extra, key=lambda f: f["t"]), refined_frames=len(extra))
    jdump(res, out)
    return res


# ---------------------------------------------------------------- stage: CLEF (LiftWing vision decision model)
def stage_clef(w, meta, ocr, pre_tl, transcript, pace=2.6):
    """Two questions to llm-clef-flash (see clef.py; fuzheado/Wikipedia-AI-Skills wikimedia-ml-services):
    1. what is on screen (slide / browser / blank / none) for every OCR frame;
    2. which of 3 adjacent candidate pages is shown, only where the first-pass timeline had no strong text
       evidence and CLEF sees a slide. Candidates come from the first-pass timeline, in a seeded random order.
    Cached per frame, resumable; ~24 calls/min; errors stored as unmeasured, never as an answer."""
    import random
    from . import clef as C
    C.CHARGE = charge                            # every attempt counts against the batch budget
    out = os.path.join(w, "clef.json")
    res = jload(out) if os.path.exists(out) else {"schema": C.SCHEMA_VERSION, "screen": {}, "page": {}, "errors": 0}
    fdir = os.path.join(w, "media", "frames")
    if not os.path.isdir(fdir):
        jdump(res, out)
        return res
    cues = transcript.get("cues") or []
    strong_at = {e["t"] for e in pre_tl.get("evidence_log", []) if e.get("kind") == "ocr" and e.get("strong")}
    # >= 3 slide phrases on a frame: fuse lets no browser or none/blank answer override it, so do not ask
    settled_at = {e["t"] for e in pre_tl.get("evidence_log", []) if e.get("kind") == "ocr" and len(e["matched"]) >= 3}
    pdir = os.path.join(w, "media", "clefpages")
    os.makedirs(pdir, exist_ok=True)
    docs = [pymupdf.open(p) for p in pre_tl.get("decks", [meta["deck"]["path"]])]
    try:
        for f in ocr["frames"]:
            if f.get("refined"):
                continue
            t = int(f["t"])
            frame = os.path.join(fdir, f"{t}.jpg")
            if not os.path.exists(frame):
                continue
            if t in settled_at and str(t) not in res["screen"]:
                continue                         # rate limit (anonymous use): skip questions that cannot change fuse
            if str(t) not in res["screen"]:
                a = C.screen_type(frame)
                time.sleep(pace)
                if "error" in a:
                    res["errors"] += 1
                    continue
                res["screen"][str(t)] = a["screen"]["probabilities"]
                jdump(res, out)
            sc = res["screen"][str(t)]
            if sc.get("slide", 0) < 0.6 or any(abs(t - s) <= 15 for s in strong_at) or str(t) in res["page"]:
                continue
            seg = next((s for s in pre_tl["segments"] if s["start"] <= t < s["end"]), None)
            if not seg or not seg["page"]:
                continue
            di, p = seg.get("deck", 0), seg["page"]
            n = len(docs[di])
            cands = [x for x in (p - 1, p, p + 1) if 1 <= x <= n]
            random.Random(t).shuffle(cands)
            paths = []
            for x in cands:
                pp = os.path.join(pdir, f"d{di + 1}_p{x}.jpg")
                if not os.path.exists(pp):
                    page = docs[di][x - 1]
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(640 / page.rect.width, 640 / page.rect.width))
                    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                    imwrite_atomic(pp, cv2.cvtColor(img, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR))
                paths.append(pp)
            spoken = " ".join(c[2] for c in cues if c[1] >= t - 20 and c[0] <= t + 20)
            a = C.which_page(frame, paths, spoken)
            time.sleep(pace)
            if "error" in a:
                res["errors"] += 1
                continue
            res["page"][str(t)] = {"candidates": [[di + 1, x] for x in cands], "probs": a["match"]["probabilities"]}
            jdump(res, out)
        # Controls (every method needs a check that should fail): on frames whose page is settled by >= 3 OCR phrases,
        # ask the same page question (a) with the true page among its neighbours -> should pick it, and (b) with
        # three far pages only -> should say none. Reported per talk next to the real answers.
        res.setdefault("controls", [])
        settled = sorted({(e["t"], e["deck"], e["page"]) for e in pre_tl.get("evidence_log", [])
                          if e.get("kind") == "ocr" and len(e["matched"]) >= 3})
        rng = random.Random(len(settled))
        for t, d, p in rng.sample(settled, min(2, len(settled))) if len(res["controls"]) < 4 else []:
            frame = os.path.join(fdir, f"{t}.jpg")
            n = len(docs[d - 1])
            far = [x for x in range(1, n + 1) if abs(x - p) >= 3]
            if not os.path.exists(frame) or len(far) < 3:
                continue
            for kind, cands in (("positive", [x for x in (p - 1, p, p + 1) if 1 <= x <= n]),
                                ("negative", rng.sample(far, 3))):
                rng.shuffle(cands)
                paths = []
                for x in cands:
                    pp = os.path.join(pdir, f"d{d}_p{x}.jpg")
                    if not os.path.exists(pp):
                        page = docs[d - 1][x - 1]
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(640 / page.rect.width, 640 / page.rect.width))
                        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                        imwrite_atomic(pp, cv2.cvtColor(img, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR))
                    paths.append(pp)
                spoken = " ".join(c[2] for c in cues if c[1] >= t - 20 and c[0] <= t + 20)
                a = C.which_page(frame, paths, spoken)
                time.sleep(pace)
                if "error" in a:
                    res["controls"].append({"t": t, "kind": kind, "result": "unmeasured"})
                    continue
                pr = a["match"]["probabilities"]
                best = max(pr, key=pr.get)
                want = f"page{cands.index(p) + 1}" if kind == "positive" else "none"
                res["controls"].append({"t": t, "kind": kind, "true_page": [d, p], "candidates": cands,
                                        "answer": best, "p": round(pr[best], 2), "correct": best == want})
                jdump(res, out)
    finally:
        for d in docs:
            d.close()
    jdump(res, out)
    return res


# ---------------------------------------------------------------- stage: candidate decks (multi-deck sessions)


def load_inventory():
    """Candidate decks for discovery: {"slides": [{"title", "url", "conference_year", "wikimania_related",
    "uploader", "size_bytes"}, ...]}. No inventory configured -> no candidates (discovery is skipped)."""
    if not INVENTORY or not os.path.exists(INVENTORY):
        return []
    return list(jload(INVENTORY).values())[0]


def unexplained_frames(ocr, deck_paths):
    """OCR frames with readable text (>= 10 content words) and no strong hit on any of the given decks."""
    phr, frags = [], []
    for dp in ([deck_paths] if isinstance(deck_paths, str) else deck_paths):
        texts, _ = deck_text(dp)
        phr += page_phrases(texts)
        frags += page_fragments(texts)
    out = []
    for f in ocr["frames"]:
        content = [x for x in ctokens(f["tokens"]) if len(x) >= 4 and x != "|"]
        if len(content) < 10:
            continue
        strong_hit = any(strong(contiguous_hits(ph, f["tokens"])) for ph in phr) or \
            any(len(raw_hits(fr, f["tokens"])) >= 2 for fr in frags)
        if not strong_hit:
            out.append(f)
    return out


def deck_hits(deck_path, frames):
    texts, _ = deck_text(deck_path)
    phr, frags = page_phrases(texts), page_fragments(texts)
    seen = set()
    for f in frames:
        for pg, ph in enumerate(phr):
            seen.update((pg, p) for p in contiguous_hits(ph, f["tokens"]))
        for pg, fr in enumerate(frags):
            seen.update((pg, p) for p in raw_hits(fr, f["tokens"]))
    return len(seen)


def stage_candidates(w, meta, year, ocr, top=6):
    """Other decks of the same edition that explain screen text the main deck cannot. Accepted when their own
    phrases are read on screen (>= 3 distinct, density >= 1.0) and either twice the runner-up's density or
    >= 3 OCR frames won outright against every other deck (a panel's decks can have close densities)."""
    out = os.path.join(w, "candidates.json")
    if os.path.exists(out):
        return jload(out)
    res = {"unexplained_frames": [], "candidates": [], "accepted": [], "rounds": []}
    for _round in range(3):                      # a panel has several decks: accept one per round
        frames = unexplained_frames(ocr, [meta["deck"]["path"]] + [c["path"] for c in res["accepted"]])
        if not res["unexplained_frames"]:
            res["unexplained_frames"] = [f["t"] for f in frames]
        before = len(res["accepted"])
        round_cands = _candidate_round(w, meta, year, ocr, frames, top, res)
        res["rounds"].append({"unexplained": len(frames), "candidates": round_cands})
        if len(res["accepted"]) == before:
            break
    jdump(res, out)
    return res


def _candidate_round(w, meta, year, ocr, frames, top, res):
    round_cands = []
    accepted_titles = {c["title"] for c in res["accepted"]}
    if len(frames) >= 2:
        pool = {x for f in frames for x in ctokens(f["tokens"]) if len(x) >= 4}
        # also every word read anywhere on screen (names on end cards) and the recording's own title
        pool |= {x for f in ocr["frames"] for x in ctokens(f["tokens"]) if len(x) >= 6}
        rec_title = {x for x in ctokens(tokens(meta["video"]["title"])) if len(x) >= 4} - GENERIC - {"wikimania", "file"}
        inv = load_inventory()
        main = meta["deck"]["title"].replace(" ", "_")
        cands = []
        for d in inv:
            if d.get("conference_year") != year or not d.get("wikimania_related") or d["title"].replace(" ", "_") == main \
                    or d["title"] in accepted_titles:
                continue
            words = {x for x in ctokens(tokens(d["title"] + " " + d.get("uploader", ""))) if len(x) >= 4} - {"file", "wikimania"}
            score = len(words & pool) + 2 * len(words & rec_title)
            if score:
                cands.append((score, d))
        cands.sort(key=lambda c: -c[0])
        cdir = os.path.join(w, "media", "cand")
        os.makedirs(cdir, exist_ok=True)
        for i, (score, d) in enumerate(cands[:top]):
            path = os.path.join(cdir, "cand_" + hashlib.sha1(d["title"].encode()).hexdigest()[:12] + ".pdf")
            if not os.path.exists(path) and d.get("size_bytes", 0) < 40e6:
                time.sleep(3)
                info = file_info(d["title"])
                download(info["url"], path, info["size"])
                d = dict(d, author=info["author"], license=info["license"], license_url=info["license_url"],
                         page_url=info["page_url"])
            hits = deck_hits(path, frames) if os.path.exists(path) else 0
            n_phr = sum(len(p) for p in page_phrases(deck_text(path)[0])) if os.path.exists(path) else 0
            density = round(hits / math.sqrt(max(n_phr, 1)), 2)   # a long text document matches by volume
            round_cands.append({"title": d["title"], "path": path, "title_score": score, "hits": hits,
                                      "deck_phrases": n_phr, "density": density,
                                      "author": d.get("author"), "license": d.get("license"),
                                      "license_url": d.get("license_url"), "page_url": d.get("page_url")})
        # outright frame wins: OCR frames where a candidate has >= 2 hits and more than the main deck, every
        # accepted deck and every other candidate. A panel: two genuine decks with close densities
        # (3.14, 2.02) each won their own block of minutes (12 and 10 frames) while the 2x rule rejected both.
        present = [c for c in round_cands if os.path.exists(c["path"])]
        others = [meta["deck"]["path"]] + [c["path"] for c in res["accepted"]]
        for c in present:
            c["wins"] = 0
        for f in ocr["frames"]:
            base = max((deck_hits(p, [f]) for p in others), default=0)
            h = [deck_hits(c["path"], [f]) for c in present]
            for i, c in enumerate(present):
                if h[i] >= 2 and h[i] > base and all(h[i] > h[j] for j in range(len(h)) if j != i):
                    c["wins"] += 1
        ranked = sorted(round_cands, key=lambda c: -c["density"])
        by_wins = sorted(present, key=lambda c: -c["wins"])
        if ranked and ranked[0]["hits"] >= 3 and ranked[0]["density"] >= 1.0 and ranked[0]["density"] >= 2 * (ranked[1]["density"] if len(ranked) > 1 else 0):
            res["accepted"].append(ranked[0])
        elif by_wins and by_wins[0]["wins"] >= 3 and by_wins[0]["hits"] >= 3 and by_wins[0]["density"] >= 1.0:
            res["accepted"].append(dict(by_wins[0], accepted_by="frame wins"))
        res["candidates"] += round_cands
    return round_cands


def stage_discover(w, meta, year, ocr, transcript, top=8):
    """No deck, or the title-matched deck was not confirmed: find the deck by content. Same-edition decks are
    ranked by how many of their title/uploader words appear on screen or in the transcript; the best few are
    downloaded and scored by phrases read on screen (OCR + zoomed fragments) and slide phrases spoken aloud,
    relative to deck size. Accepted: >= 5 hits, density >= 1.0 and at least twice the runner-up."""
    out = os.path.join(w, "discover.json")
    if os.path.exists(out):
        return jload(out)
    cues = transcript.get("cues") or []
    spoken = " ".join(c[2] for c in cues)
    pool = {x for f in ocr["frames"] for x in ctokens(f["tokens"]) if len(x) >= 5}
    pool |= {x for x in ctokens(tokens(spoken)) if len(x) >= 6}
    rec_title = {x for x in ctokens(tokens(meta["video"]["title"])) if len(x) >= 4} - GENERIC - {"wikimania", "file"}
    inv = load_inventory()
    skip = (meta.get("deck") or {}).get("title", "").replace(" ", "_")
    cands = []
    for d in inv:
        if d.get("conference_year") != year or not d.get("wikimania_related") or d["title"].replace(" ", "_") == skip:
            continue
        words = {x for x in ctokens(tokens(d["title"] + " " + d.get("uploader", ""))) if len(x) >= 4} - {"file", "wikimania"}
        score = len(words & pool) + 2 * len(words & rec_title)
        if score:
            cands.append((score, d))
    cands.sort(key=lambda c: -c[0])
    cdir = os.path.join(w, "media", "cand")
    os.makedirs(cdir, exist_ok=True)
    res = {"candidates": [], "accepted": None}
    for score, d in cands[:top]:
        path = os.path.join(cdir, "cand_" + hashlib.sha1(d["title"].encode()).hexdigest()[:12] + ".pdf")
        info = None
        if not os.path.exists(path) and d.get("size_bytes", 0) < 40e6:
            time.sleep(3)
            info = file_info(d["title"])
            download(info["url"], path, info["size"])
        if not os.path.exists(path):
            continue
        texts, _ = deck_text(path)
        phr, frags = page_phrases(texts), page_fragments(texts)
        seen = set()
        for f in ocr["frames"]:
            for pg, ph in enumerate(phr):
                seen.update((pg, q) for q in contiguous_hits(ph, f["tokens"]))
            for pg, fr in enumerate(frags):
                seen.update((pg, q) for q in raw_hits(fr, f["tokens"]))
        spk = set()
        for c in cues:
            for pg, ph in enumerate(phr):
                spk.update((pg, q) for q in contiguous_hits(ph, tokens(c[2])))
        n_phr = sum(len(x) for x in phr)
        density = round((len(seen) + 0.5 * len(spk)) / math.sqrt(max(n_phr, 1)), 2)
        res["candidates"].append({"title": d["title"], "path": path, "title_score": score, "ocr_hits": len(seen),
                                  "spoken_hits": len(spk), "density": density, "info": info})
    ranked = sorted(res["candidates"], key=lambda c: -c["density"])
    if ranked:
        b0, b1 = ranked[0], (ranked[1] if len(ranked) > 1 else {"density": 0})
        if b0["ocr_hits"] + b0["spoken_hits"] >= 5 and b0["density"] >= 1.0 and b0["density"] >= 2 * b1["density"]:
            res["accepted"] = b0
    jdump(res, out)
    return res


# ---------------------------------------------------------------- stage: pair verdict
def score_deck(texts, ocr, transcript):
    phr, words = page_phrases(texts), page_words(texts)
    vis = set()
    for f in ocr["frames"]:
        for pg, ph in enumerate(phr):
            vis.update((pg, p) for p in contiguous_hits(ph, f["tokens"]))
    aud_windows = 0
    for win in transcript_windows(transcript):
        wt = set(tokens(win["text"]))
        best = max((len(ws & wt) for ws in words), default=0)
        aud_windows += best >= 3
    spoken = set()                               # slide phrases said aloud (e.g. slides never in shot)
    for c in transcript.get("cues") or []:
        for pg, ph in enumerate(phr):
            spoken.update((pg, q) for q in contiguous_hits(ph, tokens(c[2])))
    return {"visual_phrases": len(vis), "audio_windows": aud_windows, "spoken_phrases": len(spoken)}


def stage_pair(w, meta, ocr, transcript, decoy_deck_path):
    out = os.path.join(w, "pair.json")
    if os.path.exists(out):
        return jload(out)
    texts, _ = deck_text(meta["deck"]["path"])
    true = score_deck(texts, ocr, transcript)
    decoy = None
    if decoy_deck_path and os.path.exists(decoy_deck_path):
        decoy = score_deck(deck_text(decoy_deck_path)[0], ocr, transcript)
    d = decoy or {"visual_phrases": 0, "audio_windows": 0, "spoken_phrases": 0}
    vis_ok = true["visual_phrases"] >= 3 and true["visual_phrases"] >= 3 * d["visual_phrases"] + 1
    aud_ok = true["audio_windows"] >= 4 and true["audio_windows"] >= 2 * d["audio_windows"] + 2
    spk_ok = true["spoken_phrases"] >= 8 and true["spoken_phrases"] >= 3 * d.get("spoken_phrases", 0) + 1
    verdict = "CONFIRMED" if (vis_ok or aud_ok or spk_ok) else "UNCONFIRMED"
    res = {"verdict": verdict, "deck": true, "decoy": decoy, "visual_ok": vis_ok, "audio_ok": aud_ok, "spoken_ok": spk_ok,
           "decoy_path": decoy_deck_path, "deck_text_pages": sum(1 for t in texts if len(t) > 20),
           "rule": "CONFIRMED if visual phrases >= 3 and >= 3x decoy+1, or audio windows >= 4 and >= 2x decoy+2, "
                   "or spoken slide phrases >= 8 and >= 3x decoy+1"}
    jdump(res, out)
    return res


# ---------------------------------------------------------------- stage: visual (ORB)
def render_gray_pages(deck_path, width=640):
    pages = []
    with pymupdf.open(deck_path) as doc:
        for page in doc:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(width / page.rect.width, width / page.rect.width),
                                  colorspace=pymupdf.csGRAY)
            pages.append(np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy())
    return pages


def stage_visual(w, meta):
    out = os.path.join(w, "visual.json")
    if os.path.exists(out):
        return jload(out)
    t0 = time.time()
    orb, bf = cv2.ORB_create(nfeatures=800), cv2.BFMatcher(cv2.NORM_HAMMING)
    pdesc = []
    for img in render_gray_pages(meta["deck"]["path"]):
        kp, de = orb.detectAndCompute(img, None)
        pdesc.append((kp, de))
    W, H = 640, 360
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", meta["video"]["path"], "-vf",
                             f"fps=1/{ORB_EVERY},scale={W}:{H}:force_original_aspect_ratio=decrease,"
                             f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,format=gray", "-f", "rawvideo", "pipe:1"],
                            stdout=subprocess.PIPE, bufsize=10 ** 7)
    samples, t, prev, last = [], 0.0, None, None
    while True:
        buf = proc.stdout.read(W * H)
        if len(buf) < W * H:
            break
        fr = np.frombuffer(buf, dtype=np.uint8).reshape(H, W)
        diff = float(np.mean(cv2.absdiff(fr, prev))) if prev is not None else 999.0
        prev = fr
        if last is not None and diff < 1.5:          # same picture as before: reuse, saves most of the time on static cameras
            samples.append(dict(last, t=t, diff=round(diff, 1), reused=True))
            t += ORB_EVERY
            continue
        best, second = (None, 0), 0
        kv, dv = orb.detectAndCompute(fr, None)
        if dv is not None and len(kv) >= 10:
            for pg, (kp, de) in enumerate(pdesc):
                if de is None or len(kp) < 10:
                    continue
                m = sorted(bf.match(dv, de), key=lambda x: x.distance)
                good = [x for x in m if x.distance < 60][:200]
                if len(good) < 8:
                    continue
                src = np.float32([kv[x.queryIdx].pt for x in good]).reshape(-1, 1, 2)
                dst = np.float32([kp[x.trainIdx].pt for x in good]).reshape(-1, 1, 2)
                try:
                    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
                    inl = int(mask.sum()) if mask is not None else 0
                except cv2.error:
                    inl = 0
                if inl > best[1]:
                    second, best = best[1], (pg, inl)
                elif inl > second:
                    second = inl
        last = {"t": t, "page": best[0], "inliers": best[1], "second": second, "diff": round(diff, 1)}
        samples.append(last)
        t += ORB_EVERY
    proc.wait()
    res = {"every_s": ORB_EVERY, "samples": samples, "seconds": round(time.time() - t0, 1)}
    jdump(res, out)
    return res


# ---------------------------------------------------------------- audio windows
def transcript_windows(transcript, size=30):
    cues = transcript.get("cues") or []
    if not cues:
        return []
    end = max(b for _, b, _ in cues)
    wins = []
    for s in range(0, int(end) + 1, size):
        txt = " ".join(t for a, b, t in cues if a < s + size and b > s)
        wins.append({"start": s, "end": s + size, "text": txt})
    return wins


# ---------------------------------------------------------------- stage: fuse
def stage_fuse(w, meta, ocr, visual, transcript, extra_decks=None, applause=None, chrome=None, clef=None,
               out_name="timeline.json"):
    """Timeline over seconds, possibly across several decks (a deck switch splits the
    timeline, never the video; presenters may share a Q&A). State space = every page of every deck + 'no slide'.
    Within a deck: stay 0, forward 3, back 25. Switching decks: 30, or 8 within 60 s of applause."""
    out = os.path.join(w, out_name)
    if os.path.exists(out):
        return jload(out)
    clef = clef or {"screen": {}, "page": {}}
    evidence_log = []                            # what triggered each piece of evidence 
    deck_paths = [meta["deck"]["path"]] + [d["path"] for d in (extra_decks or [])]
    # words of the recording's own title are the session's topic: on every slide and web page, so no evidence (seen in calibration)
    topic = frozenset(x for x in ctokens(tokens(meta["video"]["title"])) if len(x) >= 4) - {"file", "webm", "ogv"}
    texts, deck_of, local, phr, words, frags, sizes, deck_sizes = [], [], [], [], [], [], [], []
    for di, path in enumerate(deck_paths):
        tx, sz = deck_text(path)
        sizes.append(sz[0])
        texts += tx
        deck_of += [di] * len(tx)
        local += list(range(1, len(tx) + 1))
        deck_sizes.append(len(tx))
        phr += page_phrases(tx, topic=topic)      # distinctiveness judged within each deck
        words += page_words(tx)
        frags += page_fragments(tx, topic=topic)
    NP, T = len(texts), int(math.ceil(meta["duration_s"]))
    P = NP + 1                                   # last state = "no slide"
    n_main = deck_of.count(0)
    page_vocab = [{x for x in ctokens(tokens(tx)) if len(x) >= 4} for tx in texts]
    lowcov_frames, endcard_frames = [], []
    END_WORDS = {"questions", "question", "thank", "thanks"}
    end_pages = [pg for pg, tx in enumerate(texts) if END_WORDS & set(tokens(tx))]
    E = np.zeros((T, P), np.float32)
    ocr_ev = np.full((T, P), False)
    aud_ev = np.full((T, P), False)
    vis_ev = np.full((T, P), False)
    spk_ev = np.full((T, P), False)              # slide phrase spoken aloud
    browser_frames, notdeck_frames = [], []
    minutes = {}
    for f in ocr["frames"]:
        t = int(f["t"])
        hits = [(pg, contiguous_hits(ph, f["tokens"])) for pg, ph in enumerate(phr)]
        hits = [(pg, h) for pg, h in hits if h]
        a, b = max(0, t - OCR_EVERY // 2), min(T, t + OCR_EVERY // 2 + 1)
        content = [x for x in ctokens(f["tokens"]) if len(x) >= 4]
        chrome_s = (chrome or {}).get("scores", {}).get(str(t))
        # by sight only where a screen with text was actually read: on speaker close-ups the brightest region is a
        # wall or a face and its edge looks busy (e.g. 49 % "browser" without any screen in shot)
        n_content = len([x for x in ctokens(f["tokens"]) if len(x) >= 4 and x != "|"])
        cs = clef["screen"].get(str(t)) or {}
        clef_none = cs.get("none", 0) + cs.get("blank", 0) >= 0.7
        clef_browser = cs.get("browser", 0) >= 0.7
        by_sight = ((chrome_s is not None and chrome_s >= 15 and n_content >= 10) or clef_browser) \
            and not hits and not clef_none
        if clef_browser and not any(len(h) >= 2 for _, h in hits):
            by_sight = True
        if (browser_score(f["tokens"]) >= 2 or by_sight) and not any(len(h) >= 3 for _, h in hits):
            # a web page shares vocabulary with slides (e.g. portal text vs 'education program'); the browser
            # wins unless one slide matches with three or more distinct phrases
            E[a:b, NP] += 25
            ocr_ev[a:b, NP] = True
            browser_frames.append(t)
            continue                             # its text is not slide evidence
        # closing card ("Questions?", "Thank you"): show the deck page that carries it; names/addresses read on
        # screen pick between decks (e.g. another presenter's end slide), otherwise a weak pull to the only one
        if END_WORDS & set(f["tokens"]) and not any(len(h) >= 2 for _, h in hits) and end_pages:
            ftok = {x for x in f["tokens"] if len(x) >= 4} - END_WORDS - GENERIC
            scored = sorted(((len(ftok & page_vocab[pg]), pg) for pg in end_pages), reverse=True)
            if scored[0][0] >= 1:
                E[a:b, scored[0][1]] += 12
                ocr_ev[a:b, scored[0][1]] = True
                endcard_frames.append(t)
                continue
            if len(end_pages) == 1:
                E[a:b, end_pages[0]] += 4
                endcard_frames.append(t)
                continue
        # coverage: on a real slide most readable words on screen are on that slide; a web page that shares one
        # phrase with a slide does not (e.g. 'For Program Leaders' on the portal vs slide 12)
        cset = {x for x in content if x != "|"}
        if len(cset) >= 20 and hits:
            cov = max(len(cset & page_vocab[pg]) / len(cset) for pg, _ in hits)
            if cov < 0.2:
                lowcov_frames.append(t)
                if chrome_s is not None and chrome_s >= 15:     # browser by sight + text not on any slide:
                    E[a:b, NP] += 25                            # the screen wins over the speaker's words (a calibration talk)
                    ocr_ev[a:b, NP] = True
                    browser_frames.append(t)
                else:
                    notdeck_frames.append(t)
                continue
        if (len(content) >= 25 and not hits) or (
                ({"questions", "question"} & set(f["tokens"]) or " thank you " in " " + " ".join(f["tokens"]) + " ")
                and not any(strong(h) for _, h in hits)):
            notdeck_frames.append(t)
        for pg, h in hits:
            E[a:b, pg] += 10 * len(h)
            if strong(h):
                ocr_ev[max(0, t - 20):min(T, t + 21), pg] = True
            evidence_log.append({"t": t, "kind": "ocr", "deck": deck_of[pg] + 1, "page": local[pg],
                                 "matched": [" ".join(q) for q in h], "strong": strong(h),
                                 "screen_text": " ".join(x for x in f["tokens"] if x != "|")[:300]})
        for pg, fr in enumerate(frags):           # zoomed-in fragments of one slide
            fh = raw_hits(fr, f["tokens"])
            if fh:
                E[a:b, pg] += 6 * len(fh)
                if len(fh) >= 2 or any(sum(map(len, p)) >= 9 for p in fh):
                    ocr_ev[max(0, t - 20):min(T, t + 21), pg] = True
        m = minutes.setdefault(t // 60, {"minute": t // 60, "pages": {}})
        for pg, h in hits:
            m["pages"].setdefault(f"{deck_of[pg]}:{local[pg]}", set()).update(" ".join(p) for p in h)
    for t in notdeck_frames:                     # needs two OCR frames in a row (seen in calibration)
        if t - OCR_EVERY in notdeck_frames or t + OCR_EVERY in notdeck_frames:
            a, b = max(0, t - OCR_EVERY // 2), min(T, t + OCR_EVERY // 2 + 1)
            E[a:b, NP] += 15
            aud_ev[a:b, NP] = True               # "not in deck" marker for the no-slide state
    for win in transcript_windows(transcript):
        wt = set(tokens(win["text"]))
        scores = sorted(((len(ws & wt), pg) for pg, ws in enumerate(words)), reverse=True)
        if scores and scores[0][0] >= 3 and scores[0][0] >= (scores[1][0] if len(scores) > 1 else 0) + 2:
            a, b = min(T, win["start"]), min(T, win["end"])
            E[a:b, scores[0][1]] += 1.0           # weak on purpose: word overlap must not drive the deck backwards (seen in calibration)
            aud_ev[a:b, scores[0][1]] = True
    # spoken slide phrases, per transcript line (pairs of consecutive lines): the speaker reads a slide's
    # distinctive word pair aloud ("the lack of a local chapter", a calibration talk). Per line, not per 30-s window: a window
    # often spans two slides and the tie cancelled the evidence.
    cues = transcript.get("cues") or []
    for i in range(len(cues)):
        s0, e0 = cues[i][0], cues[min(i + 1, len(cues) - 1)][1]
        txt = cues[i][2] + " " + (cues[i + 1][2] if i + 1 < len(cues) else "")
        ph_hits = sorted(((len(contiguous_hits(ph, tokens(txt))), pg) for pg, ph in enumerate(phr)), reverse=True)
        if ph_hits and ph_hits[0][0] >= 1 and ph_hits[0][0] > (ph_hits[1][0] if len(ph_hits) > 1 else 0):
            a, b = max(0, int(s0) - 5), min(T, int(e0) + 15)
            E[a:b, ph_hits[0][1]] += 2.5 * ph_hits[0][0]
            aud_ev[a:b, ph_hits[0][1]] = True
            spk_ev[a:b, ph_hits[0][1]] = True
            g = ph_hits[0][1]
            evidence_log.append({"t": int(s0), "kind": "spoken", "deck": deck_of[g] + 1, "page": local[g],
                                 "matched": [" ".join(q) for q in contiguous_hits(phr[g], tokens(txt))],
                                 "speech": txt[:300]})
    # CLEF page choice (vision model; only asked where text and geometry were weak): frame + 3 candidates
    vis2_ev = np.full((T, P), False)
    gidx = {(deck_of[g] + 1, local[g]): g for g in range(NP)}
    for ts, pc in clef["page"].items():
        if "probs" not in pc:
            continue
        best = max(pc["probs"], key=pc["probs"].get)
        if best == "none" or pc["probs"][best] < 0.55:
            continue
        d, pg_ = pc["candidates"][int(best[4:]) - 1]
        g = gidx.get((d, pg_))
        if g is None:
            continue
        t = int(ts)
        a, b = max(0, t - OCR_EVERY // 2), min(T, t + OCR_EVERY // 2 + 1)
        E[a:b, g] += 12 * pc["probs"][best]
        vis2_ev[a:b, g] = True
        evidence_log.append({"t": t, "kind": "vision", "deck": d, "page": pg_, "p": round(pc["probs"][best], 2),
                             "candidates": pc["candidates"]})
    # Image matching (main deck only) certifies nothing on its own (GUARDRAILS 6-7): margin over the runner-up,
    # and ignore a page that "wins" most frames (a texture-rich photo slide matches everything).
    wins = {}
    for s in visual["samples"]:
        if s["page"] is not None:
            wins[s["page"]] = wins.get(s["page"], 0) + 1
    n_win = max(1, sum(wins.values()))
    degenerate = {p for p, c in wins.items() if n_main > 5 and c / n_win > 0.35}
    for s in visual["samples"]:
        if s["page"] is None or s["page"] in degenerate:
            continue
        a, b = int(s["t"]), min(T, int(s["t"]) + ORB_EVERY)
        margin_ok = s["inliers"] >= 1.5 * max(s.get("second", 0), 1)
        if s["inliers"] >= 15 and margin_ok:
            E[a:b, s["page"]] += 2 * min(s["inliers"] / 30.0, 2.0)
            vis_ev[a:b, s["page"]] = True
        elif s["inliers"] >= 10 and margin_ok:
            E[a:b, s["page"]] += 0.5
    # builds / animations (near-identical consecutive pages; PowerPoint animations vanish in the PDF):
    # page k+1 contains >= 80 % of page k's words -> same slide in steps. Ties go to the fuller page, and moving
    # inside the group is cheap in both directions.
    builds = []
    for g in range(NP - 1):
        if deck_of[g] == deck_of[g + 1] and page_vocab[g] and len(page_vocab[g] & page_vocab[g + 1]) >= 0.8 * len(page_vocab[g]) \
                and len(page_vocab[g + 1]) >= len(page_vocab[g]):
            builds.append((g, g + 1))
            E[:, g + 1] += 0.15 * np.clip(E[:, g], 0, None)
    # transitions
    dk = np.array(deck_of + [-1])
    same = dk[:, None] == dk[None, :]
    trans = np.full((P, P), 30.0, np.float32)    # switching decks
    fwd = np.triu(np.ones((P, P), bool), 1)
    loc = np.array(local + [0])
    jump = np.abs(loc[None, :] - loc[:, None])
    trans[same & fwd] = 3.0 + np.minimum(jump[same & fwd] - 1, 20) * 1.0   # skipping slides costs more (a calibration talk)
    trans[same & ~fwd] = 25.0
    for g, h in builds:
        trans[g, h] = trans[h, g] = 1.0
    trans[:, NP] = 3.0                           # into "no slide"
    trans[NP, :] = 25.0                          # out of "no slide": never cheaper than a direct jump (a calibration talk escape)
    np.fill_diagonal(trans, 0.0)
    trans_app = trans.copy()
    trans_app[~same] = np.minimum(trans_app[~same], 8.0)
    np.fill_diagonal(trans_app, 0.0)
    near_app = np.zeros(T, bool)
    for s0, e0, _ in (applause or []):
        near_app[max(0, int(s0) - 60):min(T, int(e0) + 60)] = True
    E[~(ocr_ev[:, NP] | aud_ev[:, NP]), NP] -= 0.02
    score = E[0] - 0.01 * np.arange(P)
    score[n_main:NP] -= 5                        # a talk starts in its main deck
    back = np.zeros((T, P), np.int32)
    for t in range(1, T):
        cand = score[:, None] - (trans_app if near_app[t] else trans)
        back[t] = np.argmax(cand, axis=0)
        score = cand[back[t], np.arange(P)] + E[t]
    path = np.zeros(T, np.int32)
    path[-1] = int(np.argmax(score))
    for t in range(T - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    labels = []
    for t in range(T):
        p = path[t]
        labels.append(("live_browser" if ocr_ev[t, NP] else "not_in_deck") if p == NP else
                      "confirmed" if ocr_ev[t, p] else "vision" if vis2_ev[t, p] else "audio" if aud_ev[t, p]
                      else "visual" if vis_ev[t, p] else "unverified")
    # after the talk (seen in calibration): once the deck has reached its last pages, more than 3 minutes without any slide
    # evidence means the room has moved on (workshop, discussion): no slide from 60 s after the last evidence
    # strong evidence only (text on screen or a slide phrase spoken aloud), not loose word overlap: in a
    # workshop people keep using the talk's vocabulary
    on_path = np.array([path[t] < NP and (ocr_ev[t, path[t]] or spk_ev[t, path[t]]) for t in range(T)])
    strong_ev = on_path                          # strong evidence for the slide actually shown
    # the deck counts as finished only after 5 min and a quarter of the recording (e.g. a spoken phrase at 1:38
    # matched a late slide and turned 40 % into "talk over"; a calibration talk's workshop starts at 39 %)
    at_end = [t for t in range(T) if t >= max(300, T // 4) and strong_ev[t]
              and local[path[t]] >= deck_sizes[deck_of[path[t]]] - 2]
    after_dbg = {"end_pages": [f"{deck_of[x]}:{local[x]}" for x in end_pages]}
    if at_end:
        later = np.nonzero(strong_ev[at_end[0]:])[0]
        last_ev = at_end[0] + int(later.max()) if len(later) else at_end[0]
        after_dbg.update(t_end=at_end[0], last_ev=last_ev, last_page=f"{deck_of[path[last_ev]]}:{local[path[last_ev]]}"
                         if path[last_ev] < NP else "none")
        if T - last_ev > 180 and int(path[last_ev]) not in end_pages:   # Q&A under the deck's own end slide stays
            for t in range(min(T, last_ev + 60), T):
                path[t] = NP
                labels[t] = "after_talk"
        # after the deck's end was reached, falling back 3+ slides without text read on screen is the room
        # discussing the talk (a calibration talk workshop naming the women again), not the presenter going back
        t_end = at_end[0]
        top = local[path[t_end]]
        # if the deck's own end slide ("Questions?") was read on screen, the Q&A happens under it (seen in calibration)
        shown_end = [pg for pg in end_pages if deck_of[pg] == deck_of[path[t_end]] and ocr_ev[:, pg].any()]
        for t in range(t_end, T):
            p_ = int(path[t])
            if p_ < NP and deck_of[p_] == deck_of[path[t_end]]:
                if ocr_ev[t, p_]:
                    top = max(top, local[p_])
                elif local[p_] <= top - 3:
                    if shown_end and t > int(np.nonzero(ocr_ev[:, shown_end[0]])[0].min()):
                        path[t] = shown_end[0]
                        labels[t] = "unverified"
                    else:
                        path[t] = NP
                        labels[t] = "after_talk"
    segs = []
    for t in range(T):
        p = int(path[t])
        key = (0, 0, labels[t]) if p == NP else (deck_of[p], local[p], labels[t])   # page 0 = no slide
        if segs and (segs[-1]["deck"], segs[-1]["page"], segs[-1]["label"]) == key:
            segs[-1]["end"] = t + 1
        else:
            segs.append({"start": t, "end": t + 1, "deck": key[0], "page": key[1], "label": key[2]})
    share = {k: round(sum(1 for x in labels if x == k) / T, 3) for k in COLORS}
    deck_share = {str(di): round(sum(1 for t in range(T) if path[t] != NP and deck_of[path[t]] == di) / T, 3)
                  for di in range(len(deck_paths))}
    mins = [{"minute": m["minute"], "confirmed_pages": {k: sorted(v) for k, v in m["pages"].items()}}
            for m in sorted(minutes.values(), key=lambda x: x["minute"])]
    res = {"pages": n_main, "page_size": sizes[0], "decks": deck_paths, "deck_page_sizes": sizes,
           "deck_share": deck_share, "duration_s": meta["duration_s"], "segments": segs, "share": share,
           "ocr_minutes": mins, "browser_frames": browser_frames, "not_in_deck_frames": notdeck_frames,
           "after_talk_debug": after_dbg, "evidence_log": evidence_log, "clef_schema": clef.get("schema"), "builds": [f"{deck_of[g]}:{local[g]}-{local[h]}" for g, h in builds], "low_coverage_frames": lowcov_frames, "end_card_frames": endcard_frames, "applause": applause or [],
           "method": "Viterbi over seconds across decks; emissions OCR phrases 10/hit, fragments 6/hit, audio 1/s, "
                     "ORB 2*min(inl/30,2); within deck stay 0, forward 3, back 25; deck switch 30 (8 near applause); "
                     "no-slide in 3, out 12"}
    jdump(res, out)
    return res


# ---------------------------------------------------------------- stage: evidence
def composite(video_png, page_png, out_png, label, h=420):
    a, b = cv2.imread(video_png), cv2.imread(page_png)
    fit = lambda im: cv2.resize(im, (int(im.shape[1] * h / im.shape[0]), h)) if im is not None else np.zeros((h, 600, 3), np.uint8)
    a, b = fit(a), fit(b)
    canvas = np.full((h + 46, a.shape[1] + b.shape[1] + 12, 3), 18, np.uint8)
    canvas[46:, :a.shape[1]] = a
    canvas[46:, a.shape[1] + 12:] = b
    cv2.putText(canvas, label[:150], (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (240, 240, 240), 1, cv2.LINE_AA)
    cv2.putText(canvas, "VIDEO FRAME", (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 220, 160), 1, cv2.LINE_AA)
    cv2.putText(canvas, "DECK PAGE", (a.shape[1] + 20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 200, 240), 1, cv2.LINE_AA)
    imwrite_atomic(out_png, canvas)


def stage_evidence(w, key, meta, ocr, timeline):
    out = os.path.join(w, "evidence.json")
    if os.path.exists(out):
        return jload(out)
    d = os.path.join(w, "evidence")
    os.makedirs(d, exist_ok=True)
    texts, _ = deck_text(meta["deck"]["path"])
    phr = page_phrases(texts)
    records, last = [], None
    with pymupdf.open(meta["deck"]["path"]) as doc:
        for f in ocr["frames"]:
            best = max(((pg, contiguous_hits(ph, f["tokens"])) for pg, ph in enumerate(phr)), key=lambda x: len(x[1]))
            if not strong(best[1]) or best[0] == last:
                continue
            last = best[0]
            stamp = f"{int(f['t'])//60:02d}m{int(f['t'])%60:02d}s"
            pre = os.path.join(d, f"{stamp}_p{best[0]+1:02d}")
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{f['t']:.1f}", "-i", meta["video"]["path"],
                 "-frames:v", "1", "-vf", "scale=960:-2", pre + "_video.png"])
            page = doc[best[0]]
            page.get_pixmap(matrix=pymupdf.Matrix(900 / page.rect.width, 900 / page.rect.width)).save(pre + "_page.png")
            composite(pre + "_video.png", pre + "_page.png", pre + "_evidence.png",
                      f"{key} | {stamp} | deck page {best[0]+1} | phrases: {', '.join(' '.join(p) for p in best[1][:3])}")
            records.append({"t": f["t"], "page": best[0] + 1, "phrases": [" ".join(p) for p in best[1]],
                            "files": [os.path.basename(pre) + s for s in ("_video.png", "_page.png", "_evidence.png")]})
    res = {"records": records, "caveat": "evidence confirms A deck for this video; the video may use more than one deck"}
    jdump(res, out)
    return res


# ---------------------------------------------------------------- stage: review screenshots (for human review)
def _ascii(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _transcript_strip(cues, t, header, width=1600, line=26):
    import textwrap
    rows, marked = [], False
    for s, e, txt in cues:
        if e < t - 20 or s > t + 20:
            continue
        if s >= t and not marked:
            rows.append(("---------------- moment of the screenshot ----------------", "now"))
            marked = True
        stamp = f"[{int(s)//60:02d}:{int(s)%60:02d}] "
        for i, part in enumerate(textwrap.wrap(_ascii(txt), 118) or [""]):
            rows.append(((stamp if i == 0 else " " * len(stamp)) + part, "text"))
    if not marked:
        rows.append(("---------------- moment of the screenshot ----------------", "now"))
    img = np.full((26 + line * (len(rows) + 1), width, 3), 24, np.uint8)
    cv2.rectangle(img, (0, 0), (width, 36), (255, 255, 255), -1)
    cv2.putText(img, header + "   |   transcript 20 s before and after", (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                (0, 0, 0), 2, cv2.LINE_AA)
    for i, (txt, kind) in enumerate(rows, start=1):
        cv2.putText(img, txt, (12, 34 + line * i), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                    (0, 220, 255) if kind == "now" else (235, 235, 235), 2 if kind == "now" else 1, cv2.LINE_AA)
    return img


def select_points(timeline, dur, n=25, seed=0):
    """Stratified evaluation points : slide changes +/-5 s (up to 8), one point in every
    no-slide stretch (up to 5), low-confidence stretches (unverified/visual, up to 6), and a random control
    filling the rest (>= 6). Points at least 4 s apart. Returns sorted [(t, stratum)]."""
    import random
    rng = random.Random(seed)
    segs = timeline["segments"]
    pts = []

    def add(t, stratum):
        t = min(max(t, 2.0), dur - 2.0)
        if all(abs(t - u) >= 4 for u, _ in pts):
            pts.append((round(t, 1), stratum))

    changes = [s["start"] for p_, s in zip(segs, segs[1:])
               if (p_.get("deck", 0), p_["page"]) != (s.get("deck", 0), s["page"])]
    for t in rng.sample(changes, min(8, len(changes))):
        add(t + rng.choice((-5, 5)), "transition")
    noslide = [s for s in segs if s["page"] == 0 and s["end"] - s["start"] >= 10]
    for s in rng.sample(noslide, min(5, len(noslide))):
        add(rng.uniform(s["start"] + 2, s["end"] - 2), "no_slide")
    low = [s for s in segs if s["label"] in ("unverified", "visual") and s["end"] - s["start"] >= 10]
    for s in rng.sample(low, min(6, len(low))):
        add(rng.uniform(s["start"] + 2, s["end"] - 2), "low_confidence")
    tries = 0
    while len(pts) < n and tries < 2000:
        add(rng.uniform(5, max(6, dur - 5)), "random")
        tries += 1
    return sorted(pts[:n])


def stage_review(w, key, meta, timeline, transcript, n=25, seed=20261019):
    """n random moments: video frame + the slide panel the timeline shows + transcript of 20 s before and after,
    each burned with a clear id '<talk>-R<nn>' (random review set)."""
    out_dir = os.path.join(w, "review")
    done = os.path.join(out_dir, "review.json")
    if os.path.exists(done):
        return jload(done)
    os.makedirs(out_dir, exist_ok=True)
    import random
    dur = meta["duration_s"]
    points = select_points(timeline, dur, n, seed + int(key[:2]))
    times = [t for t, _ in points]
    strata = {t: st for t, st in points}
    pw, ph = timeline["page_size"]
    W = int(round(PANEL_H * pw / ph / 2) * 2)
    decks = timeline.get("decks", [meta["deck"]["path"]])
    docs = [pymupdf.open(p) for p in decks]
    talk = int(key[:2])
    items = []
    try:
        for i, t in enumerate(times, start=1):
            rid = f"{talk:02d}-R{i:02d}"
            seg = next((s for s in timeline["segments"] if s["start"] <= t < s["end"]), timeline["segments"][-1])
            vid, pan = os.path.join(out_dir, "_v.png"), os.path.join(out_dir, "_p.png")
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.1f}", "-i", meta["video"]["path"], "-frames:v", "1",
                 "-vf", f"scale=-2:{PANEL_H}", vid])
            di = seg.get("deck", 0)
            panel_png(docs[di], seg["page"], seg["label"], W, PANEL_H, pan,
                      deck_tag=f"Deck {di + 1}  |  " if len(docs) > 1 and seg["page"] else "")
            img = np.hstack([cv2.imread(vid), cv2.imread(pan)])
            img = cv2.resize(img, (1600, int(img.shape[0] * 1600 / img.shape[1])))
            mmss = f"{int(t)//60:02d}:{int(t)%60:02d}"
            cv2.putText(img, mmss, (14, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3, cv2.LINE_AA)
            (sw, th), _ = cv2.getTextSize(rid, cv2.FONT_HERSHEY_SIMPLEX, 2.4, 7)
            x, y = 20, img.shape[0] - 30
            cv2.rectangle(img, (x - 12, y - th - 18), (x + sw + 12, y + 18), (0, 0, 0), -1)
            cv2.putText(img, rid, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 2.4, (255, 255, 255), 7, cv2.LINE_AA)
            full = np.vstack([img, _transcript_strip(transcript.get("cues") or [], t,
                                                     f"{rid}   |   talk #{talk}   |   {mmss}")])
            name = f"{rid}.jpg"
            imwrite_atomic(os.path.join(out_dir, name), full, [cv2.IMWRITE_JPEG_QUALITY, 82])
            items.append({"id": rid, "file": name, "t": round(t, 1), "deck": di + 1, "page": seg["page"],
                          "label": seg["label"], "stratum": strata.get(t, "random"), "verdict": ""})
            os.remove(vid)
            os.remove(pan)
    finally:
        for d in docs:
            d.close()
    write_atomic(os.path.join(out_dir, "review.csv"), "id,time_s,deck,page,label,stratum,verdict,note\n" + "".join(
        f"{it['id']},{it['t']},{it['deck']},{it['page']},{it['label']},{it['stratum']},,\n" for it in items))
    res = {"talk": int(key[:2]), "n": len(items), "items": items,     # talk number only (a field named "key" trips secret scanners)
           "how_to_review": "For each id: right slide / wrong slide / wrong deck / browser / no slide / unsure, in review.csv"}
    jdump(res, done)
    return res


# ---------------------------------------------------------------- stage: render
def panel_png(doc, page_no, label, W, H, path, deck_tag=""):
    bar = 44
    if page_no == 0:                             # live browser: no slide at all
        canvas = np.full((H, W, 3), 30, np.uint8)
        canvas[H - bar:, :] = COLORS[label]
        cv2.putText(canvas, LABEL_TEXT[label], (14, H - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
        imwrite_atomic(path, canvas)
        return
    page = doc[page_no - 1]
    z = min(W / page.rect.width, (H - bar) / page.rect.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z))
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)
    canvas = np.full((H, W, 3), 255, np.uint8)
    y0, x0 = (H - bar - img.shape[0]) // 2, (W - img.shape[1]) // 2
    canvas[y0:y0 + img.shape[0], x0:x0 + img.shape[1]] = img
    canvas[H - bar:, :] = COLORS[label]
    cv2.putText(canvas, f"{deck_tag}Slide {page_no} of {len(doc)}  |  {LABEL_TEXT[label]}", (14, H - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
    imwrite_atomic(path, canvas)


def encoder():
    enc = run(["ffmpeg", "-hide_banner", "-encoders"]).stdout
    if "h264_videotoolbox" in enc:
        return ["-c:v", "h264_videotoolbox", "-b:v", "2M", "-maxrate", "2.5M", "-bufsize", "5M"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "2M", "-bufsize", "4M"]


def stage_render(w, key, meta, timeline):
    out = os.path.join(w, f"{key}.mp4")
    rj = os.path.join(w, "render.json")
    if os.path.exists(out) and os.path.exists(rj):
        return jload(rj)                         # resumed after the render: same record as the first time
    pw, ph = timeline["page_size"]
    W = int(round(PANEL_H * pw / ph / 2) * 2)
    t0 = time.time()
    if not os.path.exists(out):                  # else: killed between the rename and render.json; measure it again
        _render(w, meta, timeline, out, W)
    dur = probe_duration(out)
    res = {"file": out, "seconds": round(time.time() - t0, 1), "duration_s": dur,
           "duration_ok": abs(dur - meta["duration_s"]) <= 2, "mb": round(os.path.getsize(out) / 1e6, 1), "panel_w": W}
    jdump(res, rj)
    shutil.rmtree(os.path.join(w, "media", "panels"), ignore_errors=True)
    return res


def _render(w, meta, timeline, out, W):
    pdir = os.path.join(w, "media", "panels")
    os.makedirs(pdir, exist_ok=True)
    lst = os.path.join(pdir, "list.txt")
    lines, last = [], None
    docs = [pymupdf.open(p) for p in timeline.get("decks", [meta["deck"]["path"]])]
    try:
        for s in timeline["segments"]:
            di = s.get("deck", 0)
            png = os.path.join(pdir, f"d{di}_p{s['page']:03d}_{s['label']}.png")
            if not os.path.exists(png):
                tag = f"Deck {di + 1}  |  " if len(docs) > 1 and s["page"] else ""
                panel_png(docs[di], s["page"], s["label"], W, PANEL_H, png, deck_tag=tag)
            lines += [f"file '{png}'", f"duration {s['end'] - s['start']:.3f}"]
            last = png
    finally:
        for d in docs:
            d.close()
    lines.append(f"file '{last}'")
    with open(lst, "w") as f:
        f.write("\n".join(lines) + "\n")
    t0 = time.time()
    fc = (f"[0:v]scale=-2:{PANEL_H},setsar=1,fps=25[v];"
          f"[1:v]scale={W}:{PANEL_H},setsar=1,fps=25[s];"
          f"[v][s]hstack=inputs=2,format=yuv420p[out]")
    run(["ffmpeg", "-y", "-v", "error", "-i", meta["video"]["path"], "-f", "concat", "-safe", "0", "-i", lst,
         "-filter_complex", fc, "-map", "[out]", "-map", "0:a?", *encoder(), "-c:a", "aac", "-b:a", "96k",
         "-t", f"{meta['duration_s']:.3f}", "-movflags", "+faststart", out + ".part.mp4"])
    os.replace(out + ".part.mp4", out)
