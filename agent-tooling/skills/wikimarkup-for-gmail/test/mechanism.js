/**
 * Browser mechanism suite, run inside test/mock-compose.html?run.
 *
 * Typing goes through document.execCommand('insertText'), which makes Chrome
 * fire real `input` events with inputType 'insertText' — the same events
 * typing produces in Gmail's compose body.
 */

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function runSuite(h) {
  const results = [];
  const check = (name, pass, detail = '') => results.push({ name, pass: !!pass, detail: String(detail) });
  const s = h.settings;
  const popup = () => document.querySelector('.wikimarkup-consent');
  const click = (value) => popup()?.querySelector(`button[data-wm="${value}"]`)?.click();
  const type = (text) => {
    for (const ch of text) {
      if (ch === '\n') document.execCommand('insertParagraph');
      else document.execCommand('insertText', false, ch);
    }
  };
  const pause = () => sleep(s.idleSeconds * 1000 + 60);
  const key = (el, code, keyChar) => el.dispatchEvent(new KeyboardEvent('keydown', {
    code, key: keyChar, altKey: true, shiftKey: true, bubbles: true, cancelable: true,
  }));
  const reset = (html = '', over = {}) => {
    Object.assign(s, { mode: 'link', permissionMode: 'ask', idleSeconds: 0.15 }, over);
    document.querySelectorAll('.wikimarkup-consent').forEach((b) => b.remove());
    return h.newDraft(html);
  };

  /* 1 — the basic loop: type, pause, popup, nothing changes until Convert */
  let el = reset();
  type('see [[Amsterdam]] for details');
  check('no popup while still typing', !popup());
  await pause();
  check('popup appears after the pause', popup(), el.innerHTML);
  check('popup lists the token and where it goes',
    popup()?.textContent.includes('[[Amsterdam]] → link to nl.wikipedia.org/wiki/Amsterdam'), popup()?.textContent);
  check('nothing converted before a click', !el.querySelector('a'), el.innerHTML);
  check('popup does not take focus', document.activeElement === el, document.activeElement?.tagName);
  const before = h.inputEvents();
  click('once');
  check('Convert links the inner text and keeps the brackets',
    el.innerHTML.includes('[[<a href="https://nl.wikipedia.org/wiki/Amsterdam">Amsterdam</a>]]'), el.innerHTML);
  check('the draft text is unchanged, only linked',
    el.textContent === 'see [[Amsterdam]] for details' && el.querySelector('a').textContent === 'Amsterdam', el.innerHTML);
  check('Gmail is told about the edit (input event)', h.inputEvents() > before);
  check('popup closes after the choice', !popup());

  /* 1b — typing straight after a converted link stays outside it */
  el = reset();
  type('[[Utrecht]]');
  await pause();
  click('once');
  type(' next');
  check('typing after the conversion continues outside the link',
    el.querySelector('a')?.textContent === 'Utrecht' && el.textContent === '[[Utrecht]] next', el.innerHTML);

  /* 1c — bold and italic, markup kept */
  el = reset();
  type("this is '''important''' and ''urgent'' ok");
  await pause();
  check('popup lists bold and italic', popup()?.textContent.includes("'''important''' → bold")
    && popup()?.textContent.includes("''urgent'' → italic"), popup()?.textContent);
  click('once');
  check('bold and italic applied inside the kept markers',
    el.querySelector('b')?.textContent === 'important' && el.querySelector('i')?.textContent === 'urgent'
    && el.textContent === "this is '''important''' and ''urgent'' ok", el.innerHTML);

  /* 1d — HTML between the markers: not offered */
  el = reset('<div>see [[<b>Ams</b>terdam</div>');
  const end = document.createRange();
  end.selectNodeContents(el.firstChild); end.collapse(false);
  getSelection().removeAllRanges(); getSelection().addRange(end);
  type(']] and [[Plain]] ');
  await pause();
  check('a link with formatting inside is not offered; a plain one is',
    popup()?.textContent.includes('[[Plain]]') && !popup()?.textContent.includes('Ams'), popup()?.textContent);
  click('once');
  check('…and only the plain one converts', el.querySelectorAll('a').length === 1
    && el.querySelector('a').textContent === 'Plain', el.innerHTML);

  /* 2 — quoted mail and pre-existing text are never touched */
  el = reset('<div>[[Already here]] ~~~~</div><div class="gmail_quote">On Tue someone wrote: [[Quoted]] ~~~~ <br>~~~~~~~~</div>');
  const firstLine = el.firstChild;
  const r = document.createRange();
  r.selectNodeContents(firstLine); r.collapse(false);
  getSelection().removeAllRanges(); getSelection().addRange(r);
  type(' and [[Mine]] ');
  await pause();
  click('once');
  check('typed token converted', el.innerHTML.includes('wiki/Mine"'), el.innerHTML);
  check('pre-existing [[…]] and ~~~~ left alone', firstLine.textContent.startsWith('[[Already here]] ~~~~')
    && firstLine.querySelectorAll('a').length === 1, firstLine.innerHTML);
  check('quoted mail left alone', el.querySelector('.gmail_quote').textContent.includes('[[Quoted]] ~~~~ ~~~~~~~~')
    && !el.querySelector('.gmail_quote a'), el.querySelector('.gmail_quote').innerHTML);

  /* 3 — tildes: a run ending the typing counts once typing pauses */
  el = reset();
  type('thanks, ~~~~');
  await pause();
  check('trailing ~~~~ offered, showing the actual signature and time',
    popup()?.textContent.includes('~~~~ → Lodewijk (talk) 09:30, 15 October 2026 (UTC)'), popup()?.textContent);
  click('once');
  check('signature + timestamp inserted',
    el.textContent === 'thanks, Lodewijk (talk) 09:30, 15 October 2026 (UTC)'
    && el.innerHTML.includes('href="https://nl.wikipedia.org/wiki/User:Lodewijk"'), el.innerHTML);

  el = reset();
  type('cheers, ~~~ ');
  await pause();
  check('~~~ offers just the username', popup()?.textContent.includes('~~~ → Lodewijk')
    && !popup()?.textContent.includes('talk'), popup()?.textContent);
  click('once');
  check('~~~ inserts just the linked username', el.textContent.replace(/ /g, ' ') === 'cheers, Lodewijk '
    && el.querySelector('a')?.getAttribute('href') === 'https://nl.wikipedia.org/wiki/User:Lodewijk', el.innerHTML);

  /* 3b — time zone and language preferences; the inserted time is the one the popup showed */
  el = reset('', { timeZone: 'Europe/Amsterdam', language: 'nl' });
  type('groet, ~~~~~');
  await pause();
  check('popup shows the time in the chosen zone and language',
    popup()?.textContent.includes('~~~~~ → 11:30, 15 oktober 2026 (CEST)'), popup()?.textContent);
  h.clock.now = new Date('2026-10-15T09:34:00Z');           // the user takes four minutes to click
  click('once');
  check('inserted timestamp is the one the popup showed', el.textContent === 'groet, 11:30, 15 oktober 2026 (CEST)',
    el.textContent);
  h.clock.now = new Date('2026-10-15T09:30:00Z');
  Object.assign(s, { timeZone: 'UTC', language: 'en' });

  el = reset();
  type('regards,\n~~~~\nPS more text');
  await pause();
  check('~~~~ then Enter then more typing is still offered', popup()?.textContent.includes('~~~~ →'),
    popup()?.textContent ?? el.innerHTML);

  /* 4 — a separator line is not a signature */
  el = reset();
  type('~~~~~~~~ \nok');
  await pause();
  check('~~~~~~~~ separator never offered', !popup(), popup()?.textContent);

  /* 5 — Not in this draft */
  el = reset();
  type('[[One]] ');
  await pause();
  click('deny');
  type('[[Two]] ');
  await pause();
  check('"Not in this draft": nothing converted, no further popups', !popup() && !el.querySelector('a'), el.innerHTML);

  /* 6 — Convert all in this draft */
  el = reset();
  type('[[One]] ');
  await pause();
  click('draft');
  type('and [[Two]] ');
  await pause();
  check('"Convert all in this draft": later tokens convert at the pause without asking',
    !popup() && el.querySelectorAll('a').length === 2, el.innerHTML);

  /* 7 — Escape dismisses this batch; the draft keeps asking */
  el = reset();
  type('[[One]] ');
  await pause();
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  check('Escape closes the popup without converting', !popup() && !el.querySelector('a'), el.innerHTML);
  type('[[Two]] ');
  await pause();
  check('after Escape, new tokens still ask', popup()?.textContent.includes('[[Two]]')
    && !popup()?.textContent.includes('[[One]]'), popup()?.textContent);

  /* 8 — leaving the body asks immediately, before the pause */
  el = reset('', { idleSeconds: 30 });
  type('[[Soon]] ');
  const subject = document.getElementById('subject');
  const hadFocus = document.hasFocus();
  subject.focus();
  // a background window gets no focus events; send the one Chrome would have sent
  if (!hadFocus) el.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: subject }));
  await sleep(30);
  check('focus leaving the body shows the popup straight away', popup()?.textContent.includes('[[Soon]]'));
  click('once');
  check('…and Convert still works with focus elsewhere', el.innerHTML.includes('wiki/Soon"'), el.innerHTML);

  /* 9 — pasted text is not "typed" */
  el = reset();
  el.focus();
  document.execCommand('insertHTML', false, 'pasted [[Pasted]] ~~~~ ');   // inputType insertFromPaste-like
  el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertFromPaste' }));
  await pause();
  check('pasted markup is not offered', !popup(), popup()?.textContent);

  /* 10 — a token edited after it was typed is dropped */
  el = reset();
  type('[[Foo]] x');
  const t = el.firstChild;
  t.nodeValue = t.nodeValue.replace('[[Foo]]', '[[Fob]]');
  await pause();
  check('edited token is not converted', !popup() && !el.querySelector('a'), el.innerHTML);

  /* 11 — wikitext mode: links stay, tildes still expand */
  el = reset('', { mode: 'wikitext' });
  type('see [[X]] ~~~ ');
  await pause();
  check('wikitext mode offers only the tildes', popup()?.textContent.includes('~~~ →')
    && !popup()?.textContent.includes('[[X]]'), popup()?.textContent);
  click('once');
  check('wikitext mode output is plain text', el.textContent.startsWith('see [[X]] [[User:Lodewijk|Lodewijk]]')
    && !el.querySelector('a'), el.innerHTML);

  /* 12 — "never ask" converts at the pause */
  el = reset('', { permissionMode: 'always' });
  type('[[Auto]] ');
  await pause();
  check('"never ask" converts without a popup', !popup() && el.innerHTML.includes('wiki/Auto"'), el.innerHTML);

  /* 13 — hotkeys match the physical key (macOS gives e.key '„' for Option+Shift+W) */
  el = reset('<div><br></div>');
  const sel = document.createRange();
  sel.setStart(el.firstChild, 0); sel.collapse(true);
  getSelection().removeAllRanges(); getSelection().addRange(sel);
  key(el, 'KeyS', 'Í');
  check('Option+Shift+S inserts the signature on an empty line',
    el.textContent.startsWith('Lodewijk (talk) 09:30, 15 October 2026 (UTC)'), el.innerHTML);
  el = reset('', { idleSeconds: 30 });
  type('[[Now]]');
  key(el, 'KeyW', '„');
  check('Option+Shift+W asks right away', popup()?.textContent.includes('[[Now]]'), popup()?.textContent);

  /* 14 — the popup goes away with its draft */
  el = reset();
  type('[[Gone]] ');
  await pause();
  el.remove();
  await sleep(1100);
  check('popup removed when the draft disappears (sent/discarded)', !popup());

  h.newDraft();
  return results;
}
