import { describe, expect, mock, test } from 'bun:test';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { PassThrough } from 'node:stream';
import type { Browser, Page } from 'playwright-core';
import { appUrl, browserLockName, executeSession, localEndpoint, normalizeTargetInfo } from './cdp.ts';

describe('CDP connection boundaries', () => {
  test('accepts loopback origins and canonicalizes localhost', () => {
    expect(localEndpoint('http://localhost:9222').href).toBe('http://127.0.0.1:9222/');
    expect(localEndpoint('http://[::1]:9223').hostname).toBe('[::1]');
    expect(localEndpoint('ws://localhost:63990/devtools/browser/browser-id').hostname).toBe('127.0.0.1');
  });

  test('rejects remote endpoints, credentials, and URL suffixes', () => {
    for (const value of ['https://127.0.0.1:9222', 'http://example.com:9222',
      'http://127.0.0.1.example.com', 'http://user:password@localhost:9222',
      'http://localhost:9222/json/list', 'http://localhost:9222/?token=x',
      'http://localhost:9222/#target', 'ws://example.com:63990/devtools/browser/browser-id',
      'ws://localhost:63990/devtools/page/page-id']) {
      expect(() => localEndpoint(value)).toThrow();
    }
  });

  test('never selects a lookalike or another application as a message destination', () => {
    expect(appUrl('teams', 'https://teams.microsoft.com/v2/')).toBe(true);
    expect(appUrl('copilot', 'https://cr.m365copilotapp.svc.cloud.microsoft/hwav2/chat')).toBe(true);
    expect(appUrl('teams', 'https://teams.microsoft.com.attacker.test/')).toBe(false);
    expect(appUrl('teams', 'https://copilot.microsoft.com/')).toBe(false);
    expect(appUrl('teams', 'http://teams.microsoft.com/v2/')).toBe(false);
    expect(appUrl('copilot', 'edge://olympia.top-chrome/')).toBe(false);
  });

  test('exposes Copilot webviews without rewriting runtime payloads or unrelated targets', () => {
    const targetInfo = { type: 'webview', targetId: 'live-target', url: 'https://cr.m365copilotapp.svc.cloud.microsoft/hwav2/chat' };
    const event = JSON.parse(normalizeTargetInfo(JSON.stringify({ method: 'Target.attachedToTarget', params: { targetInfo, sessionId: 'session' } })));
    expect(event.params.targetInfo).toEqual({ ...targetInfo, type: 'page' });
    expect(event.params.sessionId).toBe('session');
    const unrelated = { result: { value: { type: 'webview' }, targetInfos: [{ ...targetInfo, url: 'https://example.com' }] } };
    expect(JSON.parse(normalizeTargetInfo(JSON.stringify(unrelated)))).toEqual(unrelated);
  });

  test('preserves application data named targetInfo or targetInfos', () => {
    for (const value of [
      { targetInfo: 'note', targetInfos: null },
      { targetInfo: { type: 'webview', url: 'https://cr.m365copilotapp.svc.cloud.microsoft/hwav2/chat' } },
    ]) {
      const response = { id: 9, result: { result: { type: 'object', value } } };
      expect(JSON.parse(normalizeTargetInfo(JSON.stringify(response)))).toEqual(response);
    }
  });

  test('aliases of one browser share its lock but distinct browsers do not', () => {
    const first = new URL('ws://127.0.0.1:9222/devtools/browser/one');
    const alias = new URL('ws://[::1]:9222/devtools/browser/one');
    const other = new URL('ws://127.0.0.1:9222/devtools/browser/two');
    expect(browserLockName(first)).toBe(browserLockName(alias));
    expect(browserLockName(first)).not.toBe(browserLockName(other));
  });
});

function sessionFixture(initialUrl = 'https://teams.microsoft.com/v2/') {
  const page = {
    url: mock(() => initialUrl),
    isClosed: mock(() => false),
    setDefaultTimeout: mock((_timeout: number) => {}),
    setDefaultNavigationTimeout: mock((_timeout: number) => {}),
  };
  const send = mock(async () => ({ targetInfo: { targetId: 'selected' } }));
  const detach = mock(async () => {});
  const browser = { contexts: () => [{
    pages: () => [page],
    newCDPSession: async () => ({ send, detach }),
  }] } as unknown as Browser;
  return { browser, page, send, detach };
}

function sessionInput(lines: string[]) {
  const next = mock(async (): Promise<IteratorResult<string>> => lines.length
    ? { done: false, value: lines.shift()! } : { done: true, value: undefined });
  const close = mock(async (): Promise<IteratorResult<string>> => ({ done: true, value: undefined }));
  const input = { next, return: close, [Symbol.asyncIterator]() { return this; } };
  return { input, next, close };
}

async function collect<T>(input: AsyncIterable<T>): Promise<T[]> {
  const result: T[] = [];
  for await (const value of input) result.push(value);
  return result;
}

