/**
 * Trigger wiring: when to ask, and what to apply it to.
 *
 *   - Only text you TYPE in a Gmail compose body is ever considered. Each
 *     completed token ([[…]] closed, or a ~~~ / ~~~~ / ~~~~~ run followed by
 *     another character) is remembered as a live Range at the moment it is typed.
 *     Quoted mail, forwarded mail, pasted text and anything already in the
 *     draft are therefore never candidates.
 *   - Once typing pauses (settings.idleSeconds) or focus leaves the body, the
 *     consent popup lists those tokens. Nothing changes without a click.
 *   - "Convert all in this draft" converts later tokens at each pause without
 *     asking; "Not in this draft" stops watching that draft; Esc dismisses.
 *
 * Hotkeys use KeyboardEvent.code, so they work on macOS where Option+Shift+W
 * produces '„' as e.key:
 *   Alt/Option+Shift+W  ask now · +S signature · +T timestamp · +P paste as wikitext
 *
 * Kept free of chrome.* APIs so the browser harness in test/ attaches the very
 * same handlers to a Gmail-shaped contenteditable.
 */

import { findCompletedToken } from './wikitext.js';
import {
  COMPOSE_SELECTOR, isComposeElement, textBeforeCaret, rangeForOffsets, isExcluded, isPlainTextRange,
  convertTokens, insertAtCaret, isSelfEdit,
} from './compose.js';
import { showPopup, hidePopup, popupFor, draftsWithPopup } from './consent.js';

export const HOTKEYS = {
  KeyW: 'ask about this draft now',
  KeyS: 'insert signature',
  KeyT: 'insert timestamp',
  KeyP: 'paste as wikitext',
};

/** Typing input types: pasted, dropped or autocorrected text is not "typed". */
const TYPED = new Set(['insertText', 'insertCompositionText']);
const TAIL = 400;   // only the end of the text before the caret can hold a just-finished token

