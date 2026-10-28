import type { CDPSession, ElementHandle, Frame, Locator, Page } from 'playwright-core';
import { runCli } from './cdp.ts';

export type PersonTarget = { kind: 'person'; email: string };
export type GroupTarget = { kind: 'group'; id: string; name: string };
export type TeamsRequest =
  | { operation: 'open-window' }
  | { operation: 'find'; query: string; kind: 'person' | 'group' }
  | { operation: 'send'; target: PersonTarget | GroupTarget; text: string };

type Person = { kind: 'person'; id: string; name: string; email: string };
type Group = GroupTarget;
type GroupCard = { index: number; name: string };
const SEARCH = 'input[data-tid="AUTOSUGGEST_INPUT"][role="combobox"]:visible';
const PICKER = 'input[data-tid="people-picker-search"][role="combobox"]:visible';
const EDITOR = '[data-tid="ckeditor"][role="textbox"][contenteditable="true"]:visible';
const PERSON_CARD = '[data-tid="search-people-card"][id^="serp-people-card-content-"]';
const GROUP_CARD = '[data-testid="groupChatCard"]';
const TIMEOUT = 20_000;

function object(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function keys(value: Record<string, unknown>, expected: string[], label: string): void {
  if (Object.keys(value).some(key => !expected.includes(key)) || expected.some(key => !(key in value))) {
    throw new Error(`${label} must contain exactly: ${expected.join(', ')}`);
  }
}

function string(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.trim().length === 0 || value.includes('\0')) {
    throw new Error(`${label} must be a non-empty string without NUL`);
  }
  return value;
}

export function parseRequest(value: unknown): TeamsRequest {
  const request = object(value, 'request');
  if (request.operation === 'open-window') {
    keys(request, ['operation'], 'open-window request');
    return { operation: 'open-window' };
  }
  if (request.operation === 'find') {
    keys(request, ['operation', 'query', 'kind'], 'find request');
    if (request.kind !== 'person' && request.kind !== 'group') throw new Error('kind must be person or group');
    return { operation: 'find', query: string(request.query, 'query').trim(), kind: request.kind };
  }
  if (request.operation === 'send') {
    keys(request, ['operation', 'target', 'text'], 'send request');
    const target = object(request.target, 'target');
    const text = string(request.text, 'text');
    if (target.kind === 'person') {
      keys(target, ['kind', 'email'], 'person target');
      const email = string(target.email, 'email');
      if (!/^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(email)) throw new Error('person target requires an explicit email address');
      return { operation: 'send', target: { kind: 'person', email }, text };
    }
    if (target.kind === 'group') {
      keys(target, ['kind', 'id', 'name'], 'group target');
      const id = string(target.id, 'group id');
      if (!/^19:[a-zA-Z0-9-]+@thread\.v2$/.test(id)) throw new Error('group id must be an existing group-chat id returned by find');
      const name = string(target.name, 'group name');
      if (name !== name.trim()) throw new Error('group name must be the exact name returned by find');
      return { operation: 'send', target: { kind: 'group', id, name }, text };
    }
    throw new Error('target.kind must be person or group');
  }
  throw new Error('operation must be open-window, find, or send');
}

export function exactRecipientIndex(candidates: readonly (Person | Group)[], target: PersonTarget | GroupTarget): number {
  const matches: number[] = [];
  for (let index = 0; index < candidates.length; index++) {
    const candidate = candidates[index]!;
    const exact = candidate.kind === 'person' && target.kind === 'person'
      ? candidate.email.toLowerCase() === target.email.toLowerCase()
      : candidate.kind === 'group' && target.kind === 'group' && candidate.id === target.id && candidate.name === target.name;
    if (exact) matches.push(index);
  }
  if (matches.length !== 1) throw new Error(`Exact recipient matched ${matches.length} results; nothing was sent`);
  return matches[0]!;
}

function normalizeLines(value: string): string {
  return value.replace(/\r\n?/g, '\n');
}

