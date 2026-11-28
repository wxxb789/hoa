# Recipes

Concrete procedure behind the rules in `SKILL.md`. Every step is cheap; the expensive mistakes are
skipping one of them.

## 1. Scaffold a probe (built site, no dev server)

1. Materialise the corpus with the project's own generator at a stated seed, then build with the
   **packaged** artifact you mean to judge (`node <pkg>/bin/<cli>.mjs build --content … --out dist`),
   so the numbers describe what ships rather than the working tree.
2. Serve `dist` yourself: static file server with gzip negotiation and the emitted `_headers` applied.
   Loopback removes network variance and makes transfer bytes the only network variable — say so in
   the report.
3. `chromium.launch({ channel: 'chrome', headless: true })` + `devices['Pixel 7']` (or the project's
   declared profile) + `newCDPSession(page)` → `Emulation.setCPUThrottlingRate { rate: 4 }`.
   Throttle applies to the page target only; the Worker target is not independently throttled. That
   is a stated limit, not a bug to work around.
4. `context.addInitScript(recorder)` for page-side observers and for arming engine telemetry seams.
5. Write the raw report to JSON in the task directory. Never keep numbers only in terminal scrollback.

## 2. Arm the runtime's telemetry seam

Reader-path code often withholds diagnostic fields unless a flag is set, and the flag is read at
**dispatch** time:

```js
const recorder = () => {
  window.__measurement = true;            // arm before any request is dispatched
  window.__events = [];
  document.addEventListener('snapshot-result', (e) => window.__events.push({
    t: performance.now(), type: e.detail?.type, operationMs: e.detail?.operationMs, sqlMs: e.detail?.sqlMs,
  }));
};
await context.addInitScript(recorder);
```

If `operationMs`/`sqlMs` arrive null, the seam was armed too late (or the reply was cached) — do not
read null as zero cost.

## 3. Time a dispatch on the page clock

One `page.evaluate`, one rAF loop. This is the measurement that survives comparison with another
instrument's page-side timestamps.

```js
const sample = await page.evaluate(async (sel) => {
  const list = document.querySelector('#results');
  const button = document.querySelector(sel);
  const before = list.childElementCount;
  const t0 = performance.now();
  button.click();
  const seen = await new Promise((res) => {
    const tick = () => (list.childElementCount > before ? res(performance.now()) : requestAnimationFrame(tick));
    tick();
  });
  const last = window.__events.at(-1) ?? null;
  return { dispatchMs: seen - t0, sqlMs: last?.sqlMs ?? null, items: list.childElementCount };
}, '#more');
```

Loop it, keep every sample, and report the slope as well as the endpoints: flat `sqlMs` with growing
`dispatchMs` means the page layer, not the engine.

## 4. Attribute a render timer that covers several phases

When one timer wraps layout + figure + table, build the pieces synthetically at the same throttle:

| Variant | What it isolates |
|---|---|
| figure, one shape per edge, labels on | per-node + per-edge + per-label cost |
| figure, labels off | label text cost |
| figure, all edges in one `<path>` | edge-node count cost |
| table, joined cell degree 5 / 20 / 40 | whether cost is `nodes × degree` |

Calibration from a hub-heavy corpus at 4× throttle, 60 nodes: figure 24 ms, figure without labels
9 ms, single-path edges 8 ms, table at degree 40 ≈ 256 ms.

**Check that the shape exists in the product before acting on it.** The same install rendered its real
global figure *and* its accessible table in 21.6 ms, because a node bound kept the table at ~60 short
rows; the 60 × 40 synthetic measured a shape no reader ever sees. Read the product's own `renderMs`
first, and treat synthetic numbers as a cliff report ("what happens if the bound moves"), never as the
current cost.

### What actually reduces an accessible table's cost

Measured on that 60-row × 40-joined-link table (2,460 anchors, 4× throttle), total = construction +
forced layout:

| Lever | Total | What it proves |
|---|---|---|
| `createElement` per node (baseline) | 238 ms (23 build / 215 layout) | layout is ~90% of the cost, not DOM calls |
| one `innerHTML` string, or `createContextualFragment` | 230 / 240 ms | parsing instead of DOM calls buys nothing |
| `content-visibility: auto` on the table element | 266 ms | the skip does not reach row layout |
| `table,tbody{display:block}` + `tr{content-visibility:auto;contain-intrinsic-size:auto 48px}` | **20.5 ms**, every link kept | rows must become block-level before containment can skip them |
| joined cell as plain text, all names kept | 44.7 ms | 2,400 fewer inline anchors removes the wrapping |
| joined cell capped at 12 + "and N more" | 21.4 ms | bounded content, some information lost |

Before shipping a layout change that claims to keep semantics, prove it — compare the accessibility
tree's role counts against the unchanged variant:

```js
const { nodes } = await cdp.send('Accessibility.getFullAXTree');
const roles = {};
for (const n of nodes) if (n.role?.value) roles[n.role.value] = (roles[n.role.value] ?? 0) + 1;
// {table:1, rowgroup:1, row:4, rowheader:3, columnheader:4, cell:9, link:9, …}
```

`display:block` on `table`/`tr` kept every role in Chrome. That is one browser's mapping, not a
cross-browser guarantee — name the browser you tested. When the row already links the entity, the
text-only cell is usually the better trade: no visual re-layout, no browser dependence, −5.5×.

## 5. Cache and transport checks

```bash
# what the site actually declares
cat public/_headers        # or the emitted dist/_headers
# is the asset content-addressed?
ls dist/data dist/wasm     # site.<sha256>.sqlite, sqlite3.<sha256>.wasm → immutable-safe
```

- Every rule must have a content-hashed filename or a hashed directory behind it. One non-hashed
  sibling (`sqlite-wasm.js`) in the same directory makes a directory-wide rule wrong.
- Compression, on the exact shipped bytes:

```js
import { gzipSync, brotliCompressSync, constants } from 'node:zlib';
const gz = gzipSync(bytes, { level: 9 }).length;
const br = brotliCompressSync(bytes, { params: { [constants.BROTLI_PARAM_QUALITY]: 11 } }).length;
```

Observed ratios: sqlite 430 KB → 127 KB gzip / 91 KB brotli (−29%), wasm 869 KB → 403 / 349 KB
(−13.5%), 643 KB JS glue → 175 / 141 KB (−19%). Then check the host: GitHub Pages gzip only,
Cloudflare Pages negotiates brotli. Report the headroom and its precondition, not the win.

## 6. Cold-start decomposition

Read the runtime's phase spans on the first reply (fetch / digest / init / import). If a dwell timer
gates the request, cold latency = dwell + phases + query; overlapping them recovers min(dwell,
phases). Report the alternative and its cost (a hover-bounce pays the transfer) as a decision.
