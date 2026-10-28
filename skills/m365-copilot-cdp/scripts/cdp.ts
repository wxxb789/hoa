import { chromium, type Browser, type Page } from 'playwright-core';
import { readFile, open, unlink, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { createHash } from 'node:crypto';
import { parseArgs } from 'node:util';
import { createInterface } from 'node:readline';

export type App = 'teams' | 'copilot';
export type Target = Readonly<{ id: string; title: string; url: string }>;
export type DesktopConnection = Readonly<{ browser: Browser; close: () => Promise<void> }>;
type Executor = (page: Page, request: unknown) => Promise<unknown>;
export type SessionResult = { ok: true; result: unknown } | { ok: false; error: string };

export async function* executeSession(browser: Browser, app: App, execute: Executor, lines: AsyncIterable<string>, initialTarget?: string): AsyncGenerator<SessionResult> {
  // Readline starts buffering when its iterator is created, before CDP selection can yield.
  const input = lines[Symbol.asyncIterator]();
  try {
    let page = initialTarget ? await selectPage(browser, app, initialTarget) : undefined;
    while (true) {
      const { value: line, done } = await input.next();
      if (done) return;
      if (!line.trim()) continue;
      try {
        const request: unknown = JSON.parse(line);
        const command = request && typeof request === 'object' && !Array.isArray(request) ? request as Record<string, unknown> : undefined;
        if (command?.operation === 'disconnect' && Object.keys(command).length === 1) {
          yield { ok: true, result: { disconnected: true } };
          return;
        }
        if (command?.operation === 'targets' && Object.keys(command).length === 1) {
          yield { ok: true, result: { targets: await targets(browser) } };
        } else if (command?.operation === 'select-target') {
          page = undefined;
          if (Object.keys(command).length !== 2 || typeof command.target !== 'string' || !command.target) throw new Error('select-target requires exactly operation and a nonempty target ID.');
          page = await selectPage(browser, app, command.target);
          yield { ok: true, result: { target: command.target } };
        } else {
          if (!page || page.isClosed() || !appUrl(app, page.url())) {
            page = undefined;
            throw new Error('Select an exact automation-owned target before issuing application requests; no automatic window fallback.');
          }
          page.setDefaultTimeout(10_000);
          page.setDefaultNavigationTimeout(20_000);
          yield { ok: true, result: await execute(page, request) };
        }
      } catch (error) {
        yield { ok: false, error: error instanceof Error ? error.message : String(error) };
      }
    }
  } finally { await input.return?.(); }
}

export function localEndpoint(value: string): URL {
  const url = new URL(value);
  const allowedPath = url.protocol === 'http:' ? url.pathname === '/'
    : url.protocol === 'ws:' && /^\/devtools\/browser\/[A-Za-z0-9-]+$/.test(url.pathname);
  if (!allowedPath || !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      || url.username || url.password || url.search || url.hash) {
    throw new Error('CDP endpoint must be a loopback HTTP origin or browser WebSocket URL.');
  }
  // Use one address for localhost so the lock and connection identify the same endpoint.
  if (url.hostname === 'localhost') url.hostname = '127.0.0.1';
  return url;
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid CDP response.');
  return value as Record<string, unknown>;
}

async function getJson(endpoint: URL, path: string): Promise<unknown> {
  const response = await fetch(new URL(path, endpoint), { redirect: 'error', signal: AbortSignal.timeout(5_000) });
  if (!response.ok) throw new Error(`CDP discovery failed: HTTP ${response.status}.`);
  return response.json();
}

async function targets(browser: Browser): Promise<readonly Target[]> {
  const session = await browser.newBrowserCDPSession();
  try {
    const { targetInfos } = await session.send('Target.getTargets');
    return targetInfos.filter(target => target.type === 'page' || target.type === 'webview')
      .map(target => ({ id: target.targetId, title: target.title, url: target.url }));
  } finally { await session.detach(); }
}

export function appUrl(app: App, value: string): boolean {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:') return false;
    const hosts = app === 'teams'
      ? ['teams.microsoft.com', 'teams.cloud.microsoft', 'teams.live.com']
      : ['cr.m365copilotapp.svc.cloud.microsoft', 'm365.cloud.microsoft', 'copilot.cloud.microsoft', 'copilot.microsoft.com', 'www.microsoft365.com'];
    return hosts.includes(url.hostname);
  } catch { return false; }
}

async function browserSocket(endpoint: URL): Promise<string> {
  if (endpoint.protocol === 'ws:') return endpoint.href;
  const info = object(await getJson(endpoint, '/json/version'));
  if (typeof info.webSocketDebuggerUrl !== 'string') throw new Error('CDP has no browser WebSocket endpoint.');
  const socket = localEndpoint(info.webSocketDebuggerUrl);
  if (socket.protocol !== 'ws:' || socket.port !== endpoint.port) {
    throw new Error('CDP advertised a WebSocket on a different port; refusing to attach.');
  }
  return socket.href;
}