async function uiFrame(page: Page, target?: PersonTarget | GroupTarget): Promise<Frame> {
  const candidates: Frame[] = [];
  for (const frame of page.frames()) {
    let url: URL;
    try { url = new URL(frame.url()); } catch { continue; }
    if (url.protocol !== 'https:' || url.hostname !== 'teams.microsoft.com' || !url.pathname.startsWith('/v2/')) continue;
    if (await frame.locator(SEARCH).count() === 1 && await frame.locator('button[data-tid="me-control-avatar-trigger"]:visible').count() === 1) {
      candidates.push(frame);
    } else if (target && await frame.locator(SEARCH).count() === 0 && await frame.locator(EDITOR).count() === 1) {
      if (target.kind === 'group') {
        await verifyGroupPopup(frame, target);
        candidates.push(frame);
      } else if (await frame.locator(PICKER).count() === 1 && (await composer(frame)).id === 'newchat') {
        candidates.push(frame);
      }
    }
  }
  if (candidates.length !== 1) throw new Error(`Unsupported or ambiguous Teams UI: ${candidates.length} working frames`);
  return candidates[0]!;
}

async function unique(locator: Locator, label: string): Promise<Locator> {
  if (await locator.count() !== 1) throw new Error(`Expected exactly one ${label}; UI is unsupported or ambiguous`);
  return locator;
}

async function noDraft(frame: Frame): Promise<void> {
  const editors = frame.locator(EDITOR);
  for (const editor of await editors.all()) {
    const occupied = await editor.evaluate(element => {
      if ((element.textContent ?? '').length > 0 || element.querySelector('img,svg,video,audio')) return true;
      const footer = element.closest('[data-tid="message-pane-footer"]');
      if (!footer) return true;
      const walker = document.createTreeWalker(footer, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const parent = node.parentElement;
        if (!parent || parent.closest('style,script,svg,[data-tid="ckeditor"]') || !(node.textContent ?? '').trim()) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        if ([...range.getClientRects()].some(rect => rect.width > 0 && rect.height > 0)) return true;
      }
      return [...footer.querySelectorAll('img,video,audio')].some(media => media.getBoundingClientRect().width > 0);
    });
    if (occupied) throw new Error('Existing draft or attachment detected; it was not changed. Save or clear it manually before automation.');
  }
}

function nativeWindowReady(): boolean {
  if (location.protocol !== 'https:' || location.hostname !== 'teams.microsoft.com' || !location.pathname.startsWith('/v2/')) return false;
  const visible = (selector: string) => [...document.querySelectorAll(selector)]
    .filter(element => element.getBoundingClientRect().width > 0 && element.getBoundingClientRect().height > 0);
  if (visible('input[data-tid="AUTOSUGGEST_INPUT"][role="combobox"]').length === 1
      && visible('button[data-tid="me-control-avatar-trigger"]').length === 1) return true;
  const editors = visible('[data-tid="ckeditor"][role="textbox"][contenteditable="true"]');
  if (visible('input[data-tid="people-picker-search"][role="combobox"]').length !== 1 || editors.length !== 1) return false;
  try {
    const editor = editors[0]!;
    const names = JSON.parse(editor.getAttribute('data-tabster') ?? 'null')?.observed?.names;
    return Array.isArray(names) && names.includes(`compose-editor:${JSON.stringify([editor.id, 'newchat'])}`);
  } catch { return false; }
}

type NativeWindowInfo = { title: string; url: string; searchable: boolean };

async function inspectNativeWindow(root: CDPSession, targetId: string, timeout: number): Promise<NativeWindowInfo> {
  const { sessionId } = await root.send('Target.attachToTarget', { targetId, flatten: false });
  const { promise, resolve, reject } = Promise.withResolvers<NativeWindowInfo>();
  const timer = setTimeout(() => reject(new Error(`Native target ${targetId} did not become ready.`)), timeout + 1_000);
  const receive = (event: { sessionId: string; message: string }) => {
    if (event.sessionId !== sessionId) return;
    try {
      const reply = JSON.parse(event.message);
      if (reply.id !== 1) return;
      const value = reply.result?.result?.value;
      if (reply.error || reply.result?.exceptionDetails || !value || typeof value.title !== 'string'
          || typeof value.url !== 'string' || typeof value.searchable !== 'boolean') {
        reject(new Error(`Native target ${targetId} did not expose a supported ready UI.`));
      } else resolve(value);
    } catch (error) { reject(error); }
  };
  root.on('Target.receivedMessageFromTarget', receive);
  try {
    const expression = `(async (ready, timeout) => {
      const deadline = Date.now() + timeout;
      while (!ready()) {
        if (Date.now() >= deadline) return null;
        const delay = Promise.withResolvers();
        setTimeout(delay.resolve, 100);
        await delay.promise;
      }
      return { title: document.title, url: location.href, searchable: !!document.querySelector('input[data-tid="AUTOSUGGEST_INPUT"]') };
    })(${nativeWindowReady.toString()}, ${timeout})`;
    void root.send('Target.sendMessageToTarget', { sessionId, message: JSON.stringify({
      id: 1, method: 'Runtime.evaluate', params: { expression, returnByValue: true, awaitPromise: true },
    }) }).catch(reject);
    return await promise;
  } finally {
    clearTimeout(timer);
    root.off('Target.receivedMessageFromTarget', receive);
    await root.send('Target.detachFromTarget', { sessionId }).catch(() => undefined);
  }
}

