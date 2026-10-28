import type { ElementHandle, Frame, Locator, Page } from 'playwright-core';
import { runCli } from './cdp.ts';
import { watchReceipt, type ReceiptGuard } from './receipt-guard.ts';

export type Mode = 'chat' | 'code';
export type Request =
  | { operation: 'inspect' }
  | { operation: 'models'; mode: Mode }
  | { operation: 'read'; mode: Mode }
  | { operation: 'send'; mode: Mode; model?: string; text: string };

type ModelChoice = { label: string; group: string | null; selected: boolean };

export function findExactModel(choices: readonly ModelChoice[], label: string): ModelChoice {
  const matches = choices.filter(choice => choice.label === label);
  if (matches.length !== 1) throw new Error(`Exact model label is unavailable or ambiguous: ${label}. Use the models operation.`);
  return matches[0]!;
}
type ChatTurn = { id: string; index: number; question: string; reply: string; complete: boolean };
type CodeTurn = ChatTurn & { turnId: string; userId: string; live: string | null; stepStatuses: (string | null)[] };
type CodeBlocker = { kind: 'permission' | 'dialog'; labels: string[] };
type CodeSnapshot = { sessionId: string | null; state: 'empty' | 'complete' | 'generating' | 'incomplete' | 'permission-blocked' | 'dialog-blocked'; blocker: CodeBlocker | null; turns: CodeTurn[] };
type ComposerHandle = ElementHandle<HTMLElement | SVGElement>;
type ComposerProof = { mode: Mode; route: string; modelLabel: string; modeSelector: string };
type ComposerCommand = { kind: 'read' } | { kind: 'prepare'; proof: ComposerProof } | { kind: 'send'; text: string; proof: ComposerProof };
const HOST = 'cr.m365copilotapp.svc.cloud.microsoft';
const CHAT_EDITOR = '[role="textbox"][aria-label="Message Copilot"]';
const CODE_EDITOR = '[data-testid="lexical-chat-editor"][role="textbox"]';
const TURN = '[data-testid="m365-chat-llm-web-ui-chat-message"]';
const REPLY = '[data-testid="copilot-message-div"]';
const TIMEOUT = 120_000;

const modeNavigation = (mode: Mode) => `button[role="button"][value="${mode}"][aria-label="${mode === 'chat' ? 'Chat' : 'Code'}"][aria-haspopup="menu"]`;

export function matchesChatPrompt(rendered: string, requested: string): boolean {
  return rendered === `${requested}\n`;
}

export function parseCodeModelLabel(label: string): { model: string; effort: string | null } {
  const match = /^Model: (.+?)(?:, effort: (.+))?$/.exec(label);
  if (!match || /^(?:Models unavailable|Loading models(?:…|\.{3})?)$/.test(match[1]!)) throw new Error('Code model is unavailable or its toolbar label is unsupported.');
  return { model: match[1]!, effort: match[2] ?? null };
}

export function codeSessionId(value: string): string | null {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.hostname !== HOST || url.pathname !== '/hwav2/code') throw new Error('Unsupported Code session URL.');
  if (!url.hash || url.hash === '#/sessions') return null;
  const match = /^#\/sessions\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.exec(url.hash);
  if (!match) throw new Error('Unsupported Code session route.');
  return match[1]!;
}

export function chatSessionId(value: string): string | null {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.hostname !== HOST || url.hash) throw new Error('Unsupported Chat session URL.');
  if (url.pathname === '/hwav2/chat' || url.pathname === '/hwav2/chat/web') return null;
  const match = /^\/hwav2\/chat\/conversation\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.exec(url.pathname);
  if (!match) throw new Error('Unsupported Chat conversation route.');
  return match[1]!;
}

export function parseCodeTurnId(value: string): { turnId: string; role: 'user' | 'assistant' } {
  const match = /^((?:turn-)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):(user|assistant)$/i.exec(value);
  if (!match || (match[2] !== 'user' && match[2] !== 'assistant')) throw new Error('Unsupported Code message identity.');
  return { turnId: match[1]!, role: match[2] };
}

export function codeReplyComplete(evidence: { live: string | null; stepStatuses: readonly (string | null)[]; sameMessage: boolean; copyReady: boolean; regenerateReady: boolean; reply: string }): boolean {
  return evidence.live === 'false' && evidence.stepStatuses.every(status => status === 'done') && evidence.sameMessage && evidence.copyReady && evidence.regenerateReady && !!evidence.reply.trim();
}

export function parseRequest(value: unknown): Request {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Request must be a JSON object.');
  const request = value as Record<string, unknown>;
  const operation = request.operation;
  if (!['inspect', 'models', 'read', 'send'].includes(String(operation))) throw new Error('operation must be inspect, models, read, or send.');
  const allowed = operation === 'inspect' ? ['operation'] : operation === 'send' ? ['operation', 'mode', 'model', 'text'] : ['operation', 'mode'];
  if (Object.keys(request).some(key => !allowed.includes(key))) throw new Error('Request contains unsupported fields.');
  if (operation === 'inspect') return { operation };
  if (request.mode !== 'chat' && request.mode !== 'code') throw new Error('mode must be chat or code.');
  if (operation === 'models' || operation === 'read') return { operation, mode: request.mode };
  if (typeof request.text !== 'string' || !request.text.trim() || request.text.includes('\0')) throw new Error('text must be a nonblank string without NUL.');
  if ('model' in request && (typeof request.model !== 'string' || !request.model.trim() || request.model !== request.model.trim())) throw new Error('model must be an exact, nonblank UI label.');
  return request.model === undefined
    ? { operation: 'send', mode: request.mode, text: request.text }
    : { operation: 'send', mode: request.mode, text: request.text, model: request.model as string };
}

