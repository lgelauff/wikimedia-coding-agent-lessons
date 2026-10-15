/**
 * Extension load test.
 *
 * Proves the parts the harness cannot: the manifest is valid, the MV3 service
 * worker loads its ES modules, first-run seeding writes the defaults, the
 * options page renders, and the background worker can reach a real wiki
 * (host_permissions + the siteinfo call behind the "Check this wiki" button).
 *
 *   node test/extension-load.spec.mjs
 *
 * Gmail itself is not exercised: mail.google.com needs a login.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';

const EXT = path.resolve(import.meta.dirname, '..');
const EXECUTABLE_CANDIDATES = [
  process.env.PLAYWRIGHT_EXECUTABLE,
  '/opt/data/home/.cache/ms-playwright/chromium-1217/chrome-linux/chrome',
  '/opt/hermes/.playwright/chromium_headless_shell-1234/chrome-linux/headless_shell',
].filter(Boolean).filter((p) => fs.existsSync(p));

const results = [];
const check = (name, pass, detail = '') => results.push({ name, pass: !!pass, detail });

const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'wikimarkup-profile-'));
const context = await chromium.launchPersistentContext(userDataDir, {
  ...(EXECUTABLE_CANDIDATES.length ? { executablePath: EXECUTABLE_CANDIDATES[0] } : {}),
  args: [
    '--no-sandbox',
    `--disable-extensions-except=${EXT}`,
    `--load-extension=${EXT}`,
  ],
});

let worker = context.serviceWorkers()[0];
if (!worker) {
  try { worker = await context.waitForEvent('serviceworker', { timeout: 15000 }); } catch { /* reported below */ }
}
check('the MV3 service worker registers (manifest is valid)', !!worker, worker?.url() ?? 'no service worker');
const extId = worker?.url()?.split('/')[2];
check('service worker loaded its ES module (background.js → lib/wikitext.js)', !!extId);

if (extId) {
  const workerErrors = [];
  worker.on('console', (m) => { if (m.type() === 'error') workerErrors.push(m.text()); });

  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(String(e)));

  await page.goto(`chrome-extension://${extId}/src/options.html`);
  await page.waitForFunction(() => !!document.getElementById('pv-t4')?.textContent, null, { timeout: 10000 });

  const homeWiki = await page.inputValue('#homeWiki');
  check('first-run defaults were seeded into storage', homeWiki === 'en.wikipedia.org', homeWiki);

  const pvSig = await page.textContent('#pv-t4');
  check('the preview renders a signature + timestamp', /\d\d:\d\d, \d{1,2} [A-Z][a-z]+ \d{4} \(UTC\)/.test(pvSig || ''), pvSig);

  const pvLink = await page.innerHTML('#pv-link');
  check('the preview renders [[Wikidata|WD]] as a link',
    (pvLink || '').includes('https://en.wikipedia.org/wiki/Wikidata'), pvLink);

  // the background worker reaching a real wiki: host_permissions + fetch + storage
  await page.click('#check');
  await page.waitForFunction(
    () => document.getElementById('wikiStatus')?.textContent?.trim() !== 'Checking…',
    null, { timeout: 20000 },
  );
  const status = (await page.textContent('#wikiStatus'))?.trim();
  check('background can read a live wiki (siteinfo)', /Wikipedia/.test(status || ''), status);

  // a saved home wiki must survive a reload of the settings page
  await page.fill('#homeWiki', 'nl.wikipedia.org');
  await page.fill('#signature', '— [[User:Lodewijk|Lodewijk]] (~~~~~)');
  await page.click('#save');
  await page.waitForFunction(() => document.getElementById('status')?.textContent?.includes('Saved'));
  await page.reload();
  await page.waitForFunction(() => !!document.getElementById('pv-t4')?.textContent);
  check('saved settings persist across a reload',
    (await page.inputValue('#homeWiki')) === 'nl.wikipedia.org'
      && (await page.inputValue('#signature')).includes('Lodewijk'),
    await page.inputValue('#homeWiki'));

  const pvT4 = await page.textContent('#pv-t4');
  check('a signature carrying its own ~~~~~ slot puts the timestamp in place',
    /\d\d:\d\d, \d{1,2} [A-Z][a-z]+ \d{4} \(UTC\)/.test(pvT4 || ''), pvT4);

  check('no page errors on the options page', pageErrors.length === 0, pageErrors.join(' | '));
  check('no errors from the service worker', workerErrors.length === 0, workerErrors.join(' | '));
}

await context.close();
fs.rmSync(userDataDir, { recursive: true, force: true });

let failed = 0;
for (const r of results) {
  if (!r.pass) failed += 1;
  console.log(`${r.pass ? 'PASS' : 'FAIL'}  ${r.name}${r.pass ? '' : `\n      ${r.detail}`}`);
}
console.log(`\n${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
