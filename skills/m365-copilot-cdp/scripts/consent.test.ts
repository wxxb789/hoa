import { expect, test } from 'bun:test';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { enableConsent, parseConsentArgs, restoreConsent, restoreValue, updateConsent } from './consent.ts';

test('enables only the debugging preference without changing unrelated profile state', () => {
  const state = { profile: { last_used: 'Default' }, synthetic_auth: { unchanged: 'fixture-only' }, devtools: { theme: 'dark', remote_debugging: { allowed: true } } };
  const result = updateConsent(JSON.stringify(state), true);
  expect(JSON.parse(result.text)).toEqual({ ...state, devtools: { ...state.devtools, remote_debugging: { allowed: true, 'user-enabled': true } } });
  expect(result.previous).toEqual({ present: false, value: null });
  const restored = updateConsent(result.text, restoreValue(result.previous));
  expect(JSON.parse(restored.text)).toEqual(state);
});

test('restores a previously disabled preference and preserves no-op source bytes', () => {
  const original = '{ "devtools": { "remote_debugging": { "user-enabled": false } } }';
  const enabled = updateConsent(original, true);
  expect(enabled.previous).toEqual({ present: true, value: false });
  expect(updateConsent(original, false).text).toBe(original);
  expect(JSON.parse(updateConsent(enabled.text, restoreValue(enabled.previous)).text)).toEqual(JSON.parse(original));
});

test('rejects malformed state and rollback values before replacement', () => {
  for (const original of ['[]', '{"devtools":[]}', '{"devtools":{"remote_debugging":null}}', '{"devtools":{"remote_debugging":{"user-enabled":"yes"}}}']) {
    expect(() => updateConsent(original, true)).toThrow();
  }
  for (const previous of [{ present: true, value: null }, { present: false, value: true }, { present: false }, { present: true, value: false, auth: 'unexpected' }]) {
    expect(() => restoreValue(previous)).toThrow();
  }
});

async function withProfile(run: (path: string, receipt: string, directory: string) => Promise<void>): Promise<void> {
  const root = resolve(import.meta.dir, '../../../.tmp-artifacts/copilot-consent-tests');
  await mkdir(root, { recursive: true });
  const directory = await mkdtemp(join(root, 'fixture-'));
  try {
    await run(join(directory, 'Local State'), join(directory, 'consent-previous.json'), directory);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

test('requires a receipt for enable and rejects receipt flags on other operations', () => {
  expect(parseConsentArgs(['--profile-root', 'fixture', '--enable', '--receipt', 'receipt.json', '--confirm-app-closed']).receipt).toBe('receipt.json');
  expect(() => parseConsentArgs(['--profile-root', 'fixture', '--enable'])).toThrow('--receipt');
  for (const operation of [['--inspect'], ['--restore', 'previous.json']]) {
    expect(() => parseConsentArgs(['--profile-root', 'fixture', ...operation, '--receipt', 'receipt.json'])).toThrow('--receipt');
  }
});

test.each([
  ['absent', '{ "profile": { "last_used": "Default" }, "devtools": { "remote_debugging": { "allowed": true } } }', { present: false, value: null }],
  ['false', '{ "profile": { "last_used": "Default" }, "devtools": { "remote_debugging": { "allowed": true, "user-enabled": false } } }', { present: true, value: false }],
] as const)('refuses duplicate receipts and retains the original %s preference for rollback', async (_label, original, previous) => {
  await withProfile(async (path, receipt) => {
    await writeFile(path, original);
    await enableConsent(path, receipt);
    const saved = await readFile(receipt, 'utf8');
    const enabled = await readFile(path, 'utf8');
    expect(JSON.parse(saved)).toEqual(previous);
    expect(JSON.parse(enabled).devtools.remote_debugging).toEqual({ allowed: true, 'user-enabled': true });
    await expect(enableConsent(path, receipt)).rejects.toThrow('receipt already exists');
    expect(await readFile(receipt, 'utf8')).toBe(saved);
    expect(await readFile(path, 'utf8')).toBe(enabled);
    const changed = JSON.parse(enabled);
    changed.profile.last_used = 'Changed after enable';
    await writeFile(path, JSON.stringify(changed));
    await restoreConsent(path, receipt);
    const expected = JSON.parse(original);
    expected.profile.last_used = 'Changed after enable';
    expect(JSON.parse(await readFile(path, 'utf8'))).toEqual(expected);
    await expect(readFile(receipt, 'utf8')).rejects.toThrow();
  });
});

test.each([
  ['absent', '{ "unrelated": true }'],
  ['false', '{ "devtools": { "remote_debugging": { "user-enabled": false } }, "unrelated": true }'],
] as const)('leaves the original %s preference byte-for-byte unchanged when receipt persistence fails', async (_label, original) => {
  await withProfile(async (path, _receipt, directory) => {
    await writeFile(path, original);
    await expect(enableConsent(path, join(directory, 'missing-parent', 'receipt.json'))).rejects.toThrow();
    expect(await readFile(path, 'utf8')).toBe(original);
  });
});

test('keeps already-enabled Local State bytes and records its original true preference', async () => {
  await withProfile(async (path, receipt) => {
    const original = '{ "devtools": { "remote_debugging": { "user-enabled": true } }, "unrelated": true }';
    await writeFile(path, original);
    await enableConsent(path, receipt);
    expect(await readFile(path, 'utf8')).toBe(original);
    expect(JSON.parse(await readFile(receipt, 'utf8'))).toEqual({ present: true, value: true });
    await restoreConsent(path, receipt);
    expect(await readFile(path, 'utf8')).toBe(original);
  });
});
