/**
 * WikiMarkup for Gmail — pure logic.
 *
 * No DOM, no chrome.* APIs: everything here is a pure function so it can be
 * unit-tested with `node --test` and reused by the content script, the options
 * page and the browser harness.
 *
 * Two output modes:
 *   'link'     -> wikitext becomes HTML (anchors) for a mail going to a person
 *   'wikitext' -> tildes expand, [[...]] is left exactly as typed, so the draft
 *                 can be pasted into a wiki edit box unchanged
 */

export const INTERWIKI = {
  c: 'https://commons.wikimedia.org/wiki/',
  d: 'https://www.wikidata.org/wiki/',
  m: 'https://meta.wikimedia.org/wiki/',
  mw: 'https://www.mediawiki.org/wiki/',
  s: 'https://wikisource.org/wiki/',
  species: 'https://species.wikimedia.org/wiki/',
  w: 'https://en.wikipedia.org/wiki/',
};

export const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/**
 * Lowercase 2–3 letter prefixes that are project shortcuts, not language codes.
 * Uppercase prefixes (WP:, MOS:, CAT:) are never read as languages at all.
 */
const NOT_A_LANGUAGE = new Set(['wp', 'wt', 'mos', 'cat']);

export const DEFAULT_SETTINGS = {
  homeWiki: 'en.wikipedia.org',
  signature: '[[User:Example|Example]] ([[User talk:Example|talk]])',
  mode: 'link',            // 'link' | 'wikitext'
  idleSeconds: 3,          // ask once typing has paused this long (or the body loses focus)
  showPreview: true,       // show the small toast after an action
  permissionMode: 'ask',   // 'ask' (popup) | 'always' (convert silently)
  timeZone: 'UTC',         // 'UTC' | 'browser' | an IANA zone such as 'Europe/Amsterdam'
  dateFormat: 'dmy',       // a key of DATE_FORMATS
  language: 'en',          // month names, e.g. 'nl' -> "oktober"
};

/** Settings stored by 0.1.0 used 'draft' / 'session'; both mean "ask" now. */
export function normalizeSettings(s) {
  const out = { ...DEFAULT_SETTINGS, ...s };
  if (out.permissionMode !== 'always') out.permissionMode = 'ask';
  const idle = Number(out.idleSeconds);
  out.idleSeconds = Number.isFinite(idle) && idle >= 1 && idle <= 30 ? idle : DEFAULT_SETTINGS.idleSeconds;
  if (!isTimeZone(out.timeZone)) out.timeZone = DEFAULT_SETTINGS.timeZone;
  if (!DATE_FORMATS[out.dateFormat]) out.dateFormat = DEFAULT_SETTINGS.dateFormat;
  out.language = String(out.language ?? '').trim() || DEFAULT_SETTINGS.language;
  if (!isLanguage(out.language)) out.language = DEFAULT_SETTINGS.language;
  return out;
}

/* ------------------------------------------------------------------ basics */

