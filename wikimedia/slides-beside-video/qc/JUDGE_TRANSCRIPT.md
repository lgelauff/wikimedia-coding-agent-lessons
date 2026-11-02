# Judging instructions: transcript vs slide

You judge whether what a speaker says at one moment of a talk fits a given slide. You see the speaker's words
(an automatic transcript, 20 s before to 20 s after the moment, with the moment marked) and one or more slide images.
There is no video frame: the camera never showed the screen in this talk. Judge from the words and the slides only.

Your batch file (JSON) lists items. Each item has:
- `words`: transcript lines `[mm:ss] text`, with a line `>>> MOMENT <<<` where the moment falls.
- `refs`: slide image paths.
- `q`:
  - `q = "page"`: `refs` is ONE slide. Question: **at the marked moment, is the speaker talking about what is on this
    slide**, so that this slide is the one a viewer should see now?
  - `q = "deck"`: `refs` are contact sheets with ALL slides of the deck. Question: **at the marked moment, is the
    speaker presenting one of these slides** (as opposed to an introduction, questions from the room, chat, or a part
    not covered by any slide)?

Answer per item, one of:
- `yes`: the words at the moment clearly fit (for `deck`: clearly belong to one of the slides). Quotes, names, numbers or
  topics on the slide that the speaker names or paraphrases count as evidence. A speaker who is clearly in the middle of
  the topic of the slide counts as `yes` even if they do not repeat its words.
- `no`: the words clearly fit something else: another topic, another slide's content, an introduction or a Q&A that the
  slide does not cover.
- `unmeasurable`: the words do not decide it: too short, too general (e.g. "thank you", a joke, applause), or they fit
  this slide and other slides equally well.

Be strict: a slide whose general theme matches the whole talk is not evidence for this moment. Say `yes` only when this
moment's words point to this slide more than to the deck in general.

Also give:
- `topic`: max ~8 words, what the speaker is talking about at the moment.
- `reason`: max ~20 words, the concrete evidence ("speaker quotes Cicero, slide shows the Cicero quote", "speaker
  answers an audience question about edit counts; slide is a quote about history").

## How to work
1. Read the batch file.
2. Look at the slide images with the Read tool. Many items share slides: read each distinct image once, at the start,
   all in one message (parallel Read calls), and reuse what you saw.
3. Write your answers as a JSON array to the output path you were given, one object per item:
   `[{"id": "...", "answer": "yes|no|unmeasurable", "topic": "...", "reason": "..."}, ...]`
   Every item id must appear exactly once. Write valid JSON with the Write tool.
4. Reply with one line only: `done <n> items`.

Do not open any other files, do not search the web, do not run shell commands.