describe('CDP session lifecycle', () => {
  test.each([
    { name: 'application requests followed by disconnect', requests: [{ operation: 'inspect', sequence: 1 }, { operation: 'inspect', sequence: 2 }] },
    { name: 'an immediate disconnect', requests: [] },
  ])('buffers $name while the initial target selection is pending', async ({ requests }) => {
    const { browser, send, detach } = sessionFixture();
    const selecting = Promise.withResolvers<void>();
    const selected = Promise.withResolvers<{ targetInfo: { targetId: string } }>();
    send.mockImplementation(async () => { selecting.resolve(undefined); return selected.promise; });
    const execute = mock(async (_page: Page, request: unknown) => request);
    const stream = new PassThrough();
    const lines = createInterface({ input: stream, crlfDelay: Infinity });
    const output = collect(executeSession(browser, 'teams', execute, lines, 'selected'));
    try {
      await selecting.promise;
      const closed = once(lines, 'close');
      stream.end([...requests, { operation: 'disconnect' }, { operation: 'must-not-dispatch' }]
        .map(request => JSON.stringify(request)).join('\n') + '\n');
      await closed;
      selected.resolve({ targetInfo: { targetId: 'selected' } });
      expect(await output).toEqual([
        ...requests.map(request => ({ ok: true as const, result: request })),
        { ok: true, result: { disconnected: true } },
      ]);
      expect(execute).toHaveBeenCalledTimes(requests.length);
      expect(detach).toHaveBeenCalledTimes(1);
    } finally {
      selected.resolve({ targetInfo: { targetId: 'selected' } });
      lines.close();
      stream.destroy();
      await output;
    }
  });

  test.each([
    { name: 'EOF', lines: [] },
    { name: 'disconnect', lines: ['{"operation":"disconnect"}'] },
  ])('releases the input iterator on $name', async ({ lines }) => {
    const { browser } = sessionFixture();
    const { input, close } = sessionInput([...lines]);
    await collect(executeSession(browser, 'teams', async () => null, input));
    expect(close).toHaveBeenCalledTimes(1);
  });

  test('releases the input iterator when initial selection fails', async () => {
    const { browser, send, detach } = sessionFixture();
    send.mockImplementation(async () => { throw new Error('Selection failed'); });
    const { input, next, close } = sessionInput([]);
    await expect(executeSession(browser, 'teams', async () => null, input, 'selected').next()).rejects.toThrow('Selection failed');
    expect(next).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledTimes(1);
    expect(detach).toHaveBeenCalledTimes(1);
  });

  test('releases the input iterator when reading fails', async () => {
    const { browser } = sessionFixture();
    const { input, next, close } = sessionInput([]);
    next.mockImplementation(async () => { throw new Error('Input failed'); });
    await expect(executeSession(browser, 'teams', async () => null, input).next()).rejects.toThrow('Input failed');
    expect(close).toHaveBeenCalledTimes(1);
  });

  test('releases the input iterator when the consumer stops after a result', async () => {
    const { browser } = sessionFixture();
    const { input, close } = sessionInput(['invalid JSON']);
    const session = executeSession(browser, 'teams', async () => null, input);
    expect((await session.next()).value).toMatchObject({ ok: false });
    await session.return(undefined);
    expect(close).toHaveBeenCalledTimes(1);
  });

  test.each([
    { app: 'teams' as const, url: 'https://teams.microsoft.com/v2/', unsupported: 'https://copilot.microsoft.com/' },
    { app: 'copilot' as const, url: 'https://copilot.microsoft.com/', unsupported: 'https://teams.microsoft.com/v2/' },
  ])('clears $app selection after unsupported navigation and requires an explicit reselection', async ({ app, url, unsupported }) => {
    const { browser, page, send } = sessionFixture(url);
    const execute = mock(async (_page: Page, request: unknown) => request);
    const select = JSON.stringify({ operation: 'select-target', target: 'selected' });
    const request = JSON.stringify({ operation: 'inspect' });
    async function* lines() {
      yield select;
      yield request;
      page.url.mockReturnValue(unsupported);
      yield request;
      page.url.mockReturnValue(url);
      yield request;
      yield select;
      yield request;
    }
    const error = { ok: false as const, error: 'Select an exact automation-owned target before issuing application requests; no automatic window fallback.' };
    expect(await collect(executeSession(browser, app, execute, lines()))).toEqual([
      { ok: true, result: { target: 'selected' } },
      { ok: true, result: { operation: 'inspect' } },
      error,
      error,
      { ok: true, result: { target: 'selected' } },
      { ok: true, result: { operation: 'inspect' } },
    ]);
    expect(execute).toHaveBeenCalledTimes(2);
    expect(execute.mock.calls.every(([selectedPage]) => selectedPage === (page as unknown as Page))).toBe(true);
    expect(send).toHaveBeenCalledTimes(2);
  });
});
