import test from 'node:test';
import assert from 'node:assert/strict';

import {
  mediawikiTimestamp, expandTildes, render, findCompletedToken, wikiUrl, parseWikiLink,
  normalizeHomeWiki, normalizeSettings, describeToken, renderToken, DEFAULT_SETTINGS,
} from '../src/lib/wikitext.js';

const NL = { ...DEFAULT_SETTINGS, homeWiki: 'nl.wikipedia.org', mode: 'link',
             signature: '[[User:Lodewijk|Lodewijk]] ([[User talk:Lodewijk|talk]])' };

test('timestamp matches MediaWiki formatting', () => {
  assert.equal(mediawikiTimestamp(new Date('2026-10-14T16:42:00Z')), '16:42, 14 October 2026 (UTC)');
  // day is not zero-padded, like MediaWiki
  assert.equal(mediawikiTimestamp(new Date('2026-10-04T09:05:00Z')), '09:05, 4 October 2026 (UTC)');
});

test('timestamps follow time zone, date format and language preferences', () => {
  const summer = new Date('2026-10-15T11:30:00Z');
  const winter = new Date('2026-01-15T11:30:00Z');
  const ts = (d, s) => mediawikiTimestamp(d, s);
  assert.equal(ts(summer, {}), '11:30, 15 October 2026 (UTC)', 'defaults = MediaWiki defaults');
  assert.equal(ts(summer, { timeZone: 'Europe/Amsterdam' }), '13:30, 15 October 2026 (CEST)');
  assert.equal(ts(winter, { timeZone: 'Europe/Amsterdam' }), '12:30, 15 January 2026 (CET)');
  assert.equal(ts(summer, { timeZone: 'America/New_York' }), '07:30, 15 October 2026 (EDT)');
  assert.equal(ts(summer, { timeZone: 'Asia/Kolkata' }), '17:00, 15 October 2026 (UTC+5:30)');
  assert.equal(ts(summer, { timeZone: 'Asia/Tokyo' }), '20:30, 15 October 2026 (UTC+9)');
  // the date changes with the zone
  assert.equal(ts(new Date('2026-10-15T23:30:00Z'), { timeZone: 'Asia/Tokyo' }), '08:30, 16 October 2026 (UTC+9)');
  assert.equal(ts(summer, { dateFormat: 'mdy' }), '11:30, October 15, 2026 (UTC)');
  assert.equal(ts(summer, { dateFormat: 'ymd' }), '11:30, 2026 October 15 (UTC)');
  assert.equal(ts(summer, { dateFormat: 'iso' }), '2026-10-15T11:30:00 (UTC)');
  assert.equal(ts(summer, { language: 'nl', timeZone: 'Europe/Amsterdam' }), '13:30, 15 oktober 2026 (CEST)');
  assert.equal(ts(summer, { language: 'pl' }), '11:30, 15 października 2026 (UTC)');
  assert.equal(ts(summer, { timeZone: 'Not/AZone', language: 'xx-nonsense-123' }), '11:30, 15 October 2026 (UTC)');
});

test('popup shows the signature as a reader sees it, with the real time', () => {
  const now = new Date('2026-10-15T11:30:00Z');
  const s = { ...NL, timeZone: 'Europe/Amsterdam', language: 'nl' };
  assert.equal(describeToken({ kind: 'tildes', raw: '~~~~' }, s, now), 'Lodewijk (talk) 13:30, 15 oktober 2026 (CEST)');
  assert.equal(describeToken({ kind: 'tildes', raw: '~~~~~' }, s, now), '13:30, 15 oktober 2026 (CEST)');
  assert.equal(normalizeSettings({ timeZone: 'Mars/Base' }).timeZone, 'UTC');
  assert.equal(normalizeSettings({ timeZone: 'browser' }).timeZone, 'browser');
});

test('home wiki normalisation', () => {
  assert.equal(normalizeHomeWiki('https://nl.wikipedia.org/w/index.php?title=X'), 'nl.wikipedia.org');
  assert.equal(normalizeHomeWiki('NL.Wikipedia.org'), 'nl.wikipedia.org');
  assert.equal(normalizeHomeWiki(''), DEFAULT_SETTINGS.homeWiki);
});

