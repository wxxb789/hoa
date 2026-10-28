import { readFile, open, rename, unlink } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { parseArgs } from 'node:util';

type JsonObject = Record<string, unknown>;
export type PreviousConsent = Readonly<{ present: boolean; value: boolean | null }>;
function asObject(value: unknown): JsonObject {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Unexpected preference object shape; no change made.');
  return value as JsonObject;
}

export function updateConsent(original: string, desired: boolean | undefined) {
  const state = asObject(JSON.parse(original));
  const devtools = state.devtools === undefined ? {} : asObject(state.devtools);
  const debugging = devtools.remote_debugging === undefined ? {} : asObject(devtools.remote_debugging);
  const value = debugging['user-enabled'];
  if (value !== undefined && typeof value !== 'boolean') throw new Error('Unexpected debugging preference type; no change made.');
  const previous: PreviousConsent = { present: value !== undefined, value: value ?? null };
  if (desired === value) return { text: original, previous };
  if (desired === undefined) delete debugging['user-enabled'];
  else debugging['user-enabled'] = desired;
  devtools.remote_debugging = debugging;
  state.devtools = devtools;
  return { text: JSON.stringify(state), previous };
}

export function restoreValue(value: unknown): boolean | undefined {
  const row = asObject(value);
  if (Object.keys(row).some(key => key !== 'present' && key !== 'value')
      || typeof row.present !== 'boolean' || (row.present ? typeof row.value !== 'boolean' : row.value !== null)) {
    throw new Error('Invalid previous-consent record; no change made.');
  }
  return row.present ? row.value as boolean : undefined;
}

async function replaceLocalState(path: string, original: string, updated: string): Promise<void> {
  if (updated === original) return;
  // Atomic replacement inside the same existing profile; no profile or credential export.
  const temporary = `${path}.hoa-${crypto.randomUUID()}.tmp`;
  const handle = await open(temporary, 'wx', 0o600);
  try {
    await handle.writeFile(updated);
    await handle.sync();
    await handle.close();
    if (await readFile(path, 'utf8') !== original) throw new Error('Local State changed concurrently; refusing replacement.');
    await rename(temporary, path);
  } catch (error) {
    await handle.close().catch(() => undefined);
    await unlink(temporary).catch(() => undefined);
    throw error;
  }
}

async function persistReceipt(path: string, previous: PreviousConsent): Promise<void> {
  const handle = await open(path, 'wx', 0o600).catch((error: NodeJS.ErrnoException) => {
    if (error.code === 'EEXIST') throw new Error('Rollback receipt already exists; restore it before enabling again. No change made.');
    throw error;
  });
  try {
    await handle.writeFile(`${JSON.stringify(previous)}\n`);
    await handle.sync();
    await handle.close();
  } catch (error) {
    await handle.close().catch(() => undefined);
    await unlink(path).catch(() => undefined);
    throw error;
  }
}

export async function enableConsent(path: string, receipt: string): Promise<void> {
  const original = await readFile(path, 'utf8');
  const updated = updateConsent(original, true);
  // Flush and close an exclusively created receipt before touching Local State.
  await persistReceipt(receipt, updated.previous);
  await replaceLocalState(path, original, updated.text);
}

export async function restoreConsent(path: string, receipt: string): Promise<boolean | undefined> {
  const desired = restoreValue(JSON.parse(await readFile(receipt, 'utf8')));
  const original = await readFile(path, 'utf8');
  await replaceLocalState(path, original, updateConsent(original, desired).text);
  // Consume the receipt only after restoration succeeds; failed mutations keep it.
  await unlink(receipt);
  return desired;
}

export function parseConsentArgs(args: string[]) {
  const { values } = parseArgs({ args, options: {
    'profile-root': { type: 'string' }, enable: { type: 'boolean' }, inspect: { type: 'boolean' },
    receipt: { type: 'string' }, restore: { type: 'string' }, 'confirm-app-closed': { type: 'boolean' },
  }, allowPositionals: false });
  if (!values['profile-root'] || [values.enable, values.inspect, values.restore].filter(Boolean).length !== 1) {
    throw new Error('Use --profile-root <existing User Data> and exactly one of --inspect, --enable --receipt <receipt.json>, or --restore <receipt.json>.');
  }
  if (values.enable ? !values.receipt : values.receipt !== undefined) {
    throw new Error('The --receipt <receipt.json> option is required with --enable and is not accepted with --inspect or --restore.');
  }
  return values;
}

async function main(): Promise<void> {
  const values = parseConsentArgs(process.argv.slice(2));
  const path = join(values['profile-root']!, 'Local State');
  if (values.inspect) {
    console.log(JSON.stringify(updateConsent(await readFile(path, 'utf8'), undefined).previous));
    return;
  }
  if (!values['confirm-app-closed']) throw new Error('Close Copilot normally and pass --confirm-app-closed. No process is stopped by this helper.');
  if (process.platform !== 'win32') throw new Error('This consent setup helper supports the Windows desktop app only.');
  const running = execFileSync('tasklist.exe', ['/FI', 'IMAGENAME eq copilotapp.exe', '/FO', 'CSV', '/NH'], { encoding: 'utf8', windowsHide: true });
  if (running.toLowerCase().includes('"copilotapp.exe"')) throw new Error('Copilot is still running; Local State was not changed.');
  let enabled: boolean | undefined;
  if (values.restore) enabled = await restoreConsent(path, values.restore);
  else {
    await enableConsent(path, values.receipt!);
    enabled = true;
  }
  console.log(JSON.stringify({ enabled: enabled ?? false, receipt: values.restore ?? values.receipt, restored: Boolean(values.restore), authentication: 'unchanged', approval: 'Application connection consent remains enabled.' }));
}

if (import.meta.main) {
  try { await main(); }
  catch (error) { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1; }
}
