import { statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { RunRootSource } from "../shared/runs";

export type RunRootCandidate = { path: string; source: RunRootSource; exists: boolean };

export type RunRootResolution = {
  root: string;
  source: RunRootSource;
  exists: boolean;
  candidates: RunRootCandidate[];
};

function isDirectory(path: string): boolean {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
}

function key(path: string): string {
  const normalized = path.replace(/[\\/]+$/, "");
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}

/**
 * Resolve the launcher run root.
 *
 * An explicit plugin setting or `GDD_RUN_ROOT` is authoritative (a missing path is reported as
 * missing, never silently replaced). Without either, the documented default
 * `${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs` wins, and the Windows-native
 * `%LOCALAPPDATA%/gdd/runs` is used when that default does not exist on disk.
 */
export function resolveRunRoot(
  override: string,
  env: NodeJS.ProcessEnv = process.env,
): RunRootResolution {
  const candidates: RunRootCandidate[] = [];
  const add = (path: string | undefined, source: RunRootSource) => {
    const trimmed = path?.trim();
    if (!trimmed) return;
    if (candidates.some((candidate) => key(candidate.path) === key(trimmed))) return;
    candidates.push({ path: trimmed, source, exists: isDirectory(trimmed) });
  };

  const home = env.HOME?.trim() || env.USERPROFILE?.trim() || homedir();
  const stateHome = env.XDG_STATE_HOME?.trim();
  const localAppData = env.LOCALAPPDATA?.trim();
  const defaultRoot = join(home, ".local", "state", "gdd", "runs");

  add(override, "setting");
  add(env.GDD_RUN_ROOT, "env");
  if (stateHome) add(join(stateHome, "gdd", "runs"), "xdg");
  add(defaultRoot, "home");
  add(localAppData ? join(localAppData, "gdd", "runs") : undefined, "localappdata");

  const explicit = candidates.find(
    (candidate) => candidate.source === "setting" || candidate.source === "env",
  );
  if (explicit) {
    return { root: explicit.path, source: explicit.source, exists: explicit.exists, candidates };
  }

  const existing = candidates.find((candidate) => candidate.exists);
  if (existing) {
    return { root: existing.path, source: existing.source, exists: true, candidates };
  }
  return { root: defaultRoot, source: "default", exists: false, candidates };
}
