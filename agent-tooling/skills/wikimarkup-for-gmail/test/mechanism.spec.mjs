/**
 * Browser mechanism test (Playwright).
 *
 * Gmail itself is behind a login, so this opens test/mock-compose.html?run —
 * a Gmail-shaped compose DOM with the same attachWikiMarkup() and consent popup
 * the extension installs — and reports the in-page suite in test/mechanism.js.
 * The same page can be opened in any browser by hand.
 *
 *   node test/mechanism.spec.mjs
 */

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const ROOT = path.resolve(import.meta.dirname, '..');
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
};

const server = http.createServer((req, res) => {
  const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  const file = path.join(ROOT, rel);
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404); res.end('not found'); return;
  }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] ?? 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));

const browser = await chromium.launch(
  process.env.PLAYWRIGHT_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE } : {},
);
const page = await browser.newPage();
const pageErrors = [];
page.on('pageerror', (e) => pageErrors.push(String(e)));

await page.goto(`http://127.0.0.1:${server.address().port}/test/mock-compose.html?run`);
await page.waitForFunction(() => !!window.__results, null, { timeout: 60_000 });
const results = await page.evaluate(() => window.__results);
if (pageErrors.length) results.push({ name: 'no page errors', pass: false, detail: pageErrors.join('\n') });

for (const r of results) console.log(`${r.pass ? 'PASS' : 'FAIL'}  ${r.name}${r.pass ? '' : `\n      ${r.detail}`}`);
const failed = results.filter((r) => !r.pass).length;
console.log(`\n${results.length - failed}/${results.length} passed`);

await browser.close();
server.close();
process.exit(failed ? 1 : 0);