async function openWindow(page: Page, frame: Frame): Promise<unknown> {
  await (await unique(frame.getByRole('button', { name: 'New items', exact: true }), 'New items button')).click();
  const action = await unique(frame.locator('[data-testid="simple-collab-left-rail-header-create-chat-popout"]:visible'), 'New message in new window action');
  const browser = page.context().browser();
  if (!browser) throw new Error('Native Teams window discovery requires the attached desktop browser');
  const root = await browser.newBrowserCDPSession();
  const mainSession = await page.context().newCDPSession(page);
  let contextId: string | undefined;
  try { contextId = (await mainSession.send('Target.getTargetInfo')).targetInfo.browserContextId; }
  finally { await mainSession.detach(); }
  try {
    const before = new Set((await root.send('Target.getTargets')).targetInfos.map(target => target.targetId));
    const added = async () => (await root.send('Target.getTargets')).targetInfos.filter(target =>
      !before.has(target.targetId) && target.type === 'page' && target.browserContextId === contextId
      && target.url.startsWith('https://teams.microsoft.com/v2/'));
    await action.click();
    const deadline = Date.now() + TIMEOUT;
    while (Date.now() < deadline) {
      const candidates = await added();
      if (candidates.length > 1) throw new Error('Multiple native Teams targets appeared; window ownership is ambiguous. No main-window fallback.');
      if (candidates.length === 1) {
        const target = candidates[0]!;
        const info = await inspectNativeWindow(root, target.targetId, Math.max(1, deadline - Date.now()));
        const confirmed = await added();
        if (confirmed.length !== 1 || confirmed[0]!.targetId !== target.targetId) throw new Error('Native window identity changed; no window was selected.');
        return {
          operation: 'open-window', target: { id: target.targetId, title: info.title, url: info.url },
          supported: { find: info.searchable, send: true }, requiresNewConnection: true,
          limitation: 'Use the returned exact target in a fresh Teams command/connection. WebView2 can expose the native popup before an existing Playwright connection materializes a usable Page. The empty new-message popup supports exact-email person sending; existing-group popouts require exact group ID/name. Never fall back to the human main window.',
        };
      }
      await Bun.sleep(100);
    }
    throw new Error('No additional supported native Teams window appeared. Inspect app prerequisites; the main chat was not used as a fallback.');
  } finally { await root.detach(); }
}

async function composer(frame: Frame): Promise<{ editor: Locator; id: string; editorId: string; identity: string }> {
  const editor = await unique(frame.locator(EDITOR), 'chat composer');
  const raw = await editor.getAttribute('data-tabster');
  let value: unknown;
  try { value = JSON.parse(raw ?? 'null'); } catch { throw new Error('Unsupported composer identity metadata'); }
  const names = object(object(value, 'composer metadata').observed, 'composer observed metadata').names;
  if (!Array.isArray(names)) throw new Error('Unsupported composer identity metadata');
  const identities = names.filter((name): name is string => typeof name === 'string' && name.startsWith('compose-editor:'));
  if (identities.length !== 1) throw new Error('Missing or ambiguous composer conversation identity');
  let identity: unknown;
  try { identity = JSON.parse(identities[0]!.slice('compose-editor:'.length)); } catch { throw new Error('Unsupported composer conversation identity'); }
  if (!Array.isArray(identity) || identity.length !== 2 || typeof identity[0] !== 'string' || !identity[0] || identity[0] !== await editor.getAttribute('id') || typeof identity[1] !== 'string') {
    throw new Error('Unsupported composer conversation identity');
  }
  return { editor: frame.locator(`[id=${JSON.stringify(identity[0])}][data-tid="ckeditor"]:visible`), id: identity[1], editorId: identity[0], identity: identities[0]! };
}

