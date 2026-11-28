#!/usr/bin/env node
/**
 * Playwright + CDP browser timing probe — copy, then adapt only the CONFIG block.
 *
 * Reports: per-dispatch page-clock latency (dispatch -> observed DOM change), plus
 * whatever engine spans the app exposes through `window.__events`.
 *
 * Usage:  node probe-browser-timing.mjs
 * Config: SITE_DIR (required), PAGE_PATH, ACTION_SELECTOR, OBSERVED_SELECTOR,
 *         DEVICE, THROTTLE, ITERATIONS, OUT
 */
import { createServer } from 'node:http';
import { existsSync, readFileSync, statSync, writeFileSync, mkdirSync } from 'node:fs';
import { extname, join, resolve, dirname } from 'node:path';
import { gzipSync } from 'node:zlib';
import { chromium, devices } from 'playwright';

// ---- CONFIG ---------------------------------------------------------------
const SITE_DIR = process.env.SITE_DIR;
const PAGE_PATH = process.env.PAGE_PATH ?? '/';
const ACTION_SELECTOR = process.env.ACTION_SELECTOR ?? 'button[data-action]';
const OBSERVED_SELECTOR = process.env.OBSERVED_SELECTOR ?? '#results';
const DEVICE = process.env.DEVICE ?? 'Pixel 7';
const THROTTLE = Number(process.env.THROTTLE ?? 4);
const ITERATIONS = Number(process.env.ITERATIONS ?? 30);
const OUT = process.env.OUT ?? join(process.cwd(), 'probe.json');
if (!SITE_DIR) throw new Error('SITE_DIR is required (a built static directory)');
const DIST = resolve(SITE_DIR);
// ---------------------------------------------------------------------------

const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml',
  '.wasm': 'application/wasm', '.sqlite': 'application/vnd.sqlite3',
  '.woff2': 'font/woff2', '.png': 'image/png', '.ico': 'image/x-icon',
};
const COMPRESSIBLE = new Set(['.html', '.js', '.mjs', '.css', '.json', '.svg', '.wasm', '.sqlite']);

function startServer(dist) {
  const server = createServer((req, res) => {
    const pathname = decodeURIComponent(new URL(req.url ?? '/', 'http://127.0.0.1').pathname);
    let file = resolve(dist, `.${pathname}`);
    if (!file.startsWith(dist)) return void res.writeHead(403).end('forbidden');
    if (existsSync(file) && statSync(file).isDirectory()) file = join(file, 'index.html');
    if (!existsSync(file)) return void res.writeHead(404).end('not found');
    const body = readFileSync(file);
    const ext = extname(file).toLowerCase();
    const headers = { 'content-type': MIME[ext] ?? 'application/octet-stream' };
    if (/\bgzip\b/.test(String(req.headers['accept-encoding'] ?? '')) && COMPRESSIBLE.has(ext) && body.length > 256) {
      const zipped = gzipSync(body);
      headers['content-encoding'] = 'gzip';
      headers['content-length'] = String(zipped.length);
      res.writeHead(200, headers).end(zipped);
    } else {
      headers['content-length'] = String(body.length);
      res.writeHead(200, headers).end(body);
    }
  });
  return new Promise((ok, bad) => {
    server.once('error', bad);
    server.listen(0, '127.0.0.1', () => ok({ server, origin: `http://127.0.0.1:${server.address().port}` }));
  });
}

// Page-side recorder: arm engine telemetry seams here, before any script dispatches.
const recorder = (observedSelector) => {
  window.__measurement = true; // adapt: some runtimes gate diagnostic spans on a flag read at dispatch
  window.__events = [];
  document.addEventListener('app-result', (event) => window.__events.push({
    t: performance.now(),
    operationMs: event.detail?.operationMs ?? null,
    engineMs: event.detail?.sqlMs ?? null,
  }));
  window.__observedSelector = observedSelector;
};

const result = { page: PAGE_PATH, device: DEVICE, throttle: THROTTLE, samples: [], failures: [] };
let handle, browser;
try {
  handle = await startServer(DIST);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const { defaultBrowserType: _ignored, ...deviceOptions } = devices[DEVICE];
  const context = await browser.newContext({ ...deviceOptions });
  await context.addInitScript(recorder, OBSERVED_SELECTOR);
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: THROTTLE });

  await page.goto(`${handle.origin}${PAGE_PATH}`, { waitUntil: 'load', timeout: 120_000 });
  await page.waitForSelector(OBSERVED_SELECTOR, { timeout: 30_000 });
  await page.waitForTimeout(300);

  for (let i = 0; i < ITERATIONS; i += 1) {
    const sample = await page.evaluate(async ({ action, observed }) => {
      const list = document.querySelector(observed);
      const button = document.querySelector(action);
      if (list === null || button === null || button.hidden || button.disabled) return { done: true };
      const before = list.childElementCount;
      const t0 = performance.now();
      button.click();
      const seen = await new Promise((res) => {
        const tick = () => (list.childElementCount > before ? res(performance.now()) : requestAnimationFrame(tick));
        tick();
      });
      const last = window.__events.at(-1) ?? null;
      return {
        dispatchMs: seen - t0,
        operationMs: last?.operationMs ?? null,
        engineMs: last?.engineMs ?? null,
        items: list.childElementCount,
      };
    }, { action: ACTION_SELECTOR, observed: OBSERVED_SELECTOR });
    if (sample.done) { result.failures.push(`action exhausted after ${result.samples.length} iterations`); break; }
    result.samples.push(sample);
  }

  const values = result.samples.map((s) => s.dispatchMs).filter((v) => typeof v === 'number').sort((a, b) => a - b);
  const q = (p) => (values.length ? values[Math.max(0, Math.ceil((p / 100) * values.length) - 1)] : null);
  result.summary = { n: values.length, p50: q(50), p95: q(95), min: values[0] ?? null, max: values.at(-1) ?? null };
} catch (error) {
  result.failures.push(String(error?.stack ?? error));
} finally {
  try { if (browser) await browser.close(); } catch (e) { result.failures.push('close: ' + e); }
  if (handle) await new Promise((r) => handle.server.close(r));
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify(result.summary ?? result.failures, null, 2));
}