function uiFrame(page: Page): Frame {
  const frames = page.frames().filter(frame => {
    try {
      const url = new URL(frame.url());
      return url.hostname === HOST && /^\/hwav2\/(chat|code)(\/|$)/.test(url.pathname);
    } catch { return false; }
  });
  if (frames.length !== 1) throw new Error(`Unsupported or ambiguous Copilot UI: expected one working frame on ${HOST}, found ${frames.length}. Select the actual desktop webview, not edge://olympia.top-chrome/ or a PWA.`);
  return frames[0]!;
}

async function unique(locator: Locator, description: string): Promise<Locator> {
  if (await locator.count() !== 1) throw new Error(`Unsupported or ambiguous UI: expected one ${description}.`);
  return locator;
}

async function activeMode(frame: Frame): Promise<Mode> {
  const selected: Mode[] = [];
  for (const mode of ['chat', 'code'] as const) {
    const tab = frame.getByRole('tab', { name: mode === 'chat' ? 'Chat' : 'Code', exact: true });
    if (await tab.count() === 1 && await tab.getAttribute('aria-selected') === 'true') selected.push(mode);
  }
  if (selected.length === 0) {
    for (const mode of ['chat', 'code'] as const) {
      if (await frame.locator(modeNavigation(mode)).filter({ visible: true }).count() === 1) selected.push(mode);
    }
  }
  if (selected.length !== 1) throw new Error('Unsupported Copilot mode: select Chat or Code; Cowork is not supported.');
  const mode = selected[0]!;
  if (!new URL(frame.url()).pathname.startsWith(`/hwav2/${mode}`)) throw new Error('Mode tab and URL disagree; no action taken.');
  return mode;
}

async function editor(frame: Frame, mode: Mode): Promise<Locator> {
  return unique(frame.locator(mode === 'chat' ? CHAT_EDITOR : CODE_EDITOR).filter({ visible: true }), `${mode} composer`);
}

async function composerAction(handle: ComposerHandle, command: ComposerCommand, send: ComposerHandle | null = null, guard: ReceiptGuard['interaction'] | null = null): Promise<{ text: string; error: string | null; clicked: boolean }> {
  return handle.evaluate((node, { command, send, guard }) => {
    const element = node as HTMLElement;
    const text = () => {
      const copy = element.cloneNode(true) as HTMLElement;
      copy.querySelectorAll('[aria-hidden="true"]').forEach(hidden => hidden.remove());
      copy.querySelectorAll('br').forEach(br => br.replaceWith(br.parentElement?.tagName === 'P' && br.parentElement.childNodes.length === 1 ? '' : '\n'));
      const children = [...copy.children];
      if (children.some(child => child.tagName === 'P') && [...copy.childNodes].some(child => child.nodeType === Node.TEXT_NODE && !!child.textContent)) throw new Error('Unsupported mixed composer structure; existing content is preserved.');
      if (children.length && children.every(child => child.tagName === 'P')) return children.map(child => child.textContent ?? '').join('\n');
      if (children.some(child => child.tagName === 'P')) throw new Error('Unsupported mixed composer structure; existing content is preserved.');
      return copy.textContent ?? '';
    };
    const current = text();
    if (command.kind === 'read') return { text: current, error: null, clicked: false };
    const failure = (error: string) => ({ text: current, error, clicked: false });
    const { proof } = command;
    const root = element.getRootNode() as Document | ShadowRoot;
    const url = new URL(element.ownerDocument.URL);
    const expectedEditor = proof.mode === 'chat' ? '[role="textbox"][aria-label="Message Copilot"]' : '[role="textbox"][data-testid="lexical-chat-editor"]';
    const selected = [...element.ownerDocument.querySelectorAll(proof.modeSelector)].filter(control => control.getClientRects().length);
    const models = [...root.querySelectorAll('button')].filter(button => button.getAttribute('aria-label') === proof.modelLabel && button.getClientRects().length);
    if (!element.isConnected || !element.isContentEditable || !element.matches(expectedEditor) || !element.getClientRects().length || element.closest('[inert],[aria-hidden="true"]')) return failure('The bound composer is no longer active/editable.');
    if (`${url.origin}${url.pathname}${url.hash}` !== proof.route || selected.length !== 1 || models.length !== 1) return failure('Mode, session, or exact model changed; no action taken.');
    if (command.kind === 'prepare' && current.length) return failure('DRAFT_PRESENT: the bound composer gained content; preserved.');
    if (command.kind === 'send' && current !== command.text) return failure('Composer text changed; preserved without sending.');
    if (command.kind === 'send') {
      if (!guard || guard.document !== element.ownerDocument || guard.interacted || guard.disposed) return failure('Interaction or document change invalidated the Send proof.');
      const expectedSend = proof.mode === 'chat' ? 'button[aria-label="Send"]' : 'button[data-testid="send-button"][aria-label="Send message"]';
      const button = send as HTMLButtonElement | null;
      if (!button?.isConnected || button.getRootNode() !== root || !button.matches(expectedSend) || button.disabled || button.getAttribute('aria-disabled') === 'true' || !button.getClientRects().length || getComputedStyle(button).visibility === 'hidden' || button.closest('[inert],[aria-hidden="true"]')) return failure('The bound Send button is no longer actionable.');
      if ([...root.querySelectorAll('[role="dialog"],[role="alertdialog"],[role="menu"],dialog[data-slot="popover-content"]')].some(dialog => dialog.getClientRects().length)) return failure('A dialog or menu opened; preserved without sending.');
      if ([...root.querySelectorAll('button')].some(control => control.getClientRects().length && /^(?:approve|allow|grant permission)(?:\b|$)/i.test(control.getAttribute('aria-label') ?? control.innerText.trim()))) return failure('Permission approval requires manual interaction; no prompt sent.');
      button.click();
      return { text: current, error: null, clicked: true };
    }
    element.focus();
    if (text() !== current) return failure('Composer changed while gaining focus; preserved.');
    const selection = element.ownerDocument.getSelection();
    if (!selection) return failure('Composer selection is unavailable.');
    const range = element.ownerDocument.createRange();
    const paragraph = element.firstElementChild;
    range.selectNodeContents(paragraph?.tagName === 'P' ? paragraph : element);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    return { text: text(), error: null, clicked: false };
  }, { command, send, guard });
}

