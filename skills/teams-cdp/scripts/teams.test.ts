import { describe, expect, test } from 'bun:test';
import type { Frame, Page } from 'playwright-core';
import { exactRecipientIndex, execute, parseRequest, type GroupTarget, type TeamsRequest } from './teams.ts';

describe('Teams request boundary', () => {
  test('native window creation is explicit and accepts no navigation or send fields', () => {
    expect(parseRequest({ operation: 'open-window' })).toEqual({ operation: 'open-window' });
    expect(() => parseRequest({ operation: 'open-window', query: 'Taylor' })).toThrow('exactly');
    expect(() => parseRequest({ operation: 'open-window', text: 'Hello' })).toThrow('exactly');
  });

  test('find accepts either explicit discovery domain', () => {
    expect(parseRequest({ operation: 'find', kind: 'person', query: '  Taylor  ' })).toEqual({ operation: 'find', kind: 'person', query: 'Taylor' });
    expect(parseRequest({ operation: 'find', kind: 'group', query: 'Planning' })).toEqual({ operation: 'find', kind: 'group', query: 'Planning' });
  });

  test('person send requires an email and preserves multiline content exactly', () => {
    const request = { operation: 'send', target: { kind: 'person', email: 'taylor@example.com' }, text: ' first line\n\n第二行\r\nlast line ' } satisfies TeamsRequest;
    expect(parseRequest(request)).toEqual(request);
    expect(() => parseRequest({ ...request, target: { kind: 'person', email: 'Taylor' } })).toThrow('explicit email');
  });

  test('group send consumes an exact discovered identifier and name', () => {
    const request = { operation: 'send', target: { kind: 'group', id: '19:0123456789abcdef0123456789abcdef@thread.v2', name: 'Planning' }, text: 'Agenda\nNext item' } satisfies TeamsRequest;
    expect(parseRequest(request)).toEqual(request);
    expect(() => parseRequest({ ...request, target: { kind: 'group', name: 'Planning' } })).toThrow('exactly');
    expect(() => parseRequest({ ...request, target: { ...request.target, id: 'Planning' } })).toThrow('group-chat id');
    expect(() => parseRequest({ ...request, target: { ...request.target, id: '19:meeting_example@thread.v2' } })).toThrow('group-chat id');
    expect(() => parseRequest({ ...request, target: { ...request.target, name: ' Planning ' } })).toThrow('exact name');
  });

  test.each([
    null,
    [],
    { operation: 'delete', kind: 'person', query: 'Taylor' },
    { operation: 'find', kind: 'channel', query: 'Planning' },
    { operation: 'find', kind: 'group', query: ' ' },
    { operation: 'find', kind: 'person', query: 'Taylor', send: true },
    { operation: 'send', target: { kind: 'person', email: 'Taylor <taylor@example.com>' }, text: 'Hello' },
    { operation: 'send', target: { kind: 'person', email: 'taylor@example.com', name: 'Taylor' }, text: 'Hello' },
    { operation: 'send', target: { kind: 'person', email: 'taylor@example.com' }, text: '' },
    { operation: 'send', target: { kind: 'person', email: 'taylor@example.com' }, text: '\0' },
  ].map(request => [request]))('rejects invalid requests before UI access: %j', request => {
    expect(() => parseRequest(request)).toThrow();
  });
});

describe('Teams exact recipient selection', () => {
  test('person identity is email, never the first matching display name', () => {
    const candidates = [
      { kind: 'person' as const, id: 'one', name: 'Taylor', email: 'other@example.com' },
      { kind: 'person' as const, id: 'two', name: 'Taylor', email: 'taylor@example.com' },
    ];
    expect(exactRecipientIndex(candidates, { kind: 'person', email: 'TAYLOR@example.com' })).toBe(1);
    expect(() => exactRecipientIndex(candidates, { kind: 'person', email: 'missing@example.com' })).toThrow('0 results');
    expect(() => exactRecipientIndex([...candidates, candidates[1]!], { kind: 'person', email: 'taylor@example.com' })).toThrow('2 results');
  });

  test('same-name groups require the exact ID and an unchanged exact name', () => {
    const candidates: GroupTarget[] = [
      { kind: 'group', id: '19:1111@thread.v2', name: 'Planning' },
      { kind: 'group', id: '19:2222@thread.v2', name: 'Planning' },
    ];
    expect(exactRecipientIndex(candidates, candidates[1]!)).toBe(1);
    expect(() => exactRecipientIndex(candidates, { ...candidates[1]!, name: 'planning' })).toThrow('0 results');
    expect(() => exactRecipientIndex(candidates, { ...candidates[1]!, id: '19:3333@thread.v2' })).toThrow('0 results');
    expect(() => exactRecipientIndex([...candidates, candidates[1]!], candidates[1]!)).toThrow('2 results');
    expect(() => exactRecipientIndex(candidates, { kind: 'person', email: 'Planning@example.com' })).toThrow('0 results');
  });
});