async function verifyGroupPopup(frame: Frame, target: GroupTarget): Promise<void> {
  if ((await composer(frame)).id !== target.id) throw new Error('Dedicated group window does not match the exact requested conversation ID; nothing was sent');
  const title = await unique(frame.locator('h2[data-tid="chat-title"] #custom-chat-topic-renderer:visible'), 'dedicated group window title');
  if (await title.innerText() !== target.name) throw new Error('Dedicated group window name changed; rediscover before sending');
}

async function search(frame: Frame, query: string, kind: 'person' | 'group'): Promise<void> {
  await noDraft(frame);
  const search = await unique(frame.locator(SEARCH), 'global search box');
  // Start outside Search so old result cards cannot satisfy the new search's waits.
  await (await unique(frame.getByRole('button', { name: 'Chat', exact: true }), 'Chat navigation button')).click();
  await frame.locator('[data-tid="people-tab"]:visible').waitFor({ state: 'hidden', timeout: TIMEOUT });
  await noDraft(frame);
  await search.fill(query);
  await search.press('Enter');
  const tab = frame.locator(`[data-tid="${kind === 'person' ? 'people' : 'groupchats'}-tab"]:visible`);
  await tab.waitFor({ timeout: TIMEOUT });
  await (await unique(tab, 'search domain tab')).click();
  await frame.locator(kind === 'person'
    ? `${PERSON_CARD}:visible, [data-tid="search-no-results"]:visible`
    : `${GROUP_CARD}:visible, [data-tid="search-no-results"]:visible`).first().waitFor({ timeout: TIMEOUT });
  if (await tab.getAttribute('aria-selected') !== 'true') throw new Error('Search domain selection did not complete');
}

async function people(frame: Frame): Promise<Person[]> {
  const cards = frame.locator(`${PERSON_CARD}:visible`);
  const results: Person[] = [];
  for (const card of await cards.all()) {
    const person = await card.evaluate(element => {
      const emailNodes = [...element.querySelectorAll('div,span,a')].filter(node => node.childElementCount === 0 && /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test((node.textContent ?? '').trim()));
      const emails = [...new Set(emailNodes.map(node => (node.textContent ?? '').trim()))];
      const name = element.querySelector('[id^="menu"]')?.textContent?.trim() ?? '';
      return { id: element.id.slice('serp-people-card-content-'.length), name, emails };
    });
    if (!/^[0-9a-f-]{36}$/i.test(person.id) || !person.name || person.emails.length !== 1) {
      throw new Error('Person result lacks an unambiguous visible email/name/identifier; refusing to guess');
    }
    results.push({ kind: 'person', id: person.id, name: person.name, email: person.emails[0]! });
  }
  return results;
}

async function groupCards(frame: Frame): Promise<GroupCard[]> {
  const cards = frame.locator(`${GROUP_CARD}:visible`);
  const results: GroupCard[] = [];
  for (let index = 0; index < await cards.count(); index++) {
    const name = await cards.nth(index).evaluate(element => {
      const label = element.parentElement?.querySelector('[data-tid="carousel-card-button"]')?.getAttribute('aria-label') ?? '';
      return /^group chat card from (.+) is selected\. Press Enter to open the group chat and press Tab to navigate within the group chat card\.$/s.exec(label)?.[1] ?? '';
    });
    if (!name) throw new Error('Unsupported group result card: exact group name is unavailable');
    results.push({ index, name });
  }
  return results;
}

async function openGroup(frame: Frame, card: GroupCard): Promise<Group> {
  const previousId = await frame.locator(EDITOR).count() ? (await composer(frame)).id : null;
  await frame.locator(`${GROUP_CARD}:visible`).nth(card.index).click();
  const selected = await frame.waitForFunction(({ previousId, name }) => {
    const visible = (element: Element) => {
      const bounds = element.getBoundingClientRect();
      return bounds.width > 0 && bounds.height > 0 && getComputedStyle(element).visibility === 'visible';
    };
    const editors = [...document.querySelectorAll<HTMLElement>('[data-tid="ckeditor"][role="textbox"][contenteditable="true"]')].filter(visible);
    const titles = [...document.querySelectorAll<HTMLElement>('h2[data-tid="chat-title"] #custom-chat-topic-renderer')].filter(visible);
    if (editors.length !== 1 || titles.length !== 1 || titles[0]!.innerText !== name) return false;
    const editor = editors[0]!;
    try {
      const names: unknown = JSON.parse(editor.getAttribute('data-tabster') ?? 'null')?.observed?.names;
      if (!Array.isArray(names)) return false;
      const identities = names.filter((value): value is string => typeof value === 'string' && value.startsWith('compose-editor:'));
      if (identities.length !== 1) return false;
      const identity: unknown = JSON.parse(identities[0]!.slice('compose-editor:'.length));
      if (!Array.isArray(identity) || identity.length !== 2 || !editor.id || identity[0] !== editor.id
          || typeof identity[1] !== 'string' || !/^19:[a-zA-Z0-9-]+@thread\.v2$/.test(identity[1]) || identity[1] === previousId) return false;
      return { kind: 'group' as const, id: identity[1], name };
    } catch { return false; }
  }, { previousId, name: card.name }, { timeout: TIMEOUT, polling: 100 });
  try { return await selected.jsonValue() as Group; }
  finally { await selected.dispose(); }
}

