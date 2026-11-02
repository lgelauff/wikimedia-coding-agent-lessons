# slides-beside-video

Puts a conference talk recording next to its slide deck. Given a talk video and its PDF deck on Wikimedia Commons,
it works out which slide is on screen at every second and renders a side-by-side MP4: the recording on the left,
the matching slide on the right, with a bar saying how sure it is. Built for Wikimania recordings, where the
projection is often filmed badly or not at all.

It also contains:
- an **agent quality check** (`qc/`) that judges the result over the whole video, from the raw frame and the chosen
  slide only, with decoy controls and a second independent judge;
- **evidence export** (`evidence/`): the transcript (SRT), OCR text and timeline of a talk, with a privacy pass
  (non-speaker names and private screens removed) before publication;
- a **timeline rebuild from the transcript** (`evidence/rebuild_timeline.py`) for talks where the camera never
  shows the screen.

Everything the tools produce is **machine-made ("silver")**. Check it before you rely on it.

## How it works
For one recording (`slides_beside_video/run.py`), each stage caches its output, so a run can be resumed:

| stage | what it does |
|---|---|
| fetch | downloads the video and deck from Commons (API metadata, checksum, licence, author) |
| transcript | Commons TimedText if present, otherwise whisper.cpp (5-min chunks) |
| ocr / refine | tesseract on a screen crop every 30 s, plus extra frames where neighbours disagree |
| discover / candidates | optional: finds the deck by content, or extra decks of a panel, from a deck inventory |
| pair | confirms the deck against a decoy deck (phrases read on screen, spoken slide phrases) |
| visual | ORB image matching between frames and pages |
| chrome / applause | live-browser detection by sight; applause as a speaker-switch cue |
| clef | optional: Wikimedia's LiftWing `llm-clef-flash` vision model for screen type and close page choices |
| fuse | Viterbi over seconds across all evidence: page per second, or "no slide" (browser, not in deck, talk over) |
| render | ffmpeg side-by-side MP4 with an evidence bar per segment |
| review / sidecar | 25 random review screenshots; provenance JSON (sources, licences, evidence shares) |