async function insertPrompt(frame: Frame, handle: ComposerHandle, proof: ComposerProof, text: string): Promise<void> {
  const input = await frame.page().context().newCDPSession(frame.page());
  try {
    const prepared = await composerAction(handle, { kind: 'prepare', proof });
    if (prepared.error) throw new Error(prepared.error);
    // Code's native editor needs separate breaks; multiline insertText creates extra DIV breaks.
    if (proof.mode === 'code') {
      const lines = text.split('\n');
      for (let index = 0; index < lines.length; index++) {
        if (index > 0) await handle.press('Shift+Enter');
        if (lines[index]) await input.send('Input.insertText', { text: lines[index]! });
      }
    } else await input.send('Input.insertText', { text });
    if ((await composerAction(handle, { kind: 'read' })).text !== text) throw new Error('Editor did not retain the exact prompt; draft preserved. No Send was attempted.');
  } finally { await input.detach(); }
}

async function composerText(input: Locator): Promise<string> {
  const handle = await input.elementHandle();
  if (!handle) throw new Error('Composer disappeared.');
  try { return (await composerAction(handle, { kind: 'read' })).text; }
  finally { await handle.dispose(); }
}

async function composerProof(frame: Frame, mode: Mode, model: string, expectedUrl: string): Promise<ComposerProof> {
  const expected = new URL(expectedUrl);
  const current = new URL(frame.url());
  const route = `${expected.origin}${expected.pathname}${expected.hash}`;
  if (`${current.origin}${current.pathname}${current.hash}` !== route) throw new Error('Conversation changed before composing.');
  const button = await unique(frame.getByRole('button', { name: mode === 'chat' ? /, Model Selector$/ : /^Model: / }).filter({ visible: true }), 'exact model toolbar');
  const modelLabel = await button.getAttribute('aria-label');
  if (!modelLabel || (mode === 'chat' ? modelLabel.replace(/, Model Selector$/, '') : parseCodeModelLabel(modelLabel).model) !== model) throw new Error('Model changed before composing.');
  const selectedTab = `[role="tab"][value="${mode}"][aria-selected="true"]`;
  const modeSelector = await frame.locator(selectedTab).isVisible() ? selectedTab : modeNavigation(mode);
  return { mode, route, modelLabel, modeSelector };
}

async function assertNoDraft(frame: Frame): Promise<void> {
  for (const input of await frame.locator(`${CHAT_EDITOR}, ${CODE_EDITOR}`).all()) {
    if ((await composerText(input)).length) throw new Error('DRAFT_PRESENT: existing draft is preserved. Send or clear it manually before changing modes, models, or composing.');
  }
}

async function selectMode(frame: Frame, mode: Mode): Promise<void> {
  const current = await activeMode(frame);
  if (current === mode) return;
  await assertNoDraft(frame);
  const tab = frame.getByRole('tab', { name: mode === 'chat' ? 'Chat' : 'Code', exact: true });
  if (await tab.count() === 1) await tab.click();
  else {
    await (await unique(frame.locator(modeNavigation(current)), 'current mode navigation')).click();
    const item = frame.getByRole('menu').getByRole('menuitem', { name: mode === 'chat' ? 'Chat' : 'Code', exact: true });
    await item.waitFor({ state: 'visible', timeout: 10_000 });
    await (await unique(item, 'requested mode menu item')).click();
  }
  await frame.waitForFunction(({ expected, navigation }) => {
    const control = document.querySelector(`[role="tab"][value="${expected}"][aria-selected="true"]`) ?? document.querySelector(navigation);
    return !!control?.getClientRects().length && location.pathname.startsWith(`/hwav2/${expected}`);
  }, { expected: mode, navigation: modeNavigation(mode) }, { timeout: 15_000 });
  if (await activeMode(frame) !== mode) throw new Error('Requested mode was not selected.');
}

async function codePrerequisite(frame: Frame): Promise<string | null> {
  const welcome = frame.getByRole('dialog').filter({ hasText: 'Welcome to Copilot Code' });
  if (await welcome.isVisible()) return 'CODE_ONBOARDING_REQUIRED: review the Copilot Code terms and choose Get started manually. Automation will not acknowledge permissions or initialize projects.';
  const model = frame.getByRole('button', { name: /^Model: / });
  if (await model.count() === 1 && /^Model: (?:Models unavailable|Loading models(?:…|\.{3})?)$/.test(await model.getAttribute('aria-label') ?? '')) return 'CODE_RUNTIME_NOT_READY: the native Code runtime has not provided models. Wait for supported native-host startup using the existing signed-in profile and connection consent; see setup.md. Do not copy credentials, create isolated profiles, approve execution, or change policy.';
  return null;
}

