/**
 * The consent popup.
 *
 * It appears next to the compose box once typing pauses, lists exactly the
 * tokens it would convert, and never takes keyboard focus — you may still be
 * mid-sentence. Escape (handled in triggers.js) dismisses it.
 *
 * Pure DOM — no chrome.* APIs — so the browser harness exercises this exact code.
 */

import { describeToken } from './wikitext.js';

const popups = new Map();    // compose element -> popup element

export const CHOICES = {
  once: 'Convert',
  draft: 'Convert all in this draft',
  deny: 'Not in this draft',
};

export function popupFor(el) { return popups.get(el) ?? null; }
export function draftsWithPopup() { return [...popups.keys()]; }

export function hidePopup(el) {
  popups.get(el)?.remove();
  popups.delete(el);
}

export function hideAllPopups() {
  for (const el of [...popups.keys()]) hidePopup(el);
  for (const box of document.querySelectorAll('.wikimarkup-consent')) box.remove();
}

function css(node, decls) {
  // set through the CSSOM rather than a <style> tag: Gmail's CSP allows this
  for (const [k, v] of Object.entries(decls)) node.style.setProperty(k, v);
  return node;
}

const MAX_LISTED = 4;

/** Show (or refresh) the popup for `el` listing `tokens`; `onChoice(value)` gets 'once' | 'draft' | 'deny'. */
export function showPopup(el, tokens, settings, { onChoice, now = new Date() }) {
  hidePopup(el);

  const box = css(document.createElement('div'), {
    position: 'fixed', 'z-index': '2147483647', width: '360px', 'max-width': '92vw',
    background: '#fff', color: '#202122', border: '1px solid #a2a9b1',
    'border-radius': '8px', 'box-shadow': '0 4px 16px rgba(0,0,0,.22)',
    padding: '12px 14px', font: '13px/1.5 system-ui,-apple-system,Segoe UI,sans-serif',
  });
  box.className = 'wikimarkup-consent';
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-label', 'WikiMarkup for Gmail');
  box.setAttribute('aria-live', 'polite');
  // clicking a button must not move focus out of the draft
  box.addEventListener('mousedown', (ev) => ev.preventDefault());

  const title = css(document.createElement('div'), { 'font-weight': '600', 'margin-bottom': '4px' });
  title.textContent = tokens.length === 1
    ? 'Convert this wiki markup?'
    : `Convert these ${tokens.length} bits of wiki markup?`;
  box.appendChild(title);

  const list = css(document.createElement('div'), { color: '#54595d', 'margin-bottom': '10px' });
  for (const t of tokens.slice(0, MAX_LISTED)) {
    // wrap rather than truncate: the timestamp sits at the end of a signature line
    const d = css(document.createElement('div'), { 'overflow-wrap': 'anywhere', 'margin-bottom': '2px' });
    const c = css(document.createElement('code'), {
      background: '#f8f9fa', padding: '0 3px', 'border-radius': '3px',
    });
    c.textContent = t.raw;
    d.appendChild(c);
    d.appendChild(document.createTextNode(` → ${describeToken(t, settings, now)}`));
    list.appendChild(d);
  }
  if (tokens.length > MAX_LISTED) {
    const more = document.createElement('div');
    more.textContent = `…and ${tokens.length - MAX_LISTED} more`;
    list.appendChild(more);
  }
  box.appendChild(list);

  const actions = css(document.createElement('div'), {
    display: 'flex', gap: '8px', 'align-items': 'center', 'flex-wrap': 'wrap',
  });
  for (const [value, label] of Object.entries(CHOICES)) {
    const b = document.createElement('button');
    b.type = 'button';
    b.tabIndex = -1;
    b.dataset.wm = value;
    b.textContent = label;
    css(b, value === 'once'
      ? { font: 'inherit', padding: '6px 12px', 'border-radius': '6px', border: '1px solid #3366cc',
          background: '#3366cc', color: '#fff', cursor: 'pointer' }
      : { font: 'inherit', padding: '6px 12px', 'border-radius': '6px', border: '1px solid #a2a9b1',
          background: 'transparent', color: '#3366cc', cursor: 'pointer' });
    b.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      hidePopup(el);
      onChoice(value);
    });
    actions.appendChild(b);
  }
  box.appendChild(actions);

  const note = css(document.createElement('div'), {
    'margin-top': '8px', 'font-size': '11px', color: '#72777d',
  });
  note.textContent = 'Only what you typed in this draft is converted — never quoted mail. Esc to dismiss.';
  box.appendChild(note);

  // anchor it to the compose box
  const rect = el.getBoundingClientRect();
  const top = Math.min(rect.bottom + 8, window.innerHeight - 220);
  const left = Math.min(Math.max(8, rect.left), Math.max(8, window.innerWidth - 380));
  box.style.top = `${Math.max(8, top)}px`;
  box.style.left = `${left}px`;

  document.body.appendChild(box);
  popups.set(el, box);
  return box;
}