Evidence labels: `confirmed` (slide text read in the frame), `audio` (the speaker's words match the slide),
`visual` (image match), `vision` (vision model), `unverified` (best guess), plus no-slide states, and
`transcript_agent` / `transcript_none` for timelines rebuilt from the transcript.

## Inputs and licences
- **Recordings and decks: Wikimedia Commons.** Each file keeps its own licence (for Wikimania mostly CC BY or
  CC BY-SA); `fetch` records licence and author per file, and the sidecar carries them. A render derived from a
  CC BY-SA input is CC BY-SA too; credit both authors.
- **Transcripts:** Commons TimedText (CC BY-SA) when it exists, otherwise whisper.cpp output.
- **Vision model (optional):** LiftWing `llm-clef-flash` (`api.wikimedia.org`), anonymous and rate-limited.
  Disable it with `"clef": false`.
- **Deck inventory (optional):** your own JSON list of candidate Commons decks (format below). Without it, deck
  discovery and multi-deck detection are skipped and the deck must be given in the queue.
- Example of published outputs: the public Hugging Face bucket `Schroedinger1000/wikimania-videos`
  (`items/render/…` renders, `evidence/render/…` transcripts, OCR and timelines).

Use a descriptive User-Agent with contact details (Wikimedia's User-Agent policy), and keep downloads sequential.

## Install
System tools: ffmpeg/ffprobe (tested 8.1), tesseract (5.5.2), whisper.cpp's `whisper-cli`, curl, plus a whisper
model (tested `ggml-large-v3-turbo-q5_0.bin`).
```
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.json config.json      # set user_agent, whisper_model, work_dir
```

## Run
Queue (`queue.example.csv`): one row per recording.
- `idx`: an ID.
- `key`: `<nn>_<year>_<slug>`; the year is read from it.
- `commons_file`: the video file name.
- `deck_title`: `File:…pdf`, or empty to discover the deck by content (needs an inventory).
- `decoy_idx`: another row whose deck serves as the decoy.

```
.venv/bin/python -m slides_beside_video.run --config config.json --queue queue.example.csv --id 1
.venv/bin/python -m slides_beside_video.status --config config.json --queue queue.example.csv
```
The output is `<work_dir>/<key>/<key>.mp4`, plus `timeline.json`, `sidecar.json` and `review/`.

Options:
- `--stop-after STAGE`
- `--keep-media`
- `--redo-from fuse|chrome|chrome-keepclef`: recompute the timeline with cached inputs
- `--retry-skipped`: look for the deck by content

A deck pairing that the pipeline cannot confirm (for example when the camera never shows the screen) can be
confirmed by a person in `overrides.csv` (`decision = confirm_pair`; see `overrides.example.csv`).

### Stopping and resuming (kill-safe)
Any run can be killed at any moment (`kill -9` included) and started again with the same command:
- **Atomic outputs:** every file is written under a temporary name and renamed when complete, so a kill never leaves
  a half-written file under the real name.
- **Checksummed done markers:** each finished stage records the sha256 of its outputs in `status.json`; a resume
  checks them first and stops that recording if an output changed or disappeared, instead of building on it. The
  speech-to-text is cached per 5-minute chunk, each with its own checksum.
- **Budgets count retries:** every Commons API call, download attempt and vision-model call is charged to a ledger
  (`budget_file`, default `<work_dir>/_budget.json`) *before* it is made, so a download killed half-way still
  counts. Set caps in `budget` (`download_bytes`, `api_calls`, `clef_calls`; `null` = counted, not capped) and use a
  fresh ledger per batch. Downloads are checked against the Commons sha1 before they are kept.
- **One process per recording:** a lock file per recording; a second run on the same recording exits with code 3,
  and a lock left by a killed process is taken over.

The QC tools follow the same rules: `prepare` builds in a temporary folder, records checksums of its items and
batches, charges the download ledger before the download starts, holds a lock, and refuses a truncated verdict file.

### Agent quality check (`qc/`)
1. `python3 qc/qc.py --config config.json plan` to count the points.
2. `prepare TALK` downloads the video once, extracts a frame for every point, renders the pages, and writes blind
   batches of 30. Decoys come from other talks' decks.
3. Judging: give each batch to a vision-capable agent with `qc/JUDGE.md`. It writes `verdicts/bNNN.json`.
   We used Claude Code subagents, about 30 items and 80 s per batch.
4. `finalize TALK` writes `points.csv` (time, page, stratum, verdict, reason, silver) and `summary.md`.
5. `second.py build|finalize`: an independent second judge on all disagreements and a sample of agreements,
   with Cohen's kappa.
6. `build_index.py` builds a local `index.html` to browse every point with the frame and the slide side by side.

For talks without the screen in shot, `qc/transcript_check.py` judges transcript windows against slides instead
(`JUDGE_TRANSCRIPT.md`), with same-deck "near" decoys.

### Evidence export and timeline rebuild (`evidence/`)
- `export_evidence.py review-inputs TALK DIR`, then a privacy reviewer follows `REDACT.md` and writes
  `DIR/redact.json`, then `export TALK DIR OUT`. OUT gets `transcript.srt`, `ocr.json` and `timeline.json`, with
  names → `[name]`, private screens blanked and local paths removed.
- `rebuild_timeline.py prepare TALK DIR`, then two agents follow `DIR/ASSIGN.md` independently, then
  `compare` / `apply TALK DIR A`, then run the pipeline again to re-render.

## Hardware and time (measured on an Apple M1, 8 GB RAM)
- **Per 20–30-minute talk:**
  - download: 15 s to 7 min;
  - whisper: 1–11 min;
  - OCR and visual: about 2 min;
  - vision model: about 1.5 min, up to 90 min while rate-limited;
  - render: 2.5–4.5 min.
- **Disk:** one source video at a time (0.1–1 GB, deleted after the run unless `--keep-media`); a render is
  0.2–0.6 GB. The pipeline refuses downloads below `min_free_disk_gb` (default 12).
- **QC:** one 30-item batch took about 80 s and about 0.5 M cache-read tokens with a frontier model. 3,400 points
  over 15 talks took about 2 h of wall clock.

## Tests
`python -m unittest discover -s tests` runs offline tests: text matching, overrides, QC strata, redaction, the
rebuild and the kill-safety pieces (atomic writes, checksummed markers, locks, budget). A full dry run on one short public talk is `queue.example.csv`, id 1 ("State of GLAM in the Netherlands",
15 min). It needs about 1 GB of free disk above the floor.

## Known limits
- **Speaker close-ups:** when the camera stays on the speaker, nothing in the frame confirms the slide. The
  timeline then rests on the transcript, and frame-based QC cannot measure it.
- **Slide changes** are often a few seconds late or early. In our QC, agreement was 44 % at page changes against
  80 % elsewhere.
- **Unverified stretches** are mostly wrong where they could be checked: 21 % agreement.
- **Single-page decks** (posters) can act as magnets in multi-deck sessions.
- **Browser detection:** slides that contain browser screenshots can be taken for a live browser.
- **Deck versions:** the Commons deck may differ from the version presented. PowerPoint animations are missing from
  PDFs.
- **Languages:** tuned on English talks. Whisper detects the language per chunk.
- **Agent outputs** (QC verdicts, privacy review, rebuilt timelines) are silver. A person should spot-check them.

## Licence
The code in this folder falls under the repository's MIT licence (`LICENSE` at the repository root). The
recordings, decks and transcripts it processes keep their own Commons licences (see *Inputs and licences*).