async function selectedModel(frame: Frame, mode: Mode): Promise<string> {
  const trigger = mode === 'chat'
    ? frame.getByRole('button', { name: /, Model Selector$/ })
    : frame.getByRole('button', { name: /^Model: / });
  const button = await unique(trigger.filter({ visible: true }), `${mode} model selector`);
  const label = await button.getAttribute('aria-label');
  const model = mode === 'chat' ? label?.replace(/, Model Selector$/, '') : parseCodeModelLabel(label ?? '').model;
  if (!model || model === 'Models unavailable') throw new Error('The active model is unavailable or cannot be verified.');
  return model;
}

async function menuItems(frame: Frame): Promise<{ locator: Locator; label: string; selected: boolean }[]> {
  const items = [];
  for (const locator of await frame.locator('[role="menuitem"]:visible').all()) {
    if (await locator.getAttribute('aria-haspopup') === 'menu') continue;
    const label = (await locator.innerText()).split('\n')[0]?.trim();
    if (label) items.push({ locator, label, selected: await locator.getAttribute('aria-checked') === 'true' });
  }
  return items;
}

async function chatModels(page: Page, frame: Frame, wanted?: string): Promise<ModelChoice[]> {
  const trigger = await unique(frame.getByRole('button', { name: /, Model Selector$/ }).filter({ visible: true }), 'Chat model selector');
  if (await frame.locator('[role="menu"]:visible').count()) throw new Error('A menu is already open; close it manually before listing or selecting models.');
  const choices: ModelChoice[] = [];
  try {
    await trigger.click();
    await frame.locator('[role="menu"]:visible').first().waitFor();
    for (const item of await menuItems(frame)) choices.push({ label: item.label, group: null, selected: item.selected });
    for (const group of ['gptSubMenuModelTrigger-Claude', 'gptSubMenuModelTrigger-OpenAI']) {
      const family = frame.locator(`[data-testid="${group}"][aria-haspopup="menu"]:visible`);
      if (!await family.count()) continue;
      await unique(family, `${group} submenu`);
      await family.click();
      await frame.waitForFunction(testid => document.querySelector(`[data-testid="${testid}"][aria-haspopup="menu"]`)?.getAttribute('aria-expanded') === 'true', group, { timeout: 5_000 });
      for (const item of await menuItems(frame)) {
        if (!choices.some(choice => choice.group === null && choice.label === item.label)) choices.push({ label: item.label, group, selected: item.selected });
      }
      await page.keyboard.press('Escape');
    }
    if (wanted !== undefined) {
      const choice = findExactModel(choices, wanted);
      if (choice.group) await frame.locator(`[data-testid="${choice.group}"][aria-haspopup="menu"]:visible`).click();
      const items = (await menuItems(frame)).filter(item => item.label === wanted);
      if (items.length !== 1) throw new Error('The selected model menu changed; no prompt sent.');
      await items[0]!.locator.click();
    }
  } finally {
    if (await frame.locator('[role="menu"]:visible').count()) await page.keyboard.press('Escape');
    if (await frame.locator('[role="menu"]:visible').count()) await page.keyboard.press('Escape');
  }
  if (wanted !== undefined) await frame.getByRole('button', { name: `${wanted}, Model Selector`, exact: true }).waitFor({ state: 'visible', timeout: 5_000 });
  if (wanted !== undefined && await selectedModel(frame, 'chat') !== wanted) throw new Error('Requested model was not selected; no prompt sent.');
  return choices;
}

async function codeModels(page: Page, frame: Frame, wanted?: string): Promise<ModelChoice[]> {
  const trigger = await unique(frame.getByRole('button', { name: /^Model: / }).filter({ visible: true }), 'Code model selector');
  const surface = frame.getByRole('group', { name: 'Model, effort, and context window', exact: true });
  if (await frame.locator('dialog[data-slot="popover-content"]:visible').count()) throw new Error('A Code popover is already open; close it manually before model discovery or selection.');
  const choices: ModelChoice[] = [];
  const families = [
    { trigger: 'Claude Anthropic', group: 'Claude models' },
    { trigger: 'GPT OpenAI', group: 'GPT models' },
  ];
  try {
    await trigger.click();
    await surface.waitFor({ state: 'visible', timeout: 5_000 });
    await surface.getByRole('button', { name: /^Change model: / }).click();
    const models = surface.getByRole('group', { name: 'Models', exact: true });
    for (const family of families) {
      const familyTrigger = models.getByRole('button', { name: family.trigger, exact: true });
      if (!await familyTrigger.count()) continue;
      await unique(familyTrigger, `${family.trigger} family`);
      await familyTrigger.click();
      const group = frame.getByRole('group', { name: family.group, exact: true });
      await group.waitFor({ state: 'visible', timeout: 5_000 });
      for (const item of await group.locator('button[data-model-row]').all()) {
        const label = (await item.innerText()).trim();
        if (label) choices.push({ label, group: family.group, selected: await item.getAttribute('aria-pressed') === 'true' });
      }
      await familyTrigger.click();
      await group.waitFor({ state: 'hidden', timeout: 5_000 });
    }
    if (wanted !== undefined) {
      const choice = findExactModel(choices, wanted);
      const family = families.find(item => item.group === choice.group)!;
      await models.getByRole('button', { name: family.trigger, exact: true }).click();
      const group = frame.getByRole('group', { name: family.group, exact: true });
      const leaf = await unique(group.getByRole('button', { name: wanted, exact: true }), 'exact Code model leaf');
      await leaf.click();
    }
  } finally {
    for (let depth = 0; depth < 3 && await frame.locator('dialog[data-slot="popover-content"]:visible').count(); depth++) await page.keyboard.press('Escape');
  }
  if (!choices.length) throw new Error('The Code model menu exposed no supported model leaves.');
  if (wanted !== undefined) {
    const escaped = wanted.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    await frame.getByRole('button', { name: new RegExp(`^Model: ${escaped}(?:, effort: .+)?$`) }).waitFor({ state: 'visible', timeout: 5_000 });
  }
  if (wanted !== undefined && await selectedModel(frame, 'code') !== wanted) throw new Error('Requested Code model was not selected; no prompt sent.');
  return choices;
}