/** 'nl.wikipedia.org' | 'https://nl.wikipedia.org/w/index.php' -> 'nl.wikipedia.org' */
export function normalizeHomeWiki(input) {
  let s = String(input ?? '').trim();
  if (!s) return DEFAULT_SETTINGS.homeWiki;
  s = s.replace(/^https?:\/\//i, '').replace(/\/.*$/, '');
  return s.toLowerCase();
}

export function homeWikiBase(homeWiki) {
  return `https://${normalizeHomeWiki(homeWiki)}/wiki/`;
}

/* -------------------------------------------------------------- timestamps */

/**
 * The date formats MediaWiki offers under Preferences → Appearance → Date format
 * (shown with its own example date).
 */
export const DATE_FORMATS = {
  dmy: '16:12, 15 January 2001',
  mdy: '16:12, January 15, 2001',
  ymd: '16:12, 2001 January 15',
  iso: '2001-01-15T16:12:23',
};

/** 'browser' -> the browser's own zone; anything else is an IANA zone name. */
export function resolveTimeZone(tz) {
  if (tz === 'browser') return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  return isTimeZone(tz) ? tz : 'UTC';
}

export function isTimeZone(tz) {
  if (tz === 'UTC' || tz === 'browser') return true;
  try { new Intl.DateTimeFormat('en', { timeZone: tz }); return true; } catch { return false; }
}

export function isLanguage(lang) {
  try { return Intl.DateTimeFormat.supportedLocalesOf([String(lang)]).length > 0; } catch { return false; }
}

/**
 * Short zone name for the "(…)" after the time, like MediaWiki's "(UTC)" / "(CEST)".
 * Intl only knows some abbreviations (CEST via en-GB, EDT via en-US); for the
 * rest it gives an offset, written as "UTC+9" / "UTC+5:30".
 */
export function zoneAbbreviation(date, timeZone) {
  if (timeZone === 'UTC' || timeZone === 'Etc/UTC') return 'UTC';
  let fallback = 'UTC';
  for (const locale of ['en-GB', 'en-US']) {
    const name = new Intl.DateTimeFormat(locale, { timeZone, timeZoneName: 'short' })
      .formatToParts(date).find((p) => p.type === 'timeZoneName')?.value ?? '';
    if (name && !/^(GMT|UTC)/.test(name)) return name;
    if (name) fallback = name.replace(/^GMT/, 'UTC');
  }
  return fallback === 'UTC+0' || fallback === 'UTC' ? 'UTC' : fallback;
}

/**
 * A signature timestamp, the way MediaWiki writes one: "16:42, 14 October 2026 (UTC)".
 * Time zone, date format and language come from the settings, as MediaWiki's
 * user preferences do; the defaults reproduce MediaWiki's (UTC, dmy, English).
 */
export function mediawikiTimestamp(date = new Date(), settings = {}) {
  const timeZone = resolveTimeZone(settings.timeZone ?? 'UTC');
  const lang = isLanguage(settings.language) ? settings.language : 'en';
  const format = DATE_FORMATS[settings.dateFormat] ? settings.dateFormat : 'dmy';
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).map((p) => [p.type, p.value]));
  const zone = zoneAbbreviation(date, timeZone);
  if (format === 'iso') {
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second} (${zone})`;
  }
  // the month in its "in a date" form (Polish "października", not "październik")
  const month = lang === 'en' ? MONTHS[Number(parts.month) - 1]
    : new Intl.DateTimeFormat(lang, { timeZone, day: 'numeric', month: 'long' })
      .formatToParts(date).find((p) => p.type === 'month')?.value ?? MONTHS[Number(parts.month) - 1];
  const day = Number(parts.day);                       // not zero-padded, like MediaWiki
  const time = `${parts.hour}:${parts.minute}`;
  const dateText = { dmy: `${day} ${month} ${parts.year}`, mdy: `${month} ${day}, ${parts.year}`,
                     ymd: `${parts.year} ${month} ${day}` }[format];
  return `${time}, ${dateText} (${zone})`;
}

export function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** [[Page|label]] inner text -> { target, label, section } */
export function parseWikiLink(inner) {
  const [beforeLabel, ...labelParts] = String(inner).split('|');
  const label = labelParts.length ? labelParts.join('|') : null;
  const hash = beforeLabel.indexOf('#');
  const target = hash === -1 ? beforeLabel : beforeLabel.slice(0, hash);
  const section = hash === -1 ? null : beforeLabel.slice(hash + 1);
  return { target: target.trim(), label: label === null ? null : label.trim(), section };
}

/**
 * Resolve a wikitext target against the user's home wiki.
 * Handles the interwiki shorthands Wikimedians actually type: c:, d:, m:, mw:,
 * s:, species:, w:, and w:xx: for another language Wikipedia.
 */
export function wikiUrl(homeWiki, target) {
  const t = String(target || '').replace(/ /g, '_');
  const m = /^([A-Za-z][A-Za-z0-9-]{0,11}):(.*)$/.exec(t);
  if (m) {
    const typed = m[1];
    const prefix = typed.toLowerCase();
    const rest = m[2];
    if (prefix === 'w') {                       // w:            -> enwiki
      const inner = /^([a-z]{2,12}(?:-[a-z]+)?):(.*)$/.exec(rest);
      if (inner) return `https://${inner[1]}.wikipedia.org/wiki/${titlePath(inner[2])}`;   // w:nl:Page
      return INTERWIKI.w + titlePath(rest);
    }
    if (INTERWIKI[prefix]) return INTERWIKI[prefix] + titlePath(rest);           // c: d: m: mw: s: species:
    // nl:Page (interlanguage) — only as typed in lowercase, so WP:NPOV stays on the home wiki
    if (/^[a-z]{2,3}(?:-[a-z]+)?$/.test(typed) && !NOT_A_LANGUAGE.has(typed)) {
      return `https://${typed}.wikipedia.org/wiki/${titlePath(rest)}`;
    }
  }
  return homeWikiBase(homeWiki) + titlePath(t); // Category:Foo, Help:Contents, WP:NPOV, plain titles
}