export function normalizeTargetInfo(message: string, responseMethod?: string): string {
  const packet = object(JSON.parse(message));
  const normalize = (info: unknown): unknown => {
    const row = object(info);
    return row.type === 'webview' && typeof row.url === 'string' && appUrl('copilot', row.url)
      ? { ...row, type: 'page' } : row;
  };
  if (['Target.attachedToTarget', 'Target.targetCreated', 'Target.targetInfoChanged'].includes(String(packet.method))) {
    const params = object(packet.params);
    params.targetInfo = normalize(params.targetInfo);
  } else if (packet.result && responseMethod === 'Target.getTargetInfo') {
    const result = object(packet.result);
    result.targetInfo = normalize(result.targetInfo);
  } else if (packet.result && responseMethod === 'Target.getTargets') {
    const result = object(packet.result);
    if (!Array.isArray(result.targetInfos)) throw new Error('Invalid CDP target list.');
    result.targetInfos = result.targetInfos.map(normalize);
  } else { return message; }
  return JSON.stringify(packet);
}

function webviewRelay(upstreamUrl: string) {
  type Peer = { upstream: WebSocket; queued: string[] };
  const token = crypto.randomUUID();
  const pending = new Map<string, string>();
  let upstream: WebSocket | undefined;
  const server = Bun.serve<Peer>({
    hostname: '127.0.0.1', port: 0,
    fetch(request, server) {
      if (new URL(request.url).pathname !== `/${token}` || upstream) return new Response(null, { status: 404 });
      upstream = new WebSocket(upstreamUrl);
      if (server.upgrade(request, { data: { upstream, queued: [] } })) return;
      upstream.close();
      return new Response(null, { status: 400 });
    },
    websocket: {
      open(peer) {
        peer.data.upstream.onopen = () => {
          for (const message of peer.data.queued) peer.data.upstream.send(message);
          peer.data.queued = [];
        };
        peer.data.upstream.onmessage = event => {
          try {
            const text = String(event.data);
            const packet = object(JSON.parse(text));
            const key = `${packet.sessionId ?? ''}:${packet.id}`;
            const method = pending.get(key);
            pending.delete(key);
            peer.send(normalizeTargetInfo(text, method));
          } catch { peer.close(1011, 'Invalid CDP message'); }
        };
        peer.data.upstream.onclose = () => peer.close();
        peer.data.upstream.onerror = () => peer.close(1011, 'CDP connection failed');
      },
      message(peer, message) {
        const text = String(message);
        const packet = object(JSON.parse(text));
        if (packet.method === 'Target.getTargets' || packet.method === 'Target.getTargetInfo') {
          pending.set(`${packet.sessionId ?? ''}:${packet.id}`, packet.method);
        }
        if (peer.data.upstream.readyState === WebSocket.OPEN) peer.data.upstream.send(text);
        else peer.data.queued.push(text);
      },
      close(peer) { peer.data.upstream.close(); },
    },
  });
  return {
    endpoint: `ws://127.0.0.1:${server.port}/${token}`,
    async close() { upstream?.close(); await server.stop(true); },
  };
}

async function artifactDirectory(): Promise<string> {
  const cwd = process.cwd();
  let root = cwd;
  while (!existsSync(join(root, '.git')) && dirname(root) !== root) root = dirname(root);
  if (!existsSync(join(root, '.git'))) root = cwd;
  const directory = join(root, '.tmp-artifacts', 'desktop-cdp');
  await mkdir(directory, { recursive: true });
  return directory;
}

export function browserLockName(socket: URL): string {
  return `hoa-cdp-${createHash('sha256').update(socket.pathname).digest('hex').slice(0, 32)}.lock`;
}

export async function connectDesktop(app: App, endpoint: URL): Promise<DesktopConnection> {
  const socket = await browserSocket(endpoint);
  // Playwright ignores Chromium's webview target type, used by Copilot's working surface.
  const relay = app === 'copilot' ? webviewRelay(socket) : undefined;
  try {
    const browser = await chromium.connectOverCDP(relay?.endpoint ?? socket, {
      timeout: 60_000, noDefaults: true, artifactsDir: await artifactDirectory(),
    });
    return { browser, async close() { try { await browser.close(); } finally { await relay?.close(); } } };
  } catch (error) { await relay?.close(); throw error; }
}

async function selectPage(browser: Browser, app: App, targetId: string): Promise<Page> {
  for (const context of browser.contexts()) {
    for (const page of context.pages()) {
      if (!appUrl(app, page.url())) continue;
      const session = await context.newCDPSession(page);
      try {
        const { targetInfo } = await session.send('Target.getTargetInfo');
        if (targetInfo.targetId === targetId) return page;
      } finally { await session.detach(); }
    }
  }
  throw new Error('Requested target is missing or is not a supported application URL. Run --targets; never substitute another window.');
}

