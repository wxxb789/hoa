import { describe, expect, test } from 'bun:test';
import { chatSessionId, codeReplyComplete, codeSessionId, completedCodeTurn, findExactModel, matchesChatPrompt, parseCodeModelLabel, parseCodeTurnId, parseRequest } from './copilot.ts';
import { receiptBoundary } from './receipt-guard.ts';

describe('Copilot request boundary', () => {
  test('keeps exact prompts and model labels', () => {
    expect(parseRequest({ operation: 'send', mode: 'chat', model: 'GPT-6.1 Sol', text: 'line one\nline two' })).toEqual({ operation: 'send', mode: 'chat', model: 'GPT-6.1 Sol', text: 'line one\nline two' });
    expect(parseRequest({ operation: 'send', mode: 'code', text: 'Explain without executing commands.' })).toEqual({ operation: 'send', mode: 'code', text: 'Explain without executing commands.' });
  });

  test('supports each read-only request shape', () => {
    expect(parseRequest({ operation: 'inspect' })).toEqual({ operation: 'inspect' });
    for (const operation of ['models', 'read'] as const) {
      for (const mode of ['chat', 'code'] as const) expect(parseRequest({ operation, mode })).toEqual({ operation, mode });
    }
  });

  test('selects only one exact model leaf, never an alias or ambiguous label', () => {
    const choices = [
      { label: 'Auto', group: null, selected: true },
      { label: 'GPT-6', group: 'gptSubMenuModelTrigger-OpenAI', selected: false },
      { label: 'GPT-6.1 Sol', group: 'gptSubMenuModelTrigger-OpenAI', selected: false },
    ];
    expect(findExactModel(choices, 'GPT-6.1 Sol').label).toBe('GPT-6.1 Sol');
    for (const label of ['auto', 'GPT', 'GPT-6.1', ' Auto ']) expect(() => findExactModel(choices, label)).toThrow();
    expect(() => findExactModel([...choices, choices[0]!], 'Auto')).toThrow();
  });

  test('matches only the renderer-owned trailing LF without trimming user text', () => {
    expect(matchesChatPrompt('hello\n', 'hello')).toBe(true);
    expect(matchesChatPrompt(' first\nsecond \n\n', ' first\nsecond \n')).toBe(true);
    expect(matchesChatPrompt('hello', 'hello')).toBe(false);
    expect(matchesChatPrompt('hello\n\n', 'hello')).toBe(false);
    expect(matchesChatPrompt(' hello\n', 'hello')).toBe(false);
    expect(matchesChatPrompt('hello \n', 'hello')).toBe(false);
    expect(matchesChatPrompt('hello\n', 'hello\n')).toBe(false);
  });

  test('separates the exact Code model from its independent effort setting', () => {
    expect(parseCodeModelLabel('Model: Claude Opus 5.5, effort: Medium')).toEqual({ model: 'Claude Opus 5.5', effort: 'Medium' });
    expect(parseCodeModelLabel('Model: GPT-6.1 Sol')).toEqual({ model: 'GPT-6.1 Sol', effort: null });
    expect(() => parseCodeModelLabel('Model: Models unavailable')).toThrow();
    expect(() => parseCodeModelLabel('Model: Loading models…')).toThrow();
    expect(() => parseCodeModelLabel('Claude Opus 5.5')).toThrow();
  });

  test('accepts only the native Code session route and role-bearing turn IDs', () => {
    const uuid = '11111111-2222-4333-8444-555555555555';
    const root = 'https://cr.m365copilotapp.svc.cloud.microsoft/hwav2/code';
    expect(codeSessionId(`${root}#/sessions`)).toBeNull();
    expect(codeSessionId(`${root}#/sessions/${uuid}`)).toBe(uuid);
    expect(parseCodeTurnId(`turn-${uuid}:user`)).toEqual({ turnId: `turn-${uuid}`, role: 'user' });
    expect(parseCodeTurnId(`turn-${uuid}:assistant`)).toEqual({ turnId: `turn-${uuid}`, role: 'assistant' });
    expect(parseCodeTurnId(`${uuid}:user`)).toEqual({ turnId: uuid, role: 'user' });
    expect(parseCodeTurnId(`${uuid}:assistant`)).toEqual({ turnId: uuid, role: 'assistant' });
    expect(() => codeSessionId(`https://example.com/hwav2/code#/sessions/${uuid}`)).toThrow();
    expect(() => codeSessionId(`${root}#/sessions/not-a-session-id`)).toThrow();
    for (const id of [`turn-${uuid}`, `turn-${uuid}:system`, 'old-reply', 'turn-invalid:assistant']) expect(() => parseCodeTurnId(id)).toThrow();
  });

  test('never calls streaming, pending, unrelated, or actionless Code text complete', () => {
    const done = { live: 'false', stepStatuses: ['done'], sameMessage: true, copyReady: true, regenerateReady: true, reply: 'Rendered assistant answer' };
    expect(codeReplyComplete(done)).toBe(true);
    expect(codeReplyComplete({ ...done, live: 'true' })).toBe(false);
    expect(codeReplyComplete({ ...done, live: null })).toBe(false);
    expect(codeReplyComplete({ ...done, stepStatuses: ['running'] })).toBe(false);
    expect(codeReplyComplete({ ...done, stepStatuses: [null] })).toBe(false);
    expect(codeReplyComplete({ ...done, sameMessage: false })).toBe(false);
    expect(codeReplyComplete({ ...done, copyReady: false })).toBe(false);
    expect(codeReplyComplete({ ...done, regenerateReady: false })).toBe(false);
    expect(codeReplyComplete({ ...done, reply: ' \n ' })).toBe(false);
  });

  test.each([
    null,
    [],
    'send',
    {},
    { operation: 'delete' },
    { operation: 'inspect', mode: 'chat' },
    { operation: 'read' },
    { operation: 'models', mode: 'cowork' },
    { operation: 'read', mode: 'chat', text: 'not allowed' },
    { operation: 'send', mode: 'chat', text: '' },
    { operation: 'send', mode: 'chat', text: ' \n ' },
    { operation: 'send', mode: 'chat', text: 'a\0b' },
    { operation: 'send', mode: 'chat', text: 42 },
    { operation: 'send', mode: 'chat', text: 'x', model: ' Auto ' },
    { operation: 'send', mode: 'chat', text: 'x', model: '' },
    { operation: 'send', mode: 'chat', text: 'x', model: null },
    { operation: 'send', mode: 'code', text: 'x', approveTools: true },
  ].map(input => [input]))('rejects invalid input before UI interaction: %j', input => {
    expect(() => parseRequest(input)).toThrow();
  });
});

