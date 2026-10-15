/**
 * Gmail content script — the chrome.* glue only.
 *
 * Runs on mail.google.com and nowhere else. Watches what you type in a draft;
 * when you have typed wiki markup and pause, a popup next to the compose box
 * asks whether to convert it (see lib/triggers.js for the rules).
 *
 * Triggers (mirroring MediaWiki):
 *   ~~~ / ~~~~ / ~~~~~   signature / signature+timestamp / timestamp
 *   [[Page]], [[Page|label]], [[c:Category:X]], [[w:nl:Page]]
 *
 * Hotkeys (Alt/Option+Shift, matched on the physical key so macOS works):
 *   W ask now · S signature · T timestamp · P paste as wikitext
 *
 * The lib modules are loaded with dynamic import() because Chrome content
 * scripts are classic scripts (no top-level import), and an extension URL is
 * required since the import resolves from the page origin.
 */

(async () => {
  const lib = await import(chrome.runtime.getURL('src/lib/wikitext.js'));
  const { attachWikiMarkup } = await import(chrome.runtime.getURL('src/lib/triggers.js'));
  const compose = await import(chrome.runtime.getURL('src/lib/compose.js'));

  let settings = lib.normalizeSettings({});

  async function loadSettings() {
    settings = lib.normalizeSettings(await chrome.storage.sync.get(null));
  }
  await loadSettings();
  chrome.storage.onChanged.addListener((_c, area) => { if (area === 'sync') loadSettings(); });

  /* ----------------------------------------------------------------- toast */

  let toastTimer = null;
  function flash(message) {
    if (!settings.showPreview) return;
    let el = document.getElementById('wikimarkup-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'wikimarkup-toast';
      el.style.cssText = [
        'position:fixed', 'z-index:2147483647', 'right:18px', 'bottom:18px',
        'background:#202122', 'color:#fff', 'font:13px/1.4 system-ui,sans-serif',
        'padding:8px 12px', 'border-radius:6px', 'box-shadow:0 2px 8px rgba(0,0,0,.35)',
        'max-width:320px', 'pointer-events:none', 'opacity:0', 'transition:opacity .15s ease',
      ].join(';');
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.style.opacity = '1';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.style.opacity = '0'; }, 2200);
  }

  /* ------------------------------------------------ paste as wikitext (HTML) */

  async function pasteAsWikitext(el) {
    try {
      const items = await navigator.clipboard.read();
      let html = null;
      for (const item of items) {
        if (item.types.includes('text/html')) {
          html = await (await item.getType('text/html')).text();
          break;
        }
      }
      if (!html) {
        const text = await navigator.clipboard.readText();
        if (!text) { flash('Clipboard is empty'); return; }
        compose.insertAtCaret(el, { text }, settings);
        flash('Pasted as plain text (no HTML on the clipboard)');
        return;
      }
      flash(`Converting via ${lib.normalizeHomeWiki(settings.homeWiki)}…`);
      const res = await chrome.runtime.sendMessage({
        type: 'htmlToWikitext', html, homeWiki: settings.homeWiki,
      });
      if (!res?.ok) { flash(`Convert failed: ${res?.error ?? 'unknown'}`); return; }
      const ok = compose.insertAtCaret(el, { text: res.wikitext }, settings);
      flash(ok ? 'Pasted as wikitext' : 'Put the cursor in the message first');
    } catch (err) {
      flash(`Clipboard read failed: ${String(err?.message || err)}`);
    }
  }

  attachWikiMarkup({
    target: document,
    getSettings: () => settings,
    onFlash: flash,
    onPasteAsWikitext: pasteAsWikitext,
  });

  /* ---------------------------------------------- one-time onboarding hint */

  function onFirstCompose(e) {
    if (!compose.isComposeElement(e.target)) return;
    document.removeEventListener('focusin', onFirstCompose, true);
    chrome.storage.sync.get({ hintShown: false }, ({ hintShown }) => {
      if (hintShown) return;
      chrome.storage.sync.set({ hintShown: true });
      flash(`Type [[…]] or ~~~~ and WikiMarkup will offer to convert it (${settings.homeWiki})`);
    });
  }
  document.addEventListener('focusin', onFirstCompose, true);
})();
