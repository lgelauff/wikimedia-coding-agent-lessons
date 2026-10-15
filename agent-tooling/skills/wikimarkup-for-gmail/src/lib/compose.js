/**
 * DOM-facing helpers, shared by the Gmail content script and the browser test
 * harness — so the harness exercises the same code that runs in Gmail.
 *
 * Tokens are tracked as live Ranges over the compose body's text, so a token
 * may span several text nodes and survives edits elsewhere in the draft. Edits
 * go through Range surgery followed by an `input` event so Gmail's own model
 * notices the change.
 */

import { renderToken } from './wikitext.js';

export const COMPOSE_SELECTOR =
  'div[role="textbox"][contenteditable="true"], div[aria-label="Message Body"][contenteditable="true"], div[g_editable="true"]';

/** Text the extension must never touch: quoted mail, forwarded mail, the Gmail signature. */
export const EXCLUDE_SELECTOR =
  '.gmail_quote, blockquote, .gmail_signature, [data-smartmail="gmail_signature"]';

export function isComposeElement(el) {
  if (!el || el.nodeType !== 1) return false;
  if (!el.isContentEditable) return false;
  return el.matches?.(COMPOSE_SELECTOR) || !!el.closest?.(COMPOSE_SELECTOR);
}

/** The collapsed caret range inside `el`, or null. */
export function caretRangeIn(el) {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || !sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  return el.contains(range.startContainer) ? range : null;
}

/** All text of `el` before the caret ('' when there is no caret inside it). */
export function textBeforeCaret(el) {
  const range = caretRangeIn(el);
  if (!range) return '';
  const probe = document.createRange();
  probe.setStart(el, 0);
  probe.setEnd(range.startContainer, range.startOffset);
  return probe.toString();
}

/** Map a character offset in el's text (as Range.toString counts it) to a DOM point. */
function pointAt(el, index, preferNext) {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let seen = 0;
  let last = null;
  while (walker.nextNode()) {
    const n = walker.currentNode;
    const len = n.nodeValue.length;
    if (index < seen + len || (!preferNext && index === seen + len)) {
      return { node: n, offset: index - seen };
    }
    seen += len;
    last = n;
  }
  return last && index === seen ? { node: last, offset: last.nodeValue.length } : null;
}

/** A live Range over characters [start, end) of el's text. */
export function rangeForOffsets(el, start, end) {
  const a = pointAt(el, start, true);
  const b = pointAt(el, end, false);
  if (!a || !b) return null;
  const r = document.createRange();
  r.setStart(a.node, a.offset);
  r.setEnd(b.node, b.offset);
  return r;
}

export function isExcluded(el, range) {
  const node = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
  const hit = node?.closest(EXCLUDE_SELECTOR);
  return !!hit && el.contains(hit);
}

/** Plain text -> fragment with <br> for newlines (a bare "\n" collapses in a contenteditable). */
export function textFragment(text) {
  const frag = document.createDocumentFragment();
  String(text).split('\n').forEach((line, i) => {
    if (i) frag.appendChild(document.createElement('br'));
    if (line) frag.appendChild(document.createTextNode(line));
  });
  return frag;
}

/**
 * True if the range is one stretch of plain text: a single text node, not
 * inside a link. Links, bold and italic only convert when there is no HTML
 * (formatting, a line break, an existing link) between their markers.
 */
export function isPlainTextRange(range) {
  return range.startContainer === range.endContainer
    && range.startContainer.nodeType === 3
    && !range.startContainer.parentElement?.closest('a');
}

function fragmentFor(range, token, settings, now) {
  const out = renderToken(token, settings, now);
  return settings.mode === 'wikitext'
    ? textFragment(out.text)
    : range.createContextualFragment(out.html);
}

function placeCaretAfter(node) {
  const after = document.createRange();
  after.setStartAfter(node);
  after.collapse(true);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(after);
}

let selfEditDepth = 0;
/** True while the extension itself is editing — its own input events are not typing. */
export function isSelfEdit() { return selfEditDepth > 0; }

function notifyInput(el) {
  selfEditDepth += 1;
  try {
    el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertReplacementText' }));
  } finally {
    selfEditDepth -= 1;
  }
}

/**
 * Replace each tracked token with its rendered form. A token whose text no
 * longer matches what was typed (edited, deleted) is left alone.
 * Returns the number of tokens converted.
 */
export function convertTokens(el, tokens, settings, now = new Date()) {
  let changed = 0;
  const caret = caretRangeIn(el);
  for (const t of tokens) {
    const r = t.range;
    if (!el.contains(r.startContainer) || r.toString() !== t.raw || isExcluded(el, r)) continue;
    if (t.kind !== 'tildes' && !isPlainTextRange(r)) continue;
    const caretAtEnd = !!caret
      && r.endContainer === caret.startContainer && r.endOffset === caret.startOffset;
    const frag = fragmentFor(r, t, settings, now);
    const last = frag.lastChild;
    r.deleteContents();
    r.insertNode(frag);
    if (caretAtEnd && last) placeCaretAfter(last);
    changed += 1;
  }
  if (changed) notifyInput(el);
  return changed;
}

/** Insert rendered markup (e.g. '~~~~') or plain text at the caret; works on an empty line too. */
export function insertAtCaret(el, { raw = null, text = null }, settings, now = new Date()) {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return false;
  const range = sel.getRangeAt(0);
  if (!el.contains(range.startContainer)) return false;
  range.deleteContents();
  const frag = raw !== null ? fragmentFor(range, { kind: 'tildes', raw }, settings, now) : textFragment(text);
  const last = frag.lastChild;
  if (!last) return false;
  range.insertNode(frag);
  placeCaretAfter(last);
  notifyInput(el);
  return true;
}