describe('Teams concrete-composer dispatch and receipt safety', () => {
  const group: GroupTarget = { kind: 'group', id: '19:0123456789abcdef0123456789abcdef@thread.v2', name: 'Planning' };

  function sendFixture(mode: 'valid' | 'switched' | 'detached' | 'text-changed' | 'dialog-open' | 'new-draft' | 'historical' | 'below-highwater' | 'wrapped', text = 'Hello', renderedText = text) {
    let clicks = 0;
    const editorId = 'new-message-fixture';
    const identity = `compose-editor:${JSON.stringify([editorId, group.id])}`;
    let metadata = JSON.stringify({ observed: { names: ['chat-input', identity] } });
    const editor = {
      id: editorId, isConnected: true, children: [{ tagName: 'P', innerText: '' }], innerText: '',
      textContent: '', focus: () => undefined,
      getAttribute: (name: string) => name === 'data-tabster' ? metadata : name === 'id' ? editorId : null,
      closest: (): unknown => footer,
      getBoundingClientRect: () => ({ width: 100, height: 40 }),
    };
    class FixtureButton {
      isConnected = true;
      disabled = false;
      getAttribute() { return null; }
      getBoundingClientRect() { return { width: 40, height: 20 }; }
      click() { clicks++; }
    }
    const button = new FixtureButton();
    const footer = { isConnected: true, contains: (node: unknown) => node === editor || node === button };
    const observedAt = Date.now();
    const oldId = String(observedAt - 60_000);
    const candidateId = mode === 'below-highwater' ? String(observedAt - 120_000) : mode === 'historical' ? oldId : String(observedAt + 1);
    const row = { getAttribute: () => candidateId };
    const nodes: Record<string, unknown> = {
      [editorId]: editor,
      [`timestamp-${candidateId}`]: { getAttribute: () => new Date(mode === 'historical' ? observedAt - 60_000 : Date.now()).toISOString() },
      [`content-${candidateId}`]: {
        children: [{ tagName: 'P', innerText: 'Hello' }], innerText: 'Hello',
        querySelector: () => mode === 'wrapped' ? {
          children: renderedText.split('\n').map(line => ({ tagName: 'P', innerText: line === '' ? '\u00a0' : line })),
          innerText: renderedText,
        } : null,
      },
      [`read-status-icon-${candidateId}`]: { getAttribute: (name: string) => name === 'role' ? 'img' : 'Sent' },
    };
    function inDocument<T>(fn: () => T): T {
      const values = {
        document: {
          querySelectorAll: (selector: string) => selector.includes('ckeditor') ? [editor]
            : selector.includes('chat-pane-message') ? [row]
            : mode === 'dialog-open' ? [{ getClientRects: () => [{}] }] : [],
          getElementById: (id: string) => nodes[id] ?? null,
        },
        HTMLButtonElement: FixtureButton,
        getComputedStyle: () => ({ visibility: 'visible' }),
      };
      const saved = new Map(Object.keys(values).map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
      try {
        for (const [key, value] of Object.entries(values)) Object.defineProperty(globalThis, key, { configurable: true, value });
        return fn();
      } finally {
        for (const [key, descriptor] of saved) {
          if (descriptor) Object.defineProperty(globalThis, key, descriptor);
          else Reflect.deleteProperty(globalThis, key);
        }
      }
    }
    const buttonHandle = {
      isVisible: async () => true,
      isEnabled: async () => true,
      dispose: async () => undefined,
      evaluate: async (fn: (...args: unknown[]) => unknown, args: Record<string, unknown>) => {
        if (mode === 'switched') metadata = JSON.stringify({ observed: { names: [`compose-editor:${JSON.stringify([editorId, '19:another@thread.v2'])}`] } });
        if (mode === 'detached') button.isConnected = false;
        if (mode === 'text-changed') editor.children[0]!.innerText = 'User draft';
        return inDocument(() => fn(button, { ...args, editor, footer }));
      },
    };
    const footerHandle = { $$: async () => [buttonHandle] };
    const editorHandle = {
      evaluateHandle: async () => ({ asElement: () => footerHandle, dispose: async () => undefined }),
      press: async () => {
        editor.children.push({ tagName: 'P', innerText: '' });
        editor.innerText += '\n';
        editor.textContent += '\n';
      },
      evaluate: async (fn: (...args: unknown[]) => unknown, args?: unknown) => {
        if (mode === 'new-draft' && (args as { requireEmpty?: boolean } | undefined)?.requireEmpty) {
          editor.textContent = editor.innerText = editor.children[0]!.innerText = 'Human draft';
        }
        return inDocument(() => fn(editor, args));
      },
      dispose: async () => undefined,
    };
    type FixtureLocator = {
      count: () => Promise<number>; all: () => Promise<never[]>;
      click: () => Promise<void>; fill: () => Promise<void>; press: () => Promise<void>; waitFor: () => Promise<void>;
      getAttribute: (name: string) => Promise<string | null>;
      nth: () => FixtureLocator; first: () => FixtureLocator;
      evaluate: () => Promise<string>; elementHandle: () => Promise<typeof editorHandle>;
      evaluateAll: (fn: (...args: unknown[]) => unknown) => Promise<unknown>;
    };
    const locator = (selector: string): FixtureLocator => ({
      count: async () => 1,
      all: async () => [],
      click: async () => {}, fill: async () => {}, press: async () => {}, waitFor: async () => {},
      getAttribute: async (name: string) => name === 'aria-selected' ? 'true' : editor.getAttribute(name),
      nth: () => locator(selector), first: () => locator(selector),
      evaluate: async () => group.name,
      elementHandle: async () => editorHandle,
      evaluateAll: async (fn: (...args: unknown[]) => unknown) => fn([{ getAttribute: () => mode === 'below-highwater' ? oldId : '1000' }]),
    });
    const frame = {
      url: () => 'https://teams.microsoft.com/v2/',
      locator, getByRole: () => locator('button'),
      page: () => ({ context: () => ({ newCDPSession: async () => ({
        send: async (method: string, value: { text: string }) => {
          if (method !== 'Input.insertText') throw new Error('Unexpected input operation');
          editor.children.at(-1)!.innerText += value.text;
          editor.innerText += value.text;
          editor.textContent += value.text;
        },
        detach: async () => undefined,
      }) }) }),
      waitForFunction: async (fn: (...args: unknown[]) => unknown, args: unknown) => {
        const result = inDocument(() => fn(args));
        if (!result) throw new Error('receipt not established');
        return { jsonValue: async () => result };
      },
    } as unknown as Frame;
    return { page: { frames: () => [frame] } as unknown as Page, clicks: () => clicks, draft: () => editor.textContent, candidateId };
  }

  test.each(['switched', 'detached', 'text-changed', 'dialog-open'] as const)('does not click when the concrete %s composer proof changes', async mode => {
    const fixture = sendFixture(mode);
    await expect(execute(fixture.page, { operation: 'send', target: group, text: 'Hello' })).rejects.toThrow();
    expect(fixture.clicks()).toBe(0);
  });

  test.each(['historical', 'below-highwater'] as const)('a newly rendered %s same-text Sent row is not a fresh receipt', async mode => {
    const fixture = sendFixture(mode);
    await expect(execute(fixture.page, { operation: 'send', target: group, text: 'Hello' })).rejects.toThrow();
    expect(fixture.clicks()).toBe(1);
  });

  test('preserves a human draft appearing just before trusted text insertion', async () => {
    const fixture = sendFixture('new-draft');
    await expect(execute(fixture.page, { operation: 'send', target: group, text: 'Hello' })).rejects.toThrow();
    expect(fixture.clicks()).toBe(0);
    expect(fixture.draft()).toBe('Human draft');
  });

  test('only an exact concrete composer plus a fresh ordered outgoing Sent row succeeds', async () => {
    const fixture = sendFixture('valid');
    expect(await execute(fixture.page, { operation: 'send', target: group, text: 'Hello' })).toMatchObject({
      conversationId: group.id, receipt: { messageId: fixture.candidateId, status: 'Sent' },
    });
    expect(fixture.clicks()).toBe(1);
  });

  test.each(['Hello\n\nWorld', 'Hello\n\u00a0\nWorld'])('accepts a wrapped Sent receipt preserving %j', async text => {
    const fixture = sendFixture('wrapped', text);
    expect(await execute(fixture.page, { operation: 'send', target: group, text })).toMatchObject({
      receipt: { messageId: fixture.candidateId, status: 'Sent' },
    });
    expect(fixture.clicks()).toBe(1);
  });

  test('does not equate an authored space with an empty paragraph filler', async () => {
    const text = 'Hello\n \nWorld';
    const fixture = sendFixture('wrapped', text, 'Hello\n\nWorld');
    await expect(execute(fixture.page, { operation: 'send', target: group, text })).rejects.toThrow('Uncertain send outcome');
    expect(fixture.clicks()).toBe(1);
  });
});