test('tilde expansion follows MediaWiki semantics', () => {
  const now = new Date('2026-10-14T16:42:00Z');
  assert.equal(expandTildes('~~~', NL, now), '[[User:Lodewijk|Lodewijk]]', '~~~ is the username only');
  assert.equal(expandTildes('~~~', { ...NL, signature: 'just text' }, now), 'just text');
  assert.equal(expandTildes('~~~', { ...NL, signature: '— [[Gebruiker:L|L]] (~~~~~)' }, now), '[[Gebruiker:L|L]]');
  assert.equal(expandTildes('~~~~', NL, now),
    '[[User:Lodewijk|Lodewijk]] ([[User talk:Lodewijk|talk]]) 16:42, 14 October 2026 (UTC)');
  assert.equal(expandTildes('~~~~~', NL, now), '16:42, 14 October 2026 (UTC)');
  // a signature that carries its own slot gets the timestamp in place
  const slotted = { ...NL, signature: '— [[User:L]] (~~~~~)' };
  assert.equal(expandTildes('~~~~', slotted, now), '— [[User:L]] (16:42, 14 October 2026 (UTC))');
});

test('link mode turns wikitext into anchors against the home wiki', () => {
  const now = new Date('2026-10-14T16:42:00Z');
  const out = render('see [[Wikidata|WD]] and [[Amsterdam]]', NL, now).html;
  assert.match(out, /<a href="https:\/\/nl\.wikipedia\.org\/wiki\/Wikidata">WD<\/a>/);
  assert.match(out, /<a href="https:\/\/nl\.wikipedia\.org\/wiki\/Amsterdam">Amsterdam<\/a>/);
});

test('interwiki shorthands resolve to the right project', () => {
  assert.equal(wikiUrl('nl.wikipedia.org', 'c:Category:Amsterdam'),
    'https://commons.wikimedia.org/wiki/Category:Amsterdam');
  assert.equal(wikiUrl('nl.wikipedia.org', 'd:Q42'), 'https://www.wikidata.org/wiki/Q42');
  assert.equal(wikiUrl('nl.wikipedia.org', 'w:nl:Amsterdam'), 'https://nl.wikipedia.org/wiki/Amsterdam');
  assert.equal(wikiUrl('nl.wikipedia.org', 'w:Amsterdam'), 'https://en.wikipedia.org/wiki/Amsterdam');
  assert.equal(wikiUrl('nl.wikipedia.org', 'm:Wikimedia Europe'), 'https://meta.wikimedia.org/wiki/Wikimedia_Europe');
  // not an interwiki: a namespace on the home wiki
  assert.equal(wikiUrl('nl.wikipedia.org', 'Category:Foo'), 'https://nl.wikipedia.org/wiki/Category:Foo');
  assert.equal(wikiUrl('nl.wikipedia.org', 'Help:Contents'), 'https://nl.wikipedia.org/wiki/Help:Contents');
});

test('sections and labels', () => {
  const { target, label, section } = parseWikiLink('Amsterdam#Geschiedenis|history');
  assert.deepEqual({ target, label, section }, { target: 'Amsterdam', label: 'history', section: 'Geschiedenis' });
  const html = render('[[Amsterdam#Geschiedenis|history]]', NL, new Date()).html;
  assert.ok(html.includes('https://nl.wikipedia.org/wiki/Amsterdam#Geschiedenis">history</a>'), html);
});

test('output is escaped — no markup injection from a label', () => {
  const html = render('[[Foo|a & b <script>alert(1)</script>]]', NL, new Date()).html;
  assert.ok(!html.includes('<script'), 'script tag must not survive');
  assert.match(html, /a &amp; b &lt;script&gt;/);
});

test('wikitext mode leaves [[…]] exactly as typed but expands tildes', () => {
  const s = { ...NL, mode: 'wikitext' };
  const now = new Date('2026-10-14T16:42:00Z');
  const out = render('see [[Wikidata]] ~~~~', s, now);
  assert.equal(out.text,
    'see [[Wikidata]] [[User:Lodewijk|Lodewijk]] ([[User talk:Lodewijk|talk]]) 16:42, 14 October 2026 (UTC)');
});

test('completed-token detection: a link completes on ]], tildes on the next character', () => {
  assert.deepEqual(findCompletedToken('see [[Wikidata|WD]]'),
    { kind: 'wikilink', raw: '[[Wikidata|WD]]', start: 4, end: 19 });
  assert.deepEqual(findCompletedToken('thanks ~~~~ '), { kind: 'tildes', raw: '~~~~', start: 7, end: 11 });
  assert.deepEqual(findCompletedToken('x ~~~,'), { kind: 'tildes', raw: '~~~', start: 2, end: 5 });
  // still typing the run: not complete until something else follows, or typing pauses
  assert.equal(findCompletedToken('thanks ~~~~'), null);
  assert.deepEqual(findCompletedToken('thanks ~~~~', { final: true }),
    { kind: 'tildes', raw: '~~~~', start: 7, end: 11 });
  assert.equal(findCompletedToken('just prose'), null);
  assert.equal(findCompletedToken('an [[unclosed link'), null);
});

