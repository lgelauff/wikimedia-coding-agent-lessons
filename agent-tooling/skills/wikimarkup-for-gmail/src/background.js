/**
 * Service worker: first-run setup, settings seeding, and the one network call
 * the extension makes — HTML -> wikitext via MediaWiki's Parsoid transform.
 *
 * Verified endpoint (2026-10-14, HTTP 200):
 *   POST https://en.wikipedia.org/w/rest.php/v1/transform/html/to/wikitext/Main_Page
 *   Content-Type: application/x-www-form-urlencoded   <-- text/html returns 415
 *   html=<p>…</p>&body_only=true
 *   -> "see [[Wikidata]], the [[c:Category:Amsterdam|category]] and '''bold''' text."
 */

import { DEFAULT_SETTINGS, normalizeHomeWiki } from './lib/wikitext.js';

chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());

chrome.runtime.onInstalled.addListener(async (details) => {
  const stored = await chrome.storage.sync.get(null);
  const seed = {};
  for (const [k, v] of Object.entries(DEFAULT_SETTINGS)) {
    if (stored[k] === undefined) seed[k] = v;
  }
  if (Object.keys(seed).length) await chrome.storage.sync.set(seed);
  if (details.reason === 'install') {
    // requirement (a)+(b): ask for the home wiki and a signature up front
    chrome.runtime.openOptionsPage();
  }
});

async function fetchTransform(host, html) {
  const url = `https://${host}/w/rest.php/v1/transform/html/to/wikitext/Main_Page`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ html, body_only: 'true' }).toString(),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${res.status} ${text.slice(0, 200)}`);
  return { wikitext: text, endpoint: url, status: res.status };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false;
  (async () => {
    try {
      if (msg?.type === 'htmlToWikitext') {
        // the clipboard goes to the user's own home wiki only — no silent fallback elsewhere
        const home = normalizeHomeWiki(msg.homeWiki);
        sendResponse({ ok: true, ...(await fetchTransform(home, msg.html)) });
        return;
      }
      if (msg?.type === 'checkWiki') {
        const home = normalizeHomeWiki(msg.homeWiki);
        const url = `https://${home}/w/api.php?action=query&meta=siteinfo&siprop=general&format=json&origin=*`;
        const res = await fetch(url);
        const data = await res.json();
        sendResponse({ ok: true, host: home, sitename: data?.query?.general?.sitename ?? null,
                       server: data?.query?.general?.server ?? null });
        return;
      }
      sendResponse({ ok: false, error: 'unknown message' });
    } catch (err) {
      sendResponse({ ok: false, error: String(err?.message || err) });
    }
  })();
  return true;   // keep the channel open for the async response
});