async function groups(frame: Frame, query: string): Promise<Group[]> {
  let cards = await groupCards(frame);
  const results: Group[] = [];
  for (let index = 0; index < cards.length; index++) {
    if (index > 0) {
      await search(frame, query, 'group');
      const refreshed = await groupCards(frame);
      if (JSON.stringify(refreshed) !== JSON.stringify(cards)) throw new Error('Group search results changed during discovery; rerun find');
      cards = refreshed;
    }
    results.push(await openGroup(frame, cards[index]!));
  }
  if (new Set(results.map(group => group.id)).size !== results.length) throw new Error('Duplicate group identifiers in search results; refusing ambiguity');
  return results;
}

async function verifySelf(frame: Frame, email: string): Promise<void> {
  const trigger = await unique(frame.locator('button[data-tid="me-control-avatar-trigger"]:visible'), 'profile button');
  await trigger.click();
  try {
    const signOut = frame.locator('button[data-tid="me-control-sign-out-button"]:visible');
    await signOut.waitFor({ timeout: TIMEOUT });
    const label = await (await unique(signOut, 'signed-in account identity')).getAttribute('aria-label');
    if (label?.toLowerCase() !== `Sign out from ${email}`.toLowerCase()) throw new Error('Self-chat recipient does not match the requested email');
  } finally {
    await trigger.press('Escape');
  }
}

async function openPerson(frame: Frame, email: string): Promise<string> {
  await search(frame, email, 'person');
  const candidates = await people(frame);
  const person = candidates[exactRecipientIndex(candidates, { kind: 'person', email })]!;
  const card = frame.locator(`${PERSON_CARD}:visible`).filter({ has: frame.getByText(person.email, { exact: true }) });
  await (await unique(card, 'exact-email person result')).click();
  await frame.locator(EDITOR).waitFor({ timeout: TIMEOUT });
  const current = await composer(frame);
  if (current.id === '48:notes') {
    await verifySelf(frame, email);
  } else {
    const participants = /^19:([0-9a-f-]{36})_([0-9a-f-]{36})@unq\.gbl\.spaces$/i.exec(current.id);
    if (!participants || !participants.slice(1).some(id => id.toLowerCase() === person.id.toLowerCase())) {
      throw new Error('Opened conversation does not prove the exact selected person identity');
    }
  }
  return current.id;
}