test('bold and italic complete on their closing marker, and are not confused', () => {
  assert.deepEqual(findCompletedToken("so ''very''"), { kind: 'italic', raw: "''very''", start: 3, end: 11 });
  assert.deepEqual(findCompletedToken("so '''very'''"), { kind: 'bold', raw: "'''very'''", start: 3, end: 13 });
  assert.equal(findCompletedToken("so '''very''"), null, 'half-closed bold is not italic');
  assert.equal(findCompletedToken("it's 'quoted'"), null);
  assert.equal(findCompletedToken("so ''very''", { mode: 'wikitext' }), null);
});

test('links, bold and italic keep their markup; only the inner text gains a link or style', () => {
  const tok = (raw, kind) => renderToken({ raw, kind }, NL, new Date());
  assert.equal(tok('[[Amsterdam]]', 'wikilink').html,
    '[[<a href="https://nl.wikipedia.org/wiki/Amsterdam">Amsterdam</a>]]');
  assert.equal(tok('[[Amsterdam#Geschiedenis|history]]', 'wikilink').html,
    '[[<a href="https://nl.wikipedia.org/wiki/Amsterdam#Geschiedenis">Amsterdam#Geschiedenis|history</a>]]');
  assert.equal(tok("''very''", 'italic').html, '&#39;&#39;<i>very</i>&#39;&#39;');
  assert.equal(tok("'''a <b>'''", 'bold').html, '&#39;&#39;&#39;<b>a &lt;b&gt;</b>&#39;&#39;&#39;');
  assert.equal(tok('[[|x]]', 'wikilink').html, '[[|x]]', 'empty target stays plain');
});

test('a separator line of tildes is never a token', () => {
  assert.equal(findCompletedToken('~~~~~~~~ '), null);
  assert.equal(findCompletedToken('~~~~~~~~', { final: true }), null);
  assert.equal(findCompletedToken('~~ '), null);
});

test('wikitext mode only tracks tildes', () => {
  assert.equal(findCompletedToken('see [[Wikidata]]', { mode: 'wikitext' }), null);
  assert.equal(findCompletedToken('~~~ ', { mode: 'wikitext' }).kind, 'tildes');
});

test('project shortcuts stay on the home wiki; only lowercase 2–3 letters are languages', () => {
  assert.equal(wikiUrl('en.wikipedia.org', 'WP:NPOV'), 'https://en.wikipedia.org/wiki/WP:NPOV');
  assert.equal(wikiUrl('en.wikipedia.org', 'MOS:BOLD'), 'https://en.wikipedia.org/wiki/MOS:BOLD');
  assert.equal(wikiUrl('en.wikipedia.org', 'CAT:CSD'), 'https://en.wikipedia.org/wiki/CAT:CSD');
  assert.equal(wikiUrl('en.wikipedia.org', 'wp:NPOV'), 'https://en.wikipedia.org/wiki/wp:NPOV');
  assert.equal(wikiUrl('en.wikipedia.org', 'nl:Amsterdam'), 'https://nl.wikipedia.org/wiki/Amsterdam');
  assert.equal(wikiUrl('en.wikipedia.org', 'zh-yue:X'), 'https://zh-yue.wikipedia.org/wiki/X');
});

test('titles are percent-encoded like MediaWiki does', () => {
  assert.equal(wikiUrl('en.wikipedia.org', 'What?'), 'https://en.wikipedia.org/wiki/What%3F');
  assert.equal(wikiUrl('en.wikipedia.org', '100%'), 'https://en.wikipedia.org/wiki/100%25');
  assert.equal(wikiUrl('en.wikipedia.org', 'AC/DC'), 'https://en.wikipedia.org/wiki/AC/DC');
  assert.equal(wikiUrl('nl.wikipedia.org', 'Café de Paris'), 'https://nl.wikipedia.org/wiki/Caf%C3%A9_de_Paris');
  assert.equal(wikiUrl('nl.wikipedia.org', 'c:Category:Amsterdam'),
    'https://commons.wikimedia.org/wiki/Category:Amsterdam');
});

test('popup descriptions', () => {
  assert.equal(describeToken({ kind: 'wikilink', raw: '[[Amsterdam|A]]' }, NL),
    'link to nl.wikipedia.org/wiki/Amsterdam');
});

test('0.1.0 settings migrate', () => {
  assert.equal(normalizeSettings({ permissionMode: 'session' }).permissionMode, 'ask');
  assert.equal(normalizeSettings({ permissionMode: 'always' }).permissionMode, 'always');
  assert.equal(normalizeSettings({ idleSeconds: '0' }).idleSeconds, DEFAULT_SETTINGS.idleSeconds);
  assert.equal(normalizeSettings({ idleSeconds: '5' }).idleSeconds, 5);
});
