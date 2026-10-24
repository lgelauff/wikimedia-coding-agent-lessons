# Assign slides to a talk from its transcript

A recorded conference talk ("{TITLE}", {DURATION} long) is
going to be shown next to its slide deck. The camera never filmed the screen, so we do not know which slide was up.
Your job: from what the speaker says, decide which slide a viewer should see at each moment.

Files (in this folder):
- `transcript.txt`: automatic transcript (Whisper), one line per cue: `[mm:ss–mm:ss] text`. Expect recognition errors.
- `pages/p01.png` …: the {PAGES} deck pages, in deck order. Look at every one of them.
- `pages.txt`: the text on each page (helps with quotes and names).

Rules:
1. Cover the whole talk from 00:00 to {DURATION} without gaps or overlaps, as consecutive stretches.
2. For each stretch give the page the speaker is presenting: the slide whose content (quote, names, topic, section
   title) the speaker is talking about. Section-title slides belong at the start of their section.
3. The introduction before the first content slide gets the title page (2), unless the words point elsewhere.
   The end ("thank you", closing) gets the deck's closing page(s).
4. Use `null` (no slide) only for a stretch that no slide fits at all, e.g. a long audience discussion or Q&A that is
   not about any slide. Do not use `null` just because you are unsure; give your best page and lower the confidence.
5. If the speaker says the slides are not working or not visible, still assign the slide that fits what is said; note it.
6. Prefer the deck order, but follow the words if the speaker goes back or skips. No stretch shorter than 10 s unless the
   words clearly demand it.
7. Do not invent: every stretch needs evidence from the transcript (a quote of a few words, with its time).

Write a JSON file to the output path you were given:
```
{"segments": [{"start": "00:00", "end": "01:52", "page": 2, "confidence": "high|medium|low",
               "evidence": "[00:00] 'in this session I will talk about ...' = title"}, ...],
 "notes": "anything a reviewer should know (max ~60 words)"}
```
Times as mm:ss, from the transcript. The first start is 00:00, the last end is {DURATION}, each start equals the previous end.
Reply with one line only: `done <n> segments`. Do not open other files, do not search the web, do not run shell commands.