export function attachWikiMarkup({
  target = document,
  getSettings,
  onFlash = () => {},
  onPasteAsWikitext = null,
  now = () => new Date(),
} = {}) {
  /** compose element -> { pending, grant: 'ask'|'draft'|'deny', timer, tail, noticed } */
  const drafts = new WeakMap();

  function draft(el) {
    let d = drafts.get(el);
    if (!d) {
      d = { pending: [], grant: 'ask', timer: null, tail: null, noticed: false };
      drafts.set(el, d);
    }
    return d;
  }

  function composeTargetFrom(node) {
    if (!node || node.nodeType !== 1) return null;
    const el = node.closest?.(COMPOSE_SELECTOR) || (node.isContentEditable ? node : null);
    if (!isComposeElement(el)) return null;
    return el.closest(COMPOSE_SELECTOR) ?? el;
  }

  /** Scan the end of the text before the caret; offsets come back in whole-draft terms. */
  function scan(el, opts) {
    const before = textBeforeCaret(el);
    const base = Math.max(0, before.length - TAIL);
    const t = findCompletedToken(before.slice(base), opts);
    return t ? { ...t, start: t.start + base, end: t.end + base } : null;
  }

  function track(el, d, token) {
    const range = rangeForOffsets(el, token.start, token.end);
    if (!range || range.toString() !== token.raw || isExcluded(el, range)) return false;
    if (token.kind !== 'tildes' && !isPlainTextRange(range)) return false;   // HTML between the markers
    const dup = d.pending.some((p) => p.range.compareBoundaryPoints(Range.START_TO_START, range) === 0);
    if (dup) return false;
    d.pending.push({ kind: token.kind, raw: token.raw, range });
    return true;
  }

  function stillValid(el, t) {
    return el.contains(t.range.startContainer) && t.range.toString() === t.raw && !isExcluded(el, t.range)
      && (t.kind === 'tildes' || isPlainTextRange(t.range));
  }

  function schedule(el, d) {
    clearTimeout(d.timer);
    d.timer = setTimeout(() => flush(el), getSettings().idleSeconds * 1000);
  }

  function convert(el, d, settings) {
    // a timestamp is the one the popup showed, not the time of the click
    const n = convertTokens(el, d.pending, settings, d.shownAt ?? now());
    d.pending = [];
    d.shownAt = null;
    if (n) onFlash(`Converted ${n} bit${n === 1 ? '' : 's'} of wiki markup`);
  }

  function choose(el, value) {
    const d = draft(el);
    if (value === 'deny') {
      d.grant = 'deny';
      d.pending = [];
      d.shownAt = null;
      onFlash('WikiMarkup is off for this draft');
      return;
    }
    if (value === 'draft') d.grant = 'draft';
    d.pending = d.pending.filter((t) => stillValid(el, t));
    convert(el, d, getSettings());
  }

  /** Typing paused, focus left, or the hotkey: ask about (or convert) what was typed. */
  function flush(el) {
    const d = drafts.get(el);
    if (!d) return;
    clearTimeout(d.timer);
    d.timer = null;
    if (!el.isConnected || d.grant === 'deny') { d.pending = []; hidePopup(el); return; }
    const settings = getSettings();
    // a tilde run that ends the typing is complete once typing pauses
    if (d.tail) { track(el, d, d.tail); d.tail = null; }
    d.pending = d.pending.filter((t) => stillValid(el, t));
    if (!d.pending.length) { hidePopup(el); return; }
    if (settings.permissionMode === 'always' || d.grant === 'draft') { convert(el, d, settings); return; }
    d.shownAt = now();
    showPopup(el, d.pending, settings, { onChoice: (v) => choose(el, v), now: d.shownAt });
  }

  function onInput(e) {
    if (isSelfEdit()) return;
    const el = composeTargetFrom(e.target);
    if (!el) return;
    const d = draft(el);
    if (d.grant === 'deny') return;
    const settings = getSettings();

    if (TYPED.has(e.inputType)) {
      let token = scan(el, { mode: settings.mode });
      // a tilde run only counts if it is the run being typed a keystroke ago,
      // so typing next to a ~~~~ that was already in the draft does not adopt it
      if (token?.kind === 'tildes' && !(d.tail && d.tail.start === token.start && d.tail.raw === token.raw)) {
        token = null;
      }
      if (token && track(el, d, token)) {
        if (!d.noticed && d.grant === 'ask' && settings.permissionMode !== 'always') {
          d.noticed = true;
          onFlash('Wiki markup noticed — I\'ll ask when you pause');
        }
        if (popupFor(el)) flush(el);       // popup already open: add to its list now
      }
      const tail = scan(el, { mode: settings.mode, final: true });
      d.tail = tail?.kind === 'tildes' ? tail : null;
    } else if (e.inputType === 'insertParagraph' || e.inputType === 'insertLineBreak') {
      if (d.tail) track(el, d, d.tail);      // Enter completes a tilde run too
      d.tail = null;
    } else {
      d.tail = null;                         // deleting or pasting: the run being typed is gone
    }
    if (d.pending.length || d.tail) schedule(el, d);
  }

  function onFocusOut(e) {
    const el = composeTargetFrom(e.target);
    if (!el || (e.relatedTarget && el.contains(e.relatedTarget))) return;
    if (drafts.get(el)?.timer) flush(el);
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') {
      const open = draftsWithPopup();
      if (open.length) {
        for (const el of open) { hidePopup(el); Object.assign(draft(el), { pending: [], shownAt: null }); }
        e.preventDefault();
        e.stopPropagation();
        return;
      }
    }
    if (!(e.altKey && e.shiftKey && !e.ctrlKey && !e.metaKey) || !HOTKEYS[e.code]) return;
    const el = composeTargetFrom(e.target);
    if (!el) return;
    e.preventDefault();
    const settings = getSettings();
    const d = draft(el);
    if (e.code === 'KeyW') {
      if (d.grant === 'deny') d.grant = 'ask';
      flush(el);
      if (!popupFor(el) && !d.pending.length) onFlash('Nothing typed to convert');
    } else if (e.code === 'KeyS' || e.code === 'KeyT') {
      const raw = e.code === 'KeyS' ? '~~~~' : '~~~~~';
      const ok = insertAtCaret(el, { raw }, settings, now());
      onFlash(ok ? (e.code === 'KeyS' ? 'Signature inserted' : 'Timestamp inserted') : 'Put the cursor in the message first');
    } else if (e.code === 'KeyP' && onPasteAsWikitext) {
      onPasteAsWikitext(el, settings);
    }
  }

  // drafts that disappear (sent, discarded) take their popup with them
  const sweeper = setInterval(() => {
    for (const el of draftsWithPopup()) if (!el.isConnected) hidePopup(el);
  }, 1000);

  target.addEventListener('input', onInput, true);
  target.addEventListener('focusout', onFocusOut, true);
  target.addEventListener('keydown', onKeyDown, true);
  return {
    flush,
    pending: (el) => drafts.get(el)?.pending.map((t) => t.raw) ?? [],
    grant: (el) => drafts.get(el)?.grant ?? 'ask',
    detach() {
      clearInterval(sweeper);
      target.removeEventListener('input', onInput, true);
      target.removeEventListener('focusout', onFocusOut, true);
      target.removeEventListener('keydown', onKeyDown, true);
    },
  };
}