async function codeBlocker(frame: Frame): Promise<CodeBlocker | null> {
  const approvals = await frame.getByRole('button').filter({ visible: true }).evaluateAll(buttons => buttons
    .map(button => button.getAttribute('aria-label') ?? (button as HTMLElement).innerText.trim())
    .filter(label => /^(?:approve|allow|grant permission)(?:\b|$)/i.test(label)));
  if (approvals.length) return { kind: 'permission', labels: approvals };
  const dialogs = frame.getByRole('dialog').or(frame.getByRole('alertdialog')).filter({ visible: true });
  if (await dialogs.count()) return { kind: 'dialog', labels: await dialogs.evaluateAll(elements => elements.map(element => element.getAttribute('aria-label') ?? element.querySelector('h1,h2,h3,[role="heading"]')?.textContent ?? 'Unnamed dialog')) };
  return null;
}

async function waitForCodeReady(frame: Frame): Promise<void> {
  const welcome = frame.getByRole('dialog').filter({ hasText: 'Welcome to Copilot Code' });
  if (await welcome.isVisible()) throw new Error((await codePrerequisite(frame))!);
  try {
    await frame.getByRole('button', { name: /^Model: (?!(?:Models unavailable|Loading models(?:…|\.{3})?)$).+/ }).waitFor({ state: 'visible', timeout: 20_000 });
  } catch (error) {
    throw new Error(`${await codePrerequisite(frame) ?? 'Code model selector is unavailable.'} ${error instanceof Error ? error.message : String(error)}`);
  }
  await selectedModel(frame, 'code');
}

async function readCode(frame: Frame, transitioning = false): Promise<CodeSnapshot> {
  const sessionId = codeSessionId(frame.url());
  const blocker = await codeBlocker(frame);
  const blockedState = blocker?.kind === 'permission' ? 'permission-blocked' : 'dialog-blocked';
  if (sessionId === null) {
    await editor(frame, 'code');
    return { sessionId, state: blocker ? blockedState : 'empty', blocker, turns: [] };
  }
  const sessionLocator = frame.getByRole('region', { name: 'Code session', exact: true });
  const feedLocator = sessionLocator.getByRole('feed', { name: 'Conversation messages', exact: true });
  if ((transitioning || blocker) && (!await sessionLocator.count() || !await feedLocator.count())) return { sessionId, state: blocker ? blockedState : 'incomplete', blocker, turns: [] };
  await unique(sessionLocator, 'Code session region');
  const feed = await unique(feedLocator, 'Code conversation feed');
  // Pair identities, pending users, completion controls, and blockers in one renderer task.
  const snapshot = await feed.evaluate(feed => {
    const visible = (element: Element) => !!element.getClientRects().length && getComputedStyle(element).visibility === 'visible';
    const ready = (button: HTMLButtonElement) => visible(button) && !button.matches(':disabled') && !button.closest('[aria-disabled="true"],[inert]');
    const roots: (Document | ShadowRoot)[] = [document];
    for (const root of roots) for (const element of root.querySelectorAll('*')) if (element.shadowRoot) roots.push(element.shadowRoot);
    const all = (selector: string) => roots.flatMap(root => [...root.querySelectorAll<HTMLElement>(selector)]).filter(visible);
    const approvals = all('button,[role="button"]').map(button => button.getAttribute('aria-label') ?? button.innerText.trim())
      .filter(label => /^(?:approve|allow|grant permission)(?:\b|$)/i.test(label));
    const dialogs = all('[role="dialog"],[role="alertdialog"],dialog');
    const blocker = approvals.length ? { kind: 'permission' as const, labels: approvals }
      : dialogs.length ? { kind: 'dialog' as const, labels: dialogs.map(element => element.getAttribute('aria-label') ?? element.querySelector('h1,h2,h3,[role="heading"]')?.textContent ?? 'Unnamed dialog') } : null;
    const users = new Map<string, HTMLElement[]>();
    const userIds: string[] = [];
    for (const user of feed.querySelectorAll<HTMLElement>('[data-persona="user"][data-message-id]')) {
      const id = user.getAttribute('data-message-id')!;
      userIds.push(id);
      const matches = users.get(id);
      if (matches) matches.push(user); else users.set(id, [user]);
    }
    const turns = [];
    for (const assistant of feed.querySelectorAll<HTMLElement>('[role="article"][data-message-role="assistant"]')) {
      const id = assistant.getAttribute('data-message-id');
      const rawIndex = assistant.getAttribute('aria-posinset');
      if (!id || rawIndex === null) continue;
      const user = users.get(id.replace(/:assistant$/, ':user'));
      const question = user?.length === 1 ? user[0]!.querySelector<HTMLElement>(':scope > div:first-child > div:first-child > div:first-child') : null;
      const bots = assistant.querySelectorAll<HTMLElement>('[role="article"][aria-label="Bot message"]');
      const bot = bots.length === 1 ? bots[0]! : null;
      const body = bot?.querySelector<HTMLElement>(':scope > div:first-child');
      const chains = assistant.querySelectorAll('[data-testid="simplified-chain-of-thought"]');
      const copy = bot?.querySelectorAll<HTMLButtonElement>('button[aria-label="Copy Response"]');
      const regenerate = bot?.querySelectorAll<HTMLButtonElement>('button[aria-label="Regenerate"]');
      turns.push({ id, rawIndex, question: question?.innerText ?? '', reply: body?.innerText ?? '',
        live: chains.length === 1 ? chains[0]!.getAttribute('data-live') : null,
        stepStatuses: [...assistant.querySelectorAll('[data-testid="simple-cot-row"]')].map(step => step.getAttribute('data-step-status')),
        sameMessage: !!question && bot?.getAttribute('data-message-id') === id && bot.getAttribute('data-persona') === 'bot',
        copyReady: copy?.length === 1 && ready(copy[0]!), regenerateReady: regenerate?.length === 1 && ready(regenerate[0]!),
      });
    }
    return { url: feed.ownerDocument.URL, userIds, turns, blocker };
  });
  if (codeSessionId(snapshot.url) !== sessionId) throw new Error('Code session changed while reading its transcript.');
  const { userIds } = snapshot;
  for (const id of userIds) if (parseCodeTurnId(id).role !== 'user') throw new Error('Unsupported Code user-message identity.');
  const turns: CodeTurn[] = snapshot.turns.map(turn => {
    const identity = parseCodeTurnId(turn.id);
    const index = Number(turn.rawIndex);
    if (identity.role !== 'assistant' || !/^\d+$/.test(turn.rawIndex) || !Number.isSafeInteger(index) || index < 1) throw new Error('Unsupported Code assistant-message identity.');
    return { id: turn.id, index, turnId: identity.turnId, userId: `${identity.turnId}:user`, question: turn.question, reply: turn.reply, live: turn.live, stepStatuses: turn.stepStatuses, complete: codeReplyComplete(turn) };
  });
  const pairedUsers = new Set(turns.map(turn => turn.userId));
  const pendingUser = userIds.some(id => !pairedUsers.has(id));
  const generating = pendingUser || turns.some(turn => turn.live === 'true');
  const currentBlocker = snapshot.blocker;
  return { sessionId, state: currentBlocker ? currentBlocker.kind === 'permission' ? 'permission-blocked' : 'dialog-blocked' : generating ? 'generating' : !userIds.length && !turns.length ? 'empty' : turns.length && turns.every(turn => turn.complete) ? 'complete' : 'incomplete', blocker: currentBlocker, turns };
}