function usage(app: App): string {
  const entry = app === 'teams' ? 'teams.ts' : 'copilot.ts';
  return `Usage: bun ${entry} --targets [--endpoint http://127.0.0.1:${app === 'teams' ? 9222 : 9223}]
       bun ${entry} --request <JSON-file|-> --target <exact-id> [--endpoint <origin|browser-ws>] [--profile-root <existing User Data>]
       bun ${entry} --session [--target <exact-id>] [--profile-root <existing User Data>]

--request - reads JSON from stdin. See this skill's SKILL.md for request operations.
--session accepts one JSON request per stdin line and reuses one approved connection.
With no initial target, use {"operation":"targets"} and {"operation":"select-target","target":"exact-id"} within that connection.
Application requests revalidate the selected app URL; unsupported navigation clears selection.
Send {"operation":"disconnect"} to release the connection without closing the app.
--profile-root reads only the existing profile's DevToolsActivePort; it never creates or copies a profile.
Choose an automation-owned window, or obtain explicit permission to share the selected window.
The app must already be running with local CDP enabled and signed in.
No browser is downloaded or launched. Closing the connection leaves the app running.
Errors after dispatch may mean the message was sent; inspect before retrying.
`;
}

export async function runCli(app: App, execute: Executor): Promise<void> {
  let connection: DesktopConnection | undefined;
  let lockPath: string | undefined;
  try {
    const { values } = parseArgs({ options: {
      endpoint: { type: 'string' }, 'profile-root': { type: 'string' }, target: { type: 'string' }, request: { type: 'string' },
      targets: { type: 'boolean' }, session: { type: 'boolean' }, help: { type: 'boolean', short: 'h' },
    }, allowPositionals: false, strict: true });
    if (values.help) { process.stdout.write(usage(app)); return; }
    if ([values.targets, values.request, values.session].filter(Boolean).length !== 1) {
      throw new Error('Choose exactly one of --targets, --request <file|->, or --session.');
    }
    if (values.targets && values.target) throw new Error('--target applies only to --request or --session.');
    if (values.request && !values.target) throw new Error('--request requires an explicit --target for an automation-owned or explicitly shared window.');
    if (values.endpoint && values['profile-root']) throw new Error('Choose --endpoint or --profile-root, not both.');
    let endpoint: URL;
    if (values['profile-root']) {
      const [port, path] = (await readFile(join(values['profile-root'], 'DevToolsActivePort'), 'utf8')).trim().split(/\r?\n/);
      if (!port || !/^\d+$/.test(port) || !path) throw new Error('Invalid existing-profile DevToolsActivePort.');
      endpoint = localEndpoint(`ws://127.0.0.1:${port}${path}`);
    } else {
      endpoint = localEndpoint(values.endpoint ?? `http://127.0.0.1:${app === 'teams' ? 9222 : 9223}`);
    }
    const socket = new URL(await browserSocket(endpoint));
    if (values['profile-root']) process.stderr.write('Connecting to your signed-in Copilot profile. If Copilot shows "Allow remote debugging?", choose Allow once for this connection. Use --session to avoid reconnecting for each command; never approve an unexpected request.\n');
    if (values.targets) {
      connection = await connectDesktop(app, socket);
      process.stdout.write(`${JSON.stringify({ targets: await targets(connection.browser) })}\n`);
      return;
    }
    const request: unknown = values.session ? undefined : JSON.parse(values.request === '-'
      ? await new Response(Bun.stdin.stream()).text()
      : await readFile(values.request!, 'utf8'));
    const lock = join(tmpdir(), browserLockName(socket));
    let handle;
    try { handle = await open(lock, 'wx', 0o600); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'EEXIST') {
        throw new Error(`Another command owns this endpoint (${lock}). If it crashed, confirm it exited before removing the lock.`);
      }
      throw error;
    }
    lockPath = lock;
    try { await handle.writeFile(`${process.pid}\n`); }
    finally { await handle.close(); }
    connection = await connectDesktop(app, socket);
    if (values.session) {
      process.stdout.write(`${JSON.stringify({ ready: true, target: values.target ?? null, targets: await targets(connection.browser), protocol: 'JSONL', approval: 'reused-until-disconnected' })}\n`);
      const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
      try {
        for await (const result of executeSession(connection.browser, app, execute, input, values.target)) process.stdout.write(`${JSON.stringify(result)}\n`);
      } finally { input.close(); }
    } else {
      const page = await selectPage(connection.browser, app, values.target!);
      page.setDefaultTimeout(10_000);
      page.setDefaultNavigationTimeout(20_000);
      process.stdout.write(`${JSON.stringify({ ok: true, result: await execute(page, request) })}\n`);
    }
  } catch (error) {
    process.stderr.write(`${JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) })}\n`);
    process.exitCode = 1;
  } finally {
    // Disconnect this client without closing the user's desktop application.
    try { await connection?.close(); }
    finally { if (lockPath) await unlink(lockPath); }
  }
}
