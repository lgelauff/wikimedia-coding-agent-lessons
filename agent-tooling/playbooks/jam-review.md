# Playbook: review a Jam recording

A Jam (jam.dev) is a recording of one browser tab: a video plus everything the tab did — console
output, network requests, user actions, page and device info, and sometimes backend logs. Someone
shares a link (`https://jam.dev/c/<uuid>`) because something went wrong or looked wrong. This
playbook turns that link into a short, evidence-based finding: what happened, where it went wrong,
and what to look at next.

The order is the point: **the data before the video.** The console and the network say what the
tab actually did; the video says what the person saw and thought. Read the data first, form a
hypothesis, then use the video to confirm or refute it — not the other way round.

## 0. Get access

1. **Connector first** (Jam MCP, or `jam get …` in the Jam CLI). It returns structured data with
   server-side filters and is the cheapest route. It sees only Jams in the workspace its sign-in
   was issued for.
2. **On "not found"**, the Jam lives in another workspace. If the link is public (whoever shared it
   made it viewable), open it in a browser: the share page has a DevTools panel with Info, Console,
   Network, Actions and Backend tabs. This reads a web page, not an API, so keep it to the one
   shared link — no crawling, no other pages on the host.
3. Neither works → say so, and ask for one of: the Jam shared into the connected workspace, the
   connector signed in to the right workspace, or the link made viewable. Don't guess from the
   title.

## 1. Info — the frame (1 minute)

Page URL (which app, which environment: production, beta, local), timestamp, browser, OS, window
size, network speed, and the Jam's title or description. The title is the reporter's own words for
the problem: keep it as the question you are answering.

## 2. Console — errors first

- Filter to errors, then warnings. For each distinct error: message, source file:line, how often,
  and the first occurrence's time in the recording.
- Uncaught exceptions and failed promise rejections outrank everything else.
- Ignore noise you can name (extension messages, known third-party warnings), but say what you
  ignored.

## 3. Network — failures, then the calls that matter

- Failures first (4xx, 5xx, CORS, blocked, cache/network errors): URL path (not query values unless
  needed), method, status, timing, and the response body of failed calls.
- Then the app's own data calls (XHR/fetch) around the moment things went wrong: did a request
  succeed with the WRONG data? Read the response body (connector: `bodies: all` for that host;
  browser: open the row).
- Patterns: the same call repeated many times (a loop or retry storm), long waterfalls, a slow call
  right before the visible problem, requests to an unexpected environment.
- Classify each failure: app bug / third-party or CDN / environment (network, extension, cache) /
  expected (e.g. 404 probing).

## 4. Actions — what the person did

The click / input / navigation timeline. Line it up with the first error and the first suspicious
request: what was the last action before things went wrong? This gives you the reproduction steps.

## 5. Backend and metadata, if present

Backend logs (if the app sends them) and custom metadata (app version, user role, feature flags).
These often name the exact version or flag that matters.

## 6. The video — confirm, don't discover

Only now: the transcript (if the reporter spoke) and the video, at the timestamps steps 2–4
pointed to. Does what's on screen match the hypothesis? What did the person expect to see? Note
anything visible that the data didn't show (a layout or wording problem has no console trace).

## 7. Write the finding

```
Jam: <link> · <app + environment> · <date>
Question: <the reporter's problem, in one line>

What happened (timeline): <mm:ss action> → <mm:ss error/request> → <mm:ss visible effect>
Evidence:
  - console: <error, file:line, count>            [confirmed: Jam console]
  - network: <METHOD path → status, what was wrong> [confirmed: Jam network]
  - video:   <what was on screen at mm:ss>          [confirmed: video]
Likely cause: <one or two sentences>                [concluded: from …] / [guess]
Reproduce: 1. … 2. … 3. … (expected … / actual …)
Not explained by the data: <anything left over>
Next: <the code to read, the test to write, or the question for the reporter>
```

Label every claim confirmed / concluded / guess. Give mm:ss timestamps so a reader can jump there.

## Privacy

Whoever shares a Jam knows it carries personal details (names, emails, tokens in headers, other
people on screen) and accepts that. Still, write down only what the analysis needs: paths over
full URLs with query values, error text over request bodies, "a logged-in organiser" over a name.
Never copy a token, cookie or authorization header into any output, issue or commit message.

## Hand-offs

- Need to reproduce it live → the browser-verify playbook.
- It's a bug worth tracking → draft an issue from the finding (shown to the user first; nothing is
  posted without their yes).
- It's a bug worth fixing → write the failing test first, from the reproduction steps.