export function completedCodeTurn(current: CodeSnapshot, known: ReadonlySet<string>, after: number, text: string): CodeTurn | undefined {
  if (current.blocker) throw new Error(`Code is ${current.state}: ${current.blocker.labels.join(', ')}. No permission was approved.`);
  let fresh: CodeTurn | undefined;
  for (const turn of current.turns) {
    if (known.has(turn.id) || turn.index <= after) continue;
    if (turn.question.length > 0 && turn.question !== text) throw new Error('An unrelated new Code turn appeared; concurrent interaction may have occurred.');
    if (fresh) throw new Error('More than one new Code turn appeared.');
    fresh = turn;
  }
  return current.state === 'complete' && current.sessionId !== null && fresh && fresh.question === text && fresh.complete ? fresh : undefined;
}

async function sendCode(page: Page, frame: Frame, request: Extract<Request, { operation: 'send' }>): Promise<unknown> {
  const expectedUrl = frame.url();
  await waitForCodeReady(frame);
  await assertNoDraft(frame);
  const initial = await readCode(frame);
  if (initial.blocker || !['empty', 'complete'].includes(initial.state)) throw new Error('Code is busy, incomplete, or awaiting interaction. Resolve it manually before sending; no permission is approved automatically.');
  if (request.model !== undefined) await codeModels(page, frame, request.model);
  const model = await selectedModel(frame, 'code');
  const before = await readCode(frame);
  if (before.sessionId !== initial.sessionId || before.blocker || !['empty', 'complete'].includes(before.state)) throw new Error('Code session changed before composing; no prompt sent.');
  const ids = new Set(before.turns.map(turn => turn.id));
  const lastIndex = Math.max(0, ...before.turns.map(turn => turn.index));
  const proof = await composerProof(frame, 'code', model, expectedUrl);
  const composer = await editor(frame, 'code');
  const composerHandle = await composer.elementHandle();
  if (!composerHandle) throw new Error('Code composer disappeared.');
  let sendHandle: ComposerHandle | null = null;
  let clicking = false;
  let receiptGuard: ReceiptGuard | undefined;
  try {
    await insertPrompt(frame, composerHandle, proof, request.text);
    const blocker = await codeBlocker(frame);
    if (blocker) throw new Error(`Code requires manual interaction: ${blocker.kind}: ${blocker.labels.join(', ')}`);
    const sendLocator = frame.locator('button[data-testid="send-button"]:enabled').filter({ visible: true });
    await sendLocator.waitFor({ state: 'visible', timeout: 5_000 });
    const send = await unique(sendLocator, 'Code Send message button');
    sendHandle = await send.elementHandle();
    if (!sendHandle) throw new Error('Code Send button disappeared; draft preserved.');
    receiptGuard = await watchReceipt(frame, expectedUrl, codeSessionId);
    await receiptGuard.check();
    receiptGuard.arm();
    clicking = true;
    const action = await composerAction(composerHandle, { kind: 'send', text: request.text, proof }, sendHandle, receiptGuard.interaction);
    if (!action.clicked) { clicking = false; throw new Error(action.error ?? 'Code final proof failed; no prompt sent.'); }
    receiptGuard.commit();
    const deadline = Date.now() + TIMEOUT;
    while (Date.now() < deadline) {
      await receiptGuard.check();
      const current = await readCode(frame, true);
      await receiptGuard.check();
      const completed = completedCodeTurn(current, ids, lastIndex, request.text);
      if (completed) return { operation: 'send', mode: 'code', model, sessionId: current.sessionId, turn: completed, evidence: ['session-route-id', 'new-paired-turn-id', 'new-feed-position', 'exact-user-prompt', 'assistant-and-bot-roles', 'data-live-false', 'completed-steps', 'enabled-copy-and-regenerate'] };
      await frame.waitForFunction(({ known, after }) => {
        const roots: (Document | ShadowRoot)[] = [document];
        for (const root of roots) for (const element of root.querySelectorAll('*')) if (element.shadowRoot) roots.push(element.shadowRoot);
        const all = (selector: string) => roots.flatMap(root => [...root.querySelectorAll(selector)]);
        if (all('[role="dialog"],[role="alertdialog"]').some(element => element.getClientRects().length) || all('button').some(element => element.getClientRects().length && /^(?:approve|allow|grant permission)(?:\b|$)/i.test(element.getAttribute('aria-label') ?? (element as HTMLElement).innerText.trim()))) return true;
        const feeds = all('[role="feed"][aria-label="Conversation messages"]').filter(element => element.getClientRects().length && getComputedStyle(element).visibility === 'visible');
        if (feeds.length !== 1) return true;
        const assistants = [...feeds[0]!.querySelectorAll('[role="article"][data-message-role="assistant"][data-message-id]')];
        const fresh = assistants.filter(assistant => !known.includes(assistant.getAttribute('data-message-id')!) && Number(assistant.getAttribute('aria-posinset')) > after);
        if (fresh.length > 1) return true;
        const paired = new Set(assistants.map(assistant => assistant.getAttribute('data-message-id')!.replace(/:assistant$/, ':user')));
        if ([...feeds[0]!.querySelectorAll('[data-persona="user"][data-message-id]')].some(user => !paired.has(user.getAttribute('data-message-id')!))) return false;
        return fresh.some(assistant => {
          const id = assistant.getAttribute('data-message-id')!;
          const copy = assistant.querySelector('[data-persona="bot"] button[aria-label="Copy Response"]');
          const regenerate = assistant.querySelector('[data-persona="bot"] button[aria-label="Regenerate"]');
          return !known.includes(id) && Number(assistant.getAttribute('aria-posinset')) > after && assistant.querySelector('[data-testid="simplified-chain-of-thought"]')?.getAttribute('data-live') === 'false' && [...assistant.querySelectorAll('[data-testid="simple-cot-row"]')].every(step => step.getAttribute('data-step-status') === 'done') && !!copy?.getClientRects().length && !copy.hasAttribute('disabled') && !!regenerate?.getClientRects().length && !regenerate.hasAttribute('disabled');
        });
      }, { known: [...ids], after: lastIndex }, { timeout: Math.max(1, deadline - Date.now()), polling: 250 });
    }
    throw new Error('Timed out waiting for a newly identified completed Code response.');
  } catch (error) {
    if (clicking) throw new Error(`UNCERTAIN_SEND: the Code Send action may have taken effect. Never resend automatically; read the same session and reconcile manually. ${error instanceof Error ? error.message : String(error)}`);
    throw error;
  } finally {
    await receiptGuard?.dispose();
    await composerHandle.dispose().catch(() => {});
    await sendHandle?.dispose().catch(() => {});
  }
}

