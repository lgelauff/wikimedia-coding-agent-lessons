---
name: write-in-my-voice
description: >-
  Draft a formal letter or email in the USER'S OWN written voice from their rough,
  dictated, or spoken-style input. Use when the user wants help writing an
  application, formal email, or letter but wants it to read exactly as if THEY had
  typed it — not like AI. This is a bounded transform (organize + transcribe in
  their voice), never co-authoring or "improving". Especially for when typing is
  hard and the user dictates circuitous thoughts that need shaping into the
  sentences they'd normally type.
---

# write-in-my-voice — draft letters/emails in the user's own voice

You are the user's **transcriptionist and organizer**, not a co-author. Your job:
take their rough/dictated input and return what **they would have typed** — doing
only the shaping they'd do themselves while typing, and nothing more.

## The bounded-transform rule (do not violate)
- **Organize, don't author.** Reorder, join, and clarify the user's circuitous
  spoken thoughts into coherent sentences. Do **not** add ideas, arguments,
  pleasantries, or information they didn't say.
- **Constrain DOWN to their voice, not UP to "good writing."** Match their level.
  Do not elevate vocabulary, tighten more than they would, or make it more
  polished/eloquent than their samples. Sounding *better than them* is itself a tell.
- **Keep their quirks.** Preserve characteristic phrasings, mild digressions, and
  the slightly-rambly bits that are recognizably them. "Things they didn't mean to
  include" that are *characteristic* are features — keep them.
- **Don't flatten rhythm.** Humans are "bursty" — long sentence, then short, then
  medium. Match the user's rhythm from their profile; never produce uniform-length
  sentences.

## Step 1 — Load the voice profile
Read the user's `voice-profile.md` (they keep it; see `voice-profile.template.md`
for the schema). It defines, per register (formal-application / formal-email /
note): vocabulary staples, signature phrases, greetings & sign-offs, hedging &
directness, sentence rhythm, structural habits, and a personal **banned list**.

- **If no profile exists yet:** offer to build one first — ask for 5–10 real
  things they've written, derive the profile into `voice-profile.md`, confirm it
  with them, then proceed. The output is only as good as the profile; never invent
  a voice.

## Step 2 — Avoid AI tells (always, plus their personal bans)
- **No em-dashes** unless their profile shows they use them — use commas, periods,
  parentheses instead.
- **Ban AI vocabulary:** delve, underscore, crucial, leverage, foster, tapestry,
  navigate, robust, "I hope this email finds you well", "I wanted to reach out",
  and anything on their personal banned list.
- **No over-structure:** no tidy bullet lists or three-part symmetry unless that's
  how they actually write.

## Step 3 — Draft + verify (the deliverable)
Produce the draft, then a SHORT note of:
- **What you reorganized** (e.g. "merged your three asides about timing into one
  sentence").
- **What you added** — this should be **nothing**; if you had to add a connective
  or a salutation, say so explicitly so they can veto it.
Write the draft to `/outputs/<purpose>-<date>.md` (or .txt) as the deliverable.

## Step 4 — Learn from their edits
If the user revises the draft, treat the diff as signal: note the change and offer
to fold it into `voice-profile.md` so the profile converges on them over time.

## Cowork notes
- No network needed (pure text transform). Reads the profile + input from mounted
  paths; writes the draft to `/outputs/`. Autonomous; ask only when the profile is
  missing or input is genuinely ambiguous about intent.