describe('Copilot receipt conversation isolation', () => {
  test('pins the first post-Send session before a later polling snapshot', () => {
    const guard = receiptBoundary(null);
    guard.arm();
    guard.observe('new-session');
    guard.observe('historical-session');
    guard.commit();
    expect(() => guard.check()).toThrow('Conversation changed');
  });

  test('allows only the verified empty-to-created transition', () => {
    const guard = receiptBoundary(null);
    guard.arm();
    guard.observe('new-session');
    guard.commit();
    guard.observe('new-session');
    guard.check();
    guard.observe(null);
    expect(() => guard.check()).toThrow('Conversation changed');
  });

  test('rejects navigation before dispatch and does not recover by returning', () => {
    const guard = receiptBoundary(null);
    guard.observe('existing-session');
    guard.arm();
    guard.commit();
    guard.observe(null);
    expect(() => guard.check()).toThrow('Conversation changed');
  });

  test('rejects replacing an existing session even if its prompt matches', () => {
    const guard = receiptBoundary('original');
    guard.arm();
    guard.commit();
    guard.observe('other');
    guard.observe('original');
    expect(() => guard.check()).toThrow('Conversation changed');
  });

  test('parses only the observed Chat conversation routes', () => {
    const root = 'https://cr.m365copilotapp.svc.cloud.microsoft/hwav2/chat';
    const id = '11111111-2222-4333-8444-555555555555';
    expect(chatSessionId(root)).toBeNull();
    expect(chatSessionId(`${root}/conversation/${id}?locale=en-US`)).toBe(id);
    for (const url of [`${root}/conversation/not-an-id`, `${root}#other`, 'https://example.com/hwav2/chat', root.replace('/chat', '/code')]) {
      expect(() => chatSessionId(url)).toThrow();
    }
  });
});

describe('Code send receipt state', () => {
  const turn = { id: 'turn-first:assistant', turnId: 'turn-first', userId: 'turn-first:user', index: 2, question: 'Continue.', reply: 'Completed answer', live: 'false', stepStatuses: [], complete: true };
  const known = new Set<string>();

  test('pending user prevents early Code success even when the first reply is complete', () => {
    const snapshot = { sessionId: 'session', state: 'generating' as const, blocker: null, turns: [turn] };
    expect(completedCodeTurn(snapshot, known, 0, 'Continue.')).toBeUndefined();
  });

  test('a second fresh assistant is uncertain instead of selecting the first answer', () => {
    const snapshot = { sessionId: 'session', state: 'complete' as const, blocker: null, turns: [turn, { ...turn, id: 'second:assistant', turnId: 'second', userId: 'second:user', index: 4 }] };
    expect(() => completedCodeTurn(snapshot, known, 0, 'Continue.')).toThrow('More than one new Code turn');
  });

  test('an idle no-step answer can complete without inventing tool execution', () => {
    const snapshot = { sessionId: 'session', state: 'complete' as const, blocker: null, turns: [turn] };
    expect(completedCodeTurn(snapshot, known, 0, 'Continue.')).toMatchObject({ id: turn.id, reply: turn.reply });
    expect(completedCodeTurn(snapshot, new Set([turn.id]), 0, 'Continue.')).toBeUndefined();
  });
});