async function chatTurns(frame: Frame): Promise<ChatTurn[]> {
  const turns: ChatTurn[] = [];
  for (const turn of await frame.locator(TURN).all()) {
    const reply = turn.locator(REPLY);
    if (await reply.count() !== 1) continue;
    const id = await reply.getAttribute('id');
    if (!id) continue;
    const rawIndex = await turn.getAttribute('data-message-index');
    const index = Number(rawIndex);
    if (!id.startsWith('chatMessageResponse-') || rawIndex === null || !/^\d+$/.test(rawIndex) || !Number.isSafeInteger(index)) throw new Error('Unsupported Chat turn identity.');
    const question = turn.getByTestId('chatQuestion').getByTestId('chatOutput');
    const text = reply.getByTestId('lastChatMessage');
    const copy = reply.getByTestId('CopyButtonTestId');
    const feedback = reply.getByTestId('FeedbackContainerTestId');
    turns.push({
      id, index,
      question: await question.count() === 1 ? await question.innerText() : '',
      reply: await text.count() === 1 ? await text.innerText() : '',
      complete: await reply.getByRole('article').count() === 1 && await copy.count() === 1 && await copy.isVisible() && await copy.isEnabled() && await feedback.count() === 1,
    });
  }
  return turns;
}

async function sendChat(page: Page, frame: Frame, request: Extract<Request, { operation: 'send' }>): Promise<unknown> {
  const expectedUrl = frame.url();
  await assertNoDraft(frame);
  if (request.model !== undefined) await chatModels(page, frame, request.model);
  const model = await selectedModel(frame, 'chat');
  const before = await chatTurns(frame);
  if (before.some(turn => !turn.complete)) throw new Error('Chat has an incomplete response; wait for it manually before sending.');
  const ids = new Set(before.map(turn => turn.id));
  const lastIndex = Math.max(-1, ...before.map(turn => turn.index));
  const proof = await composerProof(frame, 'chat', model, expectedUrl);
  const composer = await editor(frame, 'chat');
  const composerHandle = await composer.elementHandle();
  if (!composerHandle) throw new Error('Chat composer disappeared.');
  let sendHandle: ComposerHandle | null = null;
  let clicking = false;
  let receiptGuard: ReceiptGuard | undefined;
  try {
    await insertPrompt(frame, composerHandle, proof, request.text);
    const sendLocator = frame.getByRole('button', { name: 'Send', exact: true, disabled: false }).filter({ visible: true });
    await sendLocator.waitFor({ state: 'visible', timeout: 5_000 });
    const send = await unique(sendLocator, 'Chat Send button');
    sendHandle = await send.elementHandle();
    if (!sendHandle) throw new Error('Chat Send button disappeared; draft preserved.');
    receiptGuard = await watchReceipt(frame, expectedUrl, chatSessionId);
    await receiptGuard.check();
    receiptGuard.arm();
    clicking = true;
    const action = await composerAction(composerHandle, { kind: 'send', text: request.text, proof }, sendHandle, receiptGuard.interaction);
    if (!action.clicked) { clicking = false; throw new Error(action.error ?? 'Chat final proof failed; no prompt sent.'); }
    receiptGuard.commit();
    const deadline = Date.now() + TIMEOUT;
    while (Date.now() < deadline) {
      await receiptGuard.check();
      const fresh = (await chatTurns(frame)).filter(turn => !ids.has(turn.id) && turn.index > lastIndex && matchesChatPrompt(turn.question, request.text));
      await receiptGuard.check();
      if (fresh.length > 1) throw new Error('More than one new matching Chat turn appeared.');
      if (fresh.length === 1 && fresh[0]!.complete && fresh[0]!.reply.trim()) {
        return { operation: 'send', mode: 'chat', model, turn: fresh[0], evidence: ['new-response-id', 'new-turn-index', 'exact-user-prompt', 'assistant-article', 'enabled-copy-response', 'feedback-controls'] };
      }
      await frame.waitForFunction(({ selector, known, after, prompt }) => [...document.querySelectorAll(selector)].some(turn => {
        const reply = turn.querySelector('[data-testid="copilot-message-div"]');
        const copy = reply?.querySelector('[data-testid="CopyButtonTestId"]');
        return !!reply?.id && !known.includes(reply.id) && Number(turn.getAttribute('data-message-index')) > after && (turn.querySelector('[data-testid="chatQuestion"] [data-testid="chatOutput"]') as HTMLElement | null)?.innerText === `${prompt}\n` && !!copy?.getClientRects().length && !copy.hasAttribute('disabled') && !!reply.querySelector('[data-testid="FeedbackContainerTestId"]');
      }), { selector: TURN, known: [...ids], after: lastIndex, prompt: request.text }, { timeout: Math.max(1, deadline - Date.now()), polling: 250 });
    }
    throw new Error('Timed out waiting for a newly identified completed assistant reply.');
  } catch (error) {
    if (clicking) throw new Error(`UNCERTAIN_SEND: the Send action may have taken effect. Never resend automatically; inspect/read the conversation manually. ${error instanceof Error ? error.message : String(error)}`);
    throw error;
  } finally {
    await receiptGuard?.dispose();
    await composerHandle.dispose().catch(() => {});
    await sendHandle?.dispose().catch(() => {});
  }
}

