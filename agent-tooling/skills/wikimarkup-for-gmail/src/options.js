import {
  normalizeSettings, normalizeHomeWiki, mediawikiTimestamp, render, DATE_FORMATS, resolveTimeZone,
} from './lib/wikitext.js';

const $ = (id) => document.getElementById(id);

/* time zone list: UTC, the browser's own zone, then every zone the browser knows */
function fillTimeZones() {
  const sel = $('timeZone');
  const add = (value, label) => sel.appendChild(Object.assign(document.createElement('option'), { value, textContent: label }));
  add('UTC', 'UTC (MediaWiki default)');
  add('browser', `Use my browser's time zone (${resolveTimeZone('browser')})`);
  for (const tz of Intl.supportedValuesOf('timeZone')) if (tz !== 'UTC') add(tz, tz.replace(/_/g, ' '));
}

/* date-format radios, labelled with MediaWiki's example date in the chosen language */
const EXAMPLE = new Date('2001-01-15T16:12:23Z');
function renderDateFormats(current) {
  const box = $('dateFormats');
  const lang = currentSettings().language;
  box.textContent = '';
  for (const key of Object.keys(DATE_FORMATS)) {
    const label = document.createElement('label');
    const input = Object.assign(document.createElement('input'), {
      type: 'radio', name: 'dateFormat', value: key, checked: key === current,
    });
    input.addEventListener('change', preview);
    label.append(input, ` ${mediawikiTimestamp(EXAMPLE, { dateFormat: key, language: lang, timeZone: 'UTC' })
      .replace(/ \(UTC\)$/, '')}`);
    box.appendChild(label);
  }
}

async function load() {
  fillTimeZones();
  const stored = normalizeSettings(await chrome.storage.sync.get(null));
  $('homeWiki').value = stored.homeWiki;
  $('signature').value = stored.signature;
  $('timeZone').value = stored.timeZone;
  $('language').value = stored.language;
  renderDateFormats(stored.dateFormat);
  $('idleSeconds').value = stored.idleSeconds;
  $('showPreview').checked = !!stored.showPreview;
  for (const r of document.querySelectorAll('input[name=mode]')) {
    r.checked = (r.value === stored.mode);
  }
  for (const r of document.querySelectorAll('input[name=permissionMode]')) {
    r.checked = (r.value === stored.permissionMode);
  }
  preview();
}

function currentSettings() {
  return normalizeSettings({
    homeWiki: normalizeHomeWiki($('homeWiki').value),
    signature: $('signature').value,
    mode: document.querySelector('input[name=mode]:checked')?.value ?? 'link',
    permissionMode: document.querySelector('input[name=permissionMode]:checked')?.value,
    idleSeconds: $('idleSeconds').value,
    showPreview: $('showPreview').checked,
    timeZone: $('timeZone').value,
    dateFormat: document.querySelector('input[name=dateFormat]:checked')?.value,
    language: $('language').value,
  });
}

function preview() {
  const s = currentSettings();
  const now = new Date();
  const cell = (id, value, isHtml = true) => {
    const el = $(id);
    el.textContent = '';
    if (isHtml && s.mode === 'link') el.innerHTML = value;   // render() output is escaped
    else el.textContent = value;
  };
  cell('pv-sig3', s.signature, false);
  cell('pv-t3', render('~~~', s, now).html);
  cell('pv-t4', render('~~~~', s, now).html);
  cell('pv-t5', mediawikiTimestamp(now, s), false);
  cell('pv-link', render('[[Wikidata|WD]]', s, now).html);
  cell('pv-c', render('[[c:Category:Amsterdam]]', s, now).html);
}

for (const r of document.querySelectorAll('input[name=mode]')) r.addEventListener('change', preview);
for (const id of ['homeWiki', 'signature']) $(id).addEventListener('input', preview);
$('timeZone').addEventListener('change', preview);
$('language').addEventListener('input', () => {
  renderDateFormats(document.querySelector('input[name=dateFormat]:checked')?.value);
  preview();
});

$('save').addEventListener('click', async () => {
  await chrome.storage.sync.set(currentSettings());
  const el = $('status');
  el.textContent = 'Saved — open Gmail tabs pick it up straight away.';
  el.className = 'ok';
});

$('check').addEventListener('click', async () => {
  const host = normalizeHomeWiki($('homeWiki').value);
  const el = $('wikiStatus');
  el.textContent = 'Checking…';
  el.className = 'hint';
  const res = await chrome.runtime.sendMessage({ type: 'checkWiki', homeWiki: host });
  if (res?.ok && res.sitename) {
    el.textContent = `${res.sitename} (${res.host})`;
    el.className = 'ok';
  } else {
    el.textContent = `Could not read ${host}: ${res?.error ?? 'no answer'}`;
    el.className = 'bad';
  }
});

load();
