# Judging instructions (slides beside video, quality check)

You judge whether a still frame from a conference recording shows a given slide. You see only images:
no transcript, no labels, no pipeline output. Judge from the pixels alone.

Your batch file (JSON) lists items. Each item has:
- `frame`: a still from the room camera recording (speaker, projection screen, audience, or a cut-in).
- `refs`: one or more reference images.
- `q`: the question type.
  - `q = "page"`: `refs` is ONE slide page. Question: **is this page what is shown on the projection screen
    (or full-screen cut-in) in the frame?**
  - `q = "deck"`: `refs` are contact sheets with ALL pages of the presenter's deck(s) as thumbnails.
    Question: **does the frame show any one of these pages on the screen?**

Answer per item, one of:
- `yes`: the screen visibly shows that page (for `deck`: one of the pages). A page that is the same slide at
  another animation/build step still counts as `yes` if the slide is clearly the same one (same title, same
  layout, same images). A slightly different version of the same slide (small text edits) is `yes`.
- `no`: the screen is visible enough to tell, and it shows something else: a different slide (even from the
  same deck), a browser, a demo, another program, a blank/black/blue screen, a title card, or a slide that is
  not among the pages.
- `unmeasurable`: you cannot tell from this frame: no screen in view (speaker close-up, audience, panel),
  screen too blurred / washed out / small to distinguish this page from similar ones, screen mostly blocked,
  or a black/transition frame of the video itself.

Be strict and honest. Do not guess `yes` because a page "could" be it: say `yes` only when the visible evidence
(title, layout, images, colours, readable text) fits this page and not merely the deck's general style. If the
screen shows a slide in the same style but a different title/content, say `no`. If many pages of the deck look
alike and you cannot tell which is shown, say `unmeasurable` (for `page`) — but for `deck`, `yes` is right if
it is clearly one of the deck's pages, whichever.

Also give:
- `screen`: what the frame shows: `slide` (a presentation slide is legible or recognisable), `browser`
  (web page / software / demo), `blank` (empty, black, blue or no-signal screen), `no_screen` (no projection
  in view), `unclear` (screen in view but unreadable), or `other`.
- `reason`: max ~20 words, the concrete evidence (e.g. "screen title 'Editor engagement' matches page title",
  "speaker close-up, no screen", "screen shows bar chart, page is a bullet list").

## How to work
1. Read the batch file.
2. Look at the images with the Read tool, MANY PER TURN: in each of your messages, issue the Read calls for
   all images of the next 10 items at once (about 20 parallel Read calls in one message), then judge those
   10 items in your head and move on to the next 10. Never read one image per turn: every extra turn re-sends
   all images seen so far and multiplies the cost. Contact sheets repeat across items: read each distinct
   sheet only once and reuse what you saw.
3. Write your answers as a JSON array to the output path you were given, one object per item, in any order:
   `[{"id": "...", "answer": "yes|no|unmeasurable", "screen": "...", "reason": "..."}, ...]`
   Every item id in the batch must appear exactly once. Write valid JSON with the Write tool.
4. Reply with one line only: `done <n> items`. Do not describe the items in your reply.

Do not open any other files, do not search the web, do not run shell commands.