export async function execute(page: Page, value: unknown): Promise<unknown> {
  const request = parseRequest(value);
  const frame = uiFrame(page);
  const current = await activeMode(frame);
  if (request.operation === 'inspect') {
    const prerequisite = current === 'code' ? await codePrerequisite(frame) : null;
    const input = frame.locator(current === 'chat' ? CHAT_EDITOR : CODE_EDITOR).filter({ visible: true });
    return { operation: 'inspect', mode: current, host: HOST, path: new URL(frame.url()).pathname, model: prerequisite ? null : await selectedModel(frame, current), draftPresent: await input.count() === 1 ? !!(await composerText(input)).length : null, prerequisite };
  }
  if (request.operation === 'read') {
    if (current !== request.mode) throw new Error('Read requires the requested mode to be active; it does not switch conversations.');
    if (current === 'chat') return { operation: 'read', mode: current, turns: await chatTurns(frame) };
    const prerequisite = await codePrerequisite(frame);
    if (prerequisite) throw new Error(prerequisite);
    return { operation: 'read', mode: 'code', ...await readCode(frame) };
  }
  await selectMode(frame, request.mode);
  if (request.mode === 'code') {
    if (request.operation === 'models') {
      await waitForCodeReady(frame);
      const models = await codeModels(page, frame);
      return { operation: 'models', mode: 'code', selected: await selectedModel(frame, 'code'), models };
    }
    return sendCode(page, frame, request);
  }
  await frame.locator(CHAT_EDITOR).filter({ visible: true }).waitFor({ state: 'visible', timeout: 20_000 });
  await frame.getByRole('button', { name: /, Model Selector$/ }).filter({ visible: true }).waitFor({ state: 'visible', timeout: 20_000 });
  if (request.operation === 'models') {
    const models = await chatModels(page, frame);
    return { operation: 'models', mode: 'chat', selected: await selectedModel(frame, 'chat'), models };
  }
  return sendChat(page, frame, request);
}

if (import.meta.main) await runCli('copilot', execute);
