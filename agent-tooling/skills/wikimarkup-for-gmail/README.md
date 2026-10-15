# WikiMarkup for Gmail

Wikimedians type wikitext out of habit. When you type `[[Article]]`, `''italic''`, `'''bold'''` or `~~~~` in a Gmail draft, this
extension notices, waits until you pause, and asks whether to turn it into a link to **your** wiki or
**your** signature. Nothing changes without a click.

Load-unpacked Chrome extension (Manifest V3). No store listing, no build step, no dependencies.

⚠️ **Use at your own risk.**
- This is an unofficial, personal tool, not a Wikimedia Foundation product, and not in the Chrome Web Store.
- It has not been extensively tested: it was tried by hand in Gmail on one computer, plus automated tests on a mock-up of Gmail's compose window.
- Gmail changes its page often, and an update can break the extension without warning.
- Always read your email before sending it. If you click Send within a few seconds of typing, the popup may not have appeared yet and the markup goes out as typed.
- Provided as-is under the MIT licence, with no warranty or support.

## How to install it (no technical knowledge needed)

It works in **Google Chrome** on a computer (also Edge, Brave and other Chrome-based browsers).
It does not work on phones or tablets. It takes about five minutes.

**1. Download it**

1. Click this link: **[download WikiMarkup for Gmail](https://github.com/lgelauff/wikimedia-coding-agent-lessons/releases/latest/download/wikimarkup-for-gmail.zip)**.
   A small file called `wikimarkup-for-gmail.zip` lands in your Downloads.
2. Double-click that file to unzip it. You now have a folder called **`wikimarkup-for-gmail`** —
   that is the extension.
3. Drag that folder to a place where it can stay, for example your Documents folder.
   Keep it there: Chrome runs the extension from that folder, so deleting it removes the extension.

**2. Add it to Chrome**

1. In Chrome, click the address bar, type `chrome://extensions` and press Enter.
2. In the top-right corner, switch on **Developer mode**.
3. In the top-left corner, click **Load unpacked**.
4. Find the `wikimarkup-for-gmail` folder from step 1, click it once, and click **Select**.
5. "WikiMarkup for Gmail" now appears in the list. Chrome may show a notice about extensions in
   developer mode; that is normal for extensions that do not come from the Chrome Web Store.

**3. Fill in your settings**

A settings page opens by itself. (Later you can find it again by clicking the puzzle-piece icon
next to the address bar, then **WikiMarkup for Gmail**.)

1. **Home wiki** — the wiki your links should point to, e.g. `en.wikipedia.org` or `nl.wikipedia.org`.
2. **Signature** — copy it from your wiki preferences, e.g.
   `[[User:YourName|YourName]] ([[User talk:YourName|talk]])`.
3. **Timestamp** — pick your time zone, date style and language.
4. Click **Save**, then reload any open Gmail tab.

**4. Try it**

Write an email in Gmail and type `see [[Amsterdam]]`. Stop typing for a few seconds: a small box
appears next to the email asking whether to convert it. Click **Convert**. Nothing in your email
changes unless you click.

**Updating** — download the zip again, replace your `wikimarkup-for-gmail` folder with the new one,
go to `chrome://extensions` and click the round arrow on the WikiMarkup for Gmail card.

**Removing** — go to `chrome://extensions` and click **Remove** on the WikiMarkup for Gmail card.

**Privacy** — it only looks at what you type in an email you are writing, and only in Gmail. It
never reads your other mail and sends nothing anywhere — except when you use the optional
*paste as wikitext* shortcut, which sends what you copied to your own home wiki to convert it.

## Settings in detail

On first install the options page opens by itself and asks:

1. **Your home wiki** — the host that bare links resolve against, e.g. `nl.wikipedia.org`.
   *Check this wiki* reads the wiki's `siteinfo` to confirm the host is real.
2. **Your signature** — wikitext, e.g. `[[User:Example|Example]] ([[User talk:Example|talk]])`.
   Put `~~~~~` inside it to place the timestamp yourself, as a wiki signature preference does.

3. **Timestamp** — set up like MediaWiki's own preferences: a **time zone** (UTC, your browser's zone,
   or any named zone), a **date format** (MediaWiki's four: `16:12, 15 January 2001`,
   `16:12, January 15, 2001`, `16:12, 2001 January 15`, `2001-01-15T16:12:23`) and the **language** for
   month names (`nl` → `15 oktober 2026`). The defaults (UTC, first format, English) match MediaWiki's.
   The zone is written as MediaWiki does where the browser knows the abbreviation (`CEST`, `EDT`);
   otherwise as an offset (`UTC+9` where MediaWiki would write `JST`). Worked out locally, nothing looked up.

Settings live in `chrome.storage.sync` and apply to open Gmail tabs straight away.
The toolbar button opens the settings.

## How it decides — when, and on what

**What counts:** only markup you *type* in a Gmail compose body, during this draft.

* A link counts the moment you type its closing `]]`; `''italic''` and `'''bold'''` on their closing quotes.
  These only count when the text between the markers is plain — no formatting, line break or existing
  link in between.
* A tilde run (`~~~`, `~~~~`, `~~~~~`) counts once you type the next character, press Enter, or pause.
  Longer runs — a `~~~~~~~~` separator line — never count.
* Never considered: quoted or forwarded mail (`.gmail_quote`, `blockquote`), your Gmail signature block,
  text that was already in the draft, pasted text, and a token you edited after typing it.

Each token is remembered as a live DOM Range at the moment you type it, so later edits elsewhere in the
draft don't confuse it.