async function openPopupPerson(frame: Frame, email: string): Promise<string> {
  const initial = await composer(frame);
  if (initial.id !== 'newchat') throw new Error('Person popup already has a selected conversation; it was not changed');
  const picker = await unique(frame.locator(PICKER), 'native recipient picker');
  const untouched = await picker.evaluate(element => {
    const control = element.closest('.fui-TagPickerControl');
    return element instanceof HTMLInputElement && element.value === '' && control
      && [...control.children].every(child => child.contains(element));
  });
  if (!untouched) throw new Error('Existing recipient selection or picker query detected; it was not changed');
  const listId = await picker.getAttribute('aria-controls');
  if (!listId) throw new Error('Native recipient picker has no bound suggestion list');
  await picker.fill(email);
  const exact = frame.locator(`[id=${JSON.stringify(listId)}] [role="option"][data-type="Person"][data-tid=${JSON.stringify(`people-picker-entry-${email}`)} i]:visible`);
  await exact.waitFor({ timeout: TIMEOUT });
  const row = await (await unique(exact, 'exact-email person picker result')).elementHandle();
  if (!row) throw new Error('Exact-email person result disappeared before selection');
  const person = await row.evaluate(element => {
    const email = element.getAttribute('data-tid')?.slice('people-picker-entry-'.length) ?? '';
    const ids = new Set<string>();
    for (const image of element.querySelectorAll('img[src]')) {
      const url = new URL(image.getAttribute('src')!, location.href);
      const match = /^\/api\/mt\/part\/msft\/beta\/users\/([0-9a-f-]{36})\/profilepicturev2\/8:orgid:([0-9a-f-]{36})$/i.exec(decodeURIComponent(url.pathname));
      if (url.protocol === 'https:' && url.hostname === 'teams.microsoft.com' && match && match[1]!.toLowerCase() === match[2]!.toLowerCase()) ids.add(match[1]!.toLowerCase());
    }
    const self = [...element.querySelectorAll('span')].some(node => node.childElementCount === 0 && (node.textContent ?? '').trim().endsWith(' (You)'));
    return { email, ids: [...ids], self };
  });
  if (person.email.toLowerCase() !== email.toLowerCase() || person.ids.length !== 1
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(person.ids[0]!)) {
    throw new Error('Native person result does not prove one exact email and immutable directory ID; nothing was selected or sent');
  }
  await noDraft(frame);
  const stillUnselected = await picker.evaluate((element, email) => {
    const control = element.closest('.fui-TagPickerControl');
    return element instanceof HTMLInputElement && element.value.toLowerCase() === email.toLowerCase() && control
      && [...control.children].every(child => child.contains(element));
  }, email);
  const before = await composer(frame);
  if (!stillUnselected || before.id !== 'newchat' || before.editorId !== initial.editorId) throw new Error('Recipient selection changed during discovery; nothing was selected or sent');
  await row.click();
  const selected = await frame.waitForFunction(({ editorId, personId, self }) => {
    const editor = document.getElementById(editorId);
    if (!editor?.isConnected) throw new Error('Native composer changed while selecting the exact recipient');
    const names = JSON.parse(editor.getAttribute('data-tabster') ?? 'null')?.observed?.names;
    if (!Array.isArray(names)) return false;
    const identities = names.filter((name): name is string => typeof name === 'string' && name.startsWith('compose-editor:'));
    if (identities.length !== 1) return false;
    const identity: unknown = JSON.parse(identities[0]!.slice('compose-editor:'.length));
    if (!Array.isArray(identity) || identity[0] !== editorId || typeof identity[1] !== 'string') return false;
    if (identity[1] === '48:notes') return self ? identity[1] : false;
    const participants = /^19:([0-9a-f-]{36})_([0-9a-f-]{36})@unq\.gbl\.spaces$/i.exec(identity[1]);
    return participants?.slice(1).some(id => id.toLowerCase() === personId) ? identity[1] : false;
  }, { editorId: initial.editorId, personId: person.ids[0]!, self: person.self }, { timeout: TIMEOUT });
  const conversationId: unknown = await selected.jsonValue();
  if (typeof conversationId !== 'string' || (await composer(frame)).id !== conversationId) throw new Error('Native conversation identity changed after exact recipient selection');
  return conversationId;
}