/** Percent-encode a title the way MediaWiki's wfUrlencode does (keeps : / @ $ , ;). */
export function titlePath(title) {
  return encodeURIComponent(String(title).replace(/ /g, '_'))
    .replace(/%(3A|2F|40|24|2C|3B)/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
}

/* -------------------------------------------------------------- signatures */

/**
 * MediaWiki tilde semantics, applied to a user-supplied signature.
 *    ~~~  username only (first link of the signature)
 *    ~~~~ signature + timestamp (timestamp goes where '~~~~~' sits, if the
 *         signature contains it — that is how MediaWiki preference signatures work)
 *    ~~~~~ timestamp only
 */
export function expandTildes(text, settings = DEFAULT_SETTINGS, now = new Date()) {
  const sig = String(settings.signature ?? DEFAULT_SETTINGS.signature);
  const ts = mediawikiTimestamp(now, settings);
  const hasSlot = sig.includes('~~~~~');
  const sigOnly = hasSlot ? sig.replace(/~~~~~/g, '').trim() : sig;
  const sigWithTime = hasSlot ? sig.replace(/~~~~~/g, ts).trim() : `${sigOnly} ${ts}`.trim();
  return String(text)
    .replace(/~~~~~/g, ts)
    .replace(/~~~~/g, sigWithTime)
    .replace(/~~~/g, usernameFromSignature(sigOnly));
}

/**
 * What ~~~ gives: just your username — the first link in the signature
 * ("[[User:Lodewijk|Lodewijk]]"), or the whole signature if it has no link.
 * (On a wiki ~~~ is the full signature without timestamp; here it is shorter on purpose.)
 */
export function usernameFromSignature(sig) {
  return /\[\[[^[\]\n]+\]\]/.exec(String(sig))?.[0] ?? String(sig);
}

/* ------------------------------------------------------- wikitext -> output */

const LINK_RE = /\[\[([^[\]\n|]*(?:\|[^[\]\n]*)?)\]\]/g;

/** 'link' mode: [[Target|label]] -> <a href="…">label</a> */
/** Where [[inner]] points, or null for an empty target. */
export function wikiLinkHref(inner, settings) {
  const { target, section } = parseWikiLink(inner);
  if (!target) return null;
  let href = wikiUrl(settings.homeWiki, target);
  if (section) href += '#' + encodeURIComponent(section.replace(/ /g, '_'));
  return href;
}

export function wikiLinkToHtml(inner, settings) {
  const { target, label } = parseWikiLink(inner);
  const href = wikiLinkHref(inner, settings);
  if (!href) return escapeHtml(`[[${inner}]]`);
  const text = label === null ? target : label;
  return `<a href="${escapeHtml(href)}">${escapeHtml(text)}</a>`;
}

/**
 * Main entry point for turning typed text into what should be inserted.
 * Returns { html, text } — the caller picks the field it needs.
 */
export function render(text, settings = DEFAULT_SETTINGS, now = new Date()) {
  const withTime = expandTildes(text, settings, now);
  if (settings.mode === 'wikitext') {
    return { html: escapeHtml(withTime).replace(/\n/g, '<br>'), text: withTime };
  }
  // 'link' mode: convert every [[…]] to an anchor, tildes already expanded
  let out = '';
  let last = 0;
  for (const m of withTime.matchAll(LINK_RE)) {
    out += escapeHtml(withTime.slice(last, m.index));
    out += wikiLinkToHtml(m[1], settings);
    last = m.index + m[0].length;
  }
  out += escapeHtml(withTime.slice(last));
  return { html: out.replace(/\n/g, '<br>'), text: withTime };
}

/* ------------------------------------------------------------- caret tokens */

/**
 * Tokens that complete the moment their closing marker is typed. The inner text
 * may not contain the marker characters, and '' / ''' must not touch another
 * apostrophe, so '''bold''' is never mistaken for ''italic''.
 */
const FORMAT_TOKENS = [
  ['wikilink', /\[\[([^[\]\n]{1,200})\]\]$/],
  ['bold', /(?<!')'''([^'\n]{1,200})'''$/],
  ['italic', /(?<!')''([^'\n]{1,200})''$/],
];
const MARKERS = { wikilink: ['[[', ']]'], bold: ["'''", "'''"], italic: ["''", "''"] };

/**
 * What a completed token becomes. Links, bold and italic keep their markup as
 * typed and only the inner text gains a link or style — the draft's text stays
 * exactly what you typed, so it still pastes back into a wiki unchanged.
 *   [[Amsterdam|A]]  ->  [[<a href="…/Amsterdam">Amsterdam|A</a>]]
 *   '''bold'''       ->  '''<b>bold</b>'''
 * Tildes are replaced by the signature / timestamp, as on a wiki.
 */
export function renderToken(token, settings = DEFAULT_SETTINGS, now = new Date()) {
  if (token.kind === 'tildes') return render(token.raw, settings, now);
  const [open, close] = MARKERS[token.kind];
  const inner = token.raw.slice(open.length, -close.length);
  let html;
  if (token.kind === 'wikilink') {
    const href = wikiLinkHref(inner, settings);
    if (!href) return { html: escapeHtml(token.raw), text: token.raw };
    html = `<a href="${escapeHtml(href)}">${escapeHtml(inner)}</a>`;
  } else {
    const tag = token.kind === 'bold' ? 'b' : 'i';
    html = `<${tag}>${escapeHtml(inner)}</${tag}>`;
  }
  return { html: escapeHtml(open) + html + escapeHtml(close), text: token.raw };
}

/**
 * Has the user just finished typing a token? `s` is the text before the caret.
 * Returns { kind, raw, start, end } with offsets into `s`, or null.
 *
 *   '… [[Wikidata|WD]]'  -> wikilink, complete the moment ']]' is typed
 *   '… ~~~~ '            -> tildes, complete once a non-tilde follows the run
 *   '… ~~~~'  (final)    -> tildes at the very end, used when typing pauses
 *
 * A run of more than five tildes (a separator line) is never a token.
 * In 'wikitext' mode only tildes count: links are meant to stay as typed.
 */
export function findCompletedToken(s, { final = false, mode = 'link' } = {}) {
  s = String(s ?? '');
  if (mode !== 'wikitext') {
    for (const [kind, re] of FORMAT_TOKENS) {
      const m = re.exec(s);
      if (m) return { kind, raw: m[0], start: s.length - m[0].length, end: s.length };
    }
  }
  const re = final ? /(?:^|[^~])(~{3,5})$/ : /(?:^|[^~])(~{3,5})[^~]$/;
  const t = re.exec(s);
  if (!t) return null;
  const end = final ? s.length : s.length - 1;
  return { kind: 'tildes', raw: t[1], start: end - t[1].length, end };
}

/** Wikitext as a reader sees it: [[a|b]] -> b, [[a]] -> a, ''x'' / '''x''' -> x. */
export function wikiToPlain(text) {
  return String(text)
    .replace(/\[\[([^[\]|\n]*)\|([^[\]\n]*)\]\]/g, '$2')
    .replace(/\[\[([^[\]\n]*)\]\]/g, '$1')
    .replace(/'''(.+?)'''/g, '$1')
    .replace(/''(.+?)''/g, '$1');
}

/** One line for the popup: what this token will become (signatures shown in full, with the real time). */
export function describeToken(token, settings = DEFAULT_SETTINGS, now = new Date()) {
  if (token.kind === 'tildes') {
    const text = expandTildes(token.raw, settings, now);
    return settings.mode === 'wikitext' ? text : wikiToPlain(text);
  }
  if (token.kind === 'bold') return 'bold';
  if (token.kind === 'italic') return 'italic';
  const href = wikiLinkHref(token.raw.slice(2, -2), settings);
  return href ? `link to ${href.replace(/^https:\/\//, '')}` : 'left as typed';
}