**When it asks:** after you stop typing for *N* seconds (setting, default 3), or as soon as focus leaves
the message body (e.g. you move to the subject or recipients). A popup next to the compose box lists each
token and what it becomes, e.g. `[[Amsterdam]] → link to nl.wikipedia.org/wiki/Amsterdam`, or for
`~~~~` the actual signature and time: `~~~~ → Lodewijk (overleg) 13:30, 15 oktober 2026 (CEST)`. That
time is frozen when the popup appears, so what you approve is exactly what is inserted. It never takes
keyboard focus, so you can keep typing; new tokens are added to the list.

* **Convert** — converts the listed tokens; later tokens in this draft will ask again.
* **Convert all in this draft** — converts, and converts later tokens at each pause without asking.
* **Not in this draft** — leaves them alone and stops watching this draft.
* **Esc** — dismisses this batch; later tokens will ask again.

The setting *Permission → never ask* converts at each pause without a popup.

**Known gap:** if you click **Send** within the pause after typing, Gmail sends before the popup can
appear, and the markup goes out as typed. The extension does not intercept Send.

## What it converts

Links, bold and italic **keep their markup**: only the text between the markers gains a link or style,
so `[[Amsterdam]]` stays `[[Amsterdam]]` with `Amsterdam` clickable, and the draft still pastes back into
a wiki unchanged. Tildes are replaced, as on a wiki.

Typed in a draft | Result (mode: *link*) | Result (mode: *keep as wikitext*)
--- | --- | ---
`[[Amsterdam]]` | `Amsterdam` links to `https://<home wiki>/wiki/Amsterdam`, brackets kept | not offered
`''very''` / `'''very'''` | `very` in italic / bold, quotes kept | not offered
`[[Amsterdam\|Amsterdam by night]]` | link, label shown | not offered
`[[Amsterdam#History]]` | link to the section | not offered
`[[c:Category:Amsterdam]]` | link to Commons | not offered
`[[d:Foo]]` | Wikidata · `m:` Meta · `mw:` mediawiki.org · `s:` Wikisource · `species:` Wikispecies | not offered
`[[w:nl:Amsterdam]]` | `nl.wikipedia.org` (as on a wiki, `w:` alone is English) | not offered
`[[nl:Amsterdam]]` | interlanguage link — only for a *lowercase* 2–3 letter prefix | not offered
`[[WP:NPOV]]`, `[[MOS:BOLD]]`, `[[Category:Foo]]` | home-wiki page (shortcut or namespace) | not offered
`~~~` | your username only — the first link in your signature (a wiki gives the full signature) | same, as text
`~~~~` | signature + `16:42, 14 October 2026 (UTC)` | same, as text
`~~~~~` | timestamp only | timestamp only

Titles are percent-encoded the way MediaWiki does it (`[[What?]]` → `/wiki/What%3F`).

Hotkeys inside a draft (Alt = Option on a Mac; matched on the physical key, so they work on macOS):
`Alt+Shift+W` ask now about what you typed · `Alt+Shift+S` insert signature + timestamp ·
`Alt+Shift+T` insert timestamp · `Alt+Shift+P` paste the clipboard as wikitext.

### Paste as wikitext (`Alt+Shift+P`)

Copied HTML is converted to wikitext by your **home wiki's** Parsoid endpoint and inserted as plain text:

```
POST https://<home wiki>/w/rest.php/v1/transform/html/to/wikitext/Main_Page
Content-Type: application/x-www-form-urlencoded       # text/html returns 415
html=<p>…</p>&body_only=true
```

This is the only time anything leaves the browser: the copied HTML goes to your home wiki, and nowhere
else. If that wiki cannot convert it, you get an error — there is no fallback to another wiki.


## Tests

* `npm test` — the pure logic (`node --test`): timestamps, tilde semantics, token completion,
  separator lines, interwiki and shortcut resolution, title encoding, settings migration.
* `test/mock-compose.html?run` — the browser suite (`test/mechanism.js`) on a Gmail-shaped compose box,
  driving the same `attachWikiMarkup()` and popup: typing via real `input` events, pause and focus-out
  timing, quoted and pre-existing text left alone, all popup choices, Esc, pasted and edited tokens,
  wikitext mode, macOS hotkeys, empty-line insertion. Open it in any browser via a static server, or run
  `node test/mechanism.spec.mjs` with Playwright installed.
* `node test/extension-load.spec.mjs` — Chrome loads the unpacked extension (needs Playwright).

**Real Gmail: tested by hand** (2026-10-15), and it works. No automated test types into an actual Gmail
compose window, so a Gmail change can still break it. If it does, the coupling points are
`COMPOSE_SELECTOR` and `EXCLUDE_SELECTOR` in `src/lib/compose.js`.

## Files

```
manifest.json                 MV3 manifest: mail.google.com content script, storage + clipboardRead
src/lib/wikitext.js           pure logic — parsing, interwiki, signatures, timestamps, token completion
src/lib/compose.js            DOM helpers — caret text, live token Ranges, conversion, insertion
src/lib/consent.js            the popup
src/lib/triggers.js           what counts and when to ask (typing, pause, focus-out, hotkeys)
src/content.js                Gmail glue: settings, toasts, paste-as-wikitext
src/background.js             first-run setup, toolbar button, the Parsoid transform call
src/options.html|js           settings and a live preview
test/                         unit tests, Gmail-shaped harness + in-page suite, Playwright runners
```

MIT licensed. Contributions to an earlier version by Fuzheado's WikiButler.