async function send(frame: Frame, request: Extract<TeamsRequest, { operation: 'send' }>): Promise<unknown> {
  let conversationId: string;
  if (request.target.kind === 'group' && await frame.locator(SEARCH).count() === 0) {
    await verifyGroupPopup(frame, request.target);
    conversationId = request.target.id;
  } else if (request.target.kind === 'person') {
    conversationId = await frame.locator(SEARCH).count() === 0
      ? await openPopupPerson(frame, request.target.email)
      : await openPerson(frame, request.target.email);
  } else {
    const target = request.target;
    await search(frame, request.target.name, 'group');
    const cards = await groupCards(frame);
    const exact = cards.filter(card => card.name === target.name);
    if (exact.length === 0) throw new Error('Exact group name was not found; nothing was sent');
    const candidates: { group: Group; card: GroupCard }[] = [];
    for (let index = 0; index < exact.length; index++) {
      if (index > 0) {
        await search(frame, request.target.name, 'group');
        if (JSON.stringify(await groupCards(frame)) !== JSON.stringify(cards)) throw new Error('Group results changed; rerun find before sending');
      }
      candidates.push({ group: await openGroup(frame, exact[index]!), card: exact[index]! });
    }
    const selected = candidates[exactRecipientIndex(candidates.map(candidate => candidate.group), target)]!;
    if ((await composer(frame)).id !== request.target.id) {
      await search(frame, request.target.name, 'group');
      if (JSON.stringify(await groupCards(frame)) !== JSON.stringify(cards)) throw new Error('Group results changed; rerun find before sending');
      if ((await openGroup(frame, selected.card)).id !== request.target.id) throw new Error('Group identity changed; nothing was sent');
    }
    conversationId = request.target.id;
  }
  await noDraft(frame);
  const current = await composer(frame);
  if (current.id !== conversationId) throw new Error('Conversation identity changed before composing');
  const editor = await current.editor.elementHandle() as ElementHandle<HTMLElement> | null;
  if (!editor) throw new Error('The verified composer disappeared before composing');
  const before = await frame.locator('[data-tid="chat-pane-message"][data-mid]').evaluateAll(elements => {
    const ids = elements.map(element => element.getAttribute('data-mid')!);
    if (ids.some(id => !/^\d+$/.test(id))) throw new Error('Unsupported message ordering metadata');
    return { ids, highWatermark: ids.reduce((highest, id) => BigInt(id) > BigInt(highest) ? id : highest, '0'), capturedAt: Date.now() };
  });
  const lines = normalizeLines(request.text).split('\n');
  const input = await frame.page().context().newCDPSession(frame.page());
  try {
    // CKEditor discards execCommand edits; trusted input plus separate breaks retains empty paragraphs.
    for (let index = 0; index < lines.length; index++) {
      await editor.evaluate((element, { identity, editorId, requireEmpty }) => {
        const names = JSON.parse(element.getAttribute('data-tabster') ?? 'null')?.observed?.names;
        if (!element.isConnected || element.id !== editorId || !Array.isArray(names) || !names.includes(identity)
            || (requireEmpty && (element.textContent ?? '').length > 0)) throw new Error('The verified composer changed; its draft was not replaced');
        element.focus();
      }, { identity: current.identity, editorId: current.editorId, requireEmpty: index === 0 });
      if (index > 0) await editor.press('Shift+Enter');
      if (lines[index]) await input.send('Input.insertText', { text: lines[index]! });
    }
  } finally { await input.detach(); }
  const composed = await editor.evaluate(element => {
    const paragraphs = [...element.children] as HTMLElement[];
    return paragraphs.length && paragraphs.every(node => node.tagName === 'P')
      ? paragraphs.map(node => node.innerText === '\n' ? '' : node.innerText).join('\n')
      : element.innerText;
  }).finally(() => editor.dispose().catch(() => undefined));
  if (normalizeLines(composed) !== normalizeLines(request.text)) {
    throw new Error('Composer did not preserve the exact text. Nothing was sent; inspect the retained draft manually.');
  }
  // Text entry may remount the footer; bind its current exact node only after the text settles.
  const dispatchEditor = await current.editor.elementHandle() as ElementHandle<HTMLElement> | null;
  if (!dispatchEditor) throw new Error('The verified composer disappeared before dispatch');
  const footerHandle = await dispatchEditor.evaluateHandle(element => element.closest('[data-tid="message-pane-footer"]'));
  const footer = footerHandle.asElement();
  if (!footer) throw new Error('The verified composer has no message footer');
  const buttons = await footer.$$('button[data-tid="sendMessageCommands-send"]:visible, button[data-tid="newMessageCommands-send"]:visible');
  if (buttons.length !== 1) throw new Error('Expected exactly one Send button in the verified composer footer');
  const sendButton = buttons[0]!;
  let dispatchAttempted = true;
  try {
    // Transport failures remain uncertain; a returned rejection proves no click occurred.
    const rejected = await sendButton.evaluate((button, { editor, footer, identity, editorId, text }) => {
      const names = JSON.parse(editor.getAttribute('data-tabster') ?? 'null')?.observed?.names;
      if (!editor.isConnected || !footer.isConnected || !button.isConnected || editor.id !== editorId
          || !Array.isArray(names) || !names.includes(identity) || editor.closest('[data-tid="message-pane-footer"]') !== footer
          || !footer.contains(button) || !footer.contains(editor)) return 'The verified composer or Send button changed; nothing was sent';
      const visibleEditors = [...document.querySelectorAll('[data-tid="ckeditor"][contenteditable="true"]')]
        .filter(element => element.getBoundingClientRect().width > 0 && element.getBoundingClientRect().height > 0);
      const paragraphs = [...editor.children] as HTMLElement[];
      const composed = paragraphs.length && paragraphs.every(node => node.tagName === 'P')
        ? paragraphs.map(node => node.innerText === '\n' ? '' : node.innerText).join('\n') : editor.innerText;
      const bounds = button.getBoundingClientRect();
      const blocked = [...document.querySelectorAll('[role="dialog"],[role="alertdialog"],[role="menu"]')]
        .some(element => element.getClientRects().length > 0 && getComputedStyle(element).visibility === 'visible');
      if (blocked || visibleEditors.length !== 1 || visibleEditors[0] !== editor || composed.replace(/\r\n?/g, '\n') !== text
          || !(button instanceof HTMLButtonElement) || button.disabled || button.getAttribute('aria-disabled') === 'true'
          || bounds.width <= 0 || bounds.height <= 0 || getComputedStyle(button).visibility !== 'visible') {
        return 'The verified destination, text, or Send availability changed; nothing was sent';
      }
      button.click();
      return null;
    }, { editor: dispatchEditor, footer, identity: current.identity, editorId: current.editorId, text: normalizeLines(request.text) });
    if (rejected !== null) {
      dispatchAttempted = false;
      throw new Error(rejected);
    }
    const receipt = await frame.waitForFunction(({ previous, highWatermark, notBefore, text, editorId, identity }) => {
      const editor = document.getElementById(editorId);
      const names = JSON.parse(editor?.getAttribute('data-tabster') ?? 'null')?.observed?.names;
      if (!editor?.isConnected || !Array.isArray(names) || !names.includes(identity)) throw new Error('Conversation changed while waiting for receipt');
      for (const message of document.querySelectorAll('[data-tid="chat-pane-message"][data-mid]')) {
        const mid = message.getAttribute('data-mid');
        if (!mid || !/^\d+$/.test(mid) || previous.includes(mid) || BigInt(mid) <= BigInt(highWatermark)) continue;
        const timestamp = document.getElementById(`timestamp-${mid}`)?.getAttribute('datetime');
        const sentAt = timestamp ? Date.parse(timestamp) : NaN;
        if (!Number.isFinite(sentAt) || sentAt < notBefore) continue;
        const content = document.getElementById(`content-${mid}`);
        if (!content) continue;
        const body = content.querySelector<HTMLElement>(':scope > [data-ask-copilot-content]') ?? content;
        const paragraphs = [...body.children] as HTMLElement[];
        const expectedLines = text.split('\n');
        const rendered = paragraphs.length && paragraphs.every(node => node.tagName === 'P')
          ? paragraphs.map((node, index) => node.innerText === '\n' || (expectedLines[index] === '' && node.innerText === '\u00a0') ? '' : node.innerText).join('\n')
          : body.innerText;
        if (rendered.replace(/\r\n?/g, '\n') !== text) continue;
        const failure = document.getElementById(`failure-status-${mid}`);
        if (failure && (failure.textContent ?? '').trim()) throw new Error('Teams reported a message delivery failure');
        const status = document.getElementById(`read-status-icon-${mid}`);
        if (status?.getAttribute('role') === 'img' && status.getAttribute('aria-label') === 'Sent') {
          return { messageId: mid, status: 'Sent' };
        }
      }
      return false;
    }, { previous: before.ids, highWatermark: before.highWatermark, notBefore: Math.floor(before.capturedAt / 1000) * 1000, text: normalizeLines(request.text), editorId: current.editorId, identity: current.identity }, { timeout: TIMEOUT });
    return { operation: 'send', target: request.target, conversationId, receipt: await receipt.jsonValue() };
  } catch (error) {
    if (dispatchAttempted) throw new Error(`Uncertain send outcome; NEVER automatically resend. Inspect the target chat manually. ${error instanceof Error ? error.message : String(error)}`);
    throw error;
  } finally {
    await sendButton.dispose().catch(() => undefined);
    await footerHandle.dispose().catch(() => undefined);
    await dispatchEditor.dispose().catch(() => undefined);
  }
}

export async function execute(page: Page, input: unknown): Promise<unknown> {
  const request = parseRequest(input);
  const frame = await uiFrame(page, request.operation === 'send' ? request.target : undefined);
  if (request.operation === 'open-window') return await openWindow(page, frame);
  await noDraft(frame);
  if (request.operation === 'send') return await send(frame, request);
  await search(frame, request.query, request.kind);
  const results = request.kind === 'person' ? await people(frame) : await groups(frame, request.query);
  return { operation: 'find', kind: request.kind, query: request.query, results, scope: 'Teams UI search results currently returned by the signed-in client; not a complete directory inventory' };
}

if (import.meta.main) await runCli('teams', execute);
