import type { PluginServerContext } from "@getpaseo/plugin/server";
import type { PluginSettingsState } from "@getpaseo/plugin/server";
import { createLivenessProbe } from "./server/liveness";
import { resolveRunRoot } from "./server/run-root";
import { createRunStore } from "./server/run-store";
import { followRun, listRuns, runDetail } from "./shared/runs";
import { OBSERVER_DEFAULTS, observerSettings, observerSettingsSchema, type ObserverSettings } from "./shared/settings";

/**
 * Read-only observer for gdd launcher runs.
 *
 * The plugin only reads what a run writes: it never writes into a run directory, never finalizes a
 * run, and never signals a process. Logging stays limited to counters, paths, and tool names.
 */
export default function contribute(server: PluginServerContext) {
  const current: ObserverSettings = { ...OBSERVER_DEFAULTS };
  const probe = createLivenessProbe();
  const settings = server.registerSettings(observerSettings);
  const store = createRunStore({
    probe,
    config: () => ({
      runRoot: current.runRoot,
      pollIntervalMs: current.pollIntervalMs,
      tailLines: current.tailLines,
    }),
    log: (message) => console.log(`[observer] ${message}`),
  });

  const apply = (state: PluginSettingsState<typeof observerSettingsSchema>) => {
    if (state.status !== "ready") return;
    current.runRoot = state.values.runRoot;
    current.pollIntervalMs = state.values.pollIntervalMs;
    current.tailLines = state.values.tailLines;
  };

  settings.subscribe((state) => apply(state));
  void settings
    .read()
    .then((state) => {
      apply(state);
      const resolved = resolveRunRoot(current.runRoot);
      console.log(
        `[observer] run root ${resolved.root} (source=${resolved.source} exists=${resolved.exists}) probe=${probe.kind} poll=${current.pollIntervalMs}ms tail=${current.tailLines}`,
      );
    })
    .catch((error: unknown) => {
      console.error(
        `[observer] settings read failed, using defaults: ${error instanceof Error ? error.message : String(error)}`,
      );
    });

  server.handle(listRuns, () => store.listRuns());
  server.handle(runDetail, ({ id, tailLines }) => store.runDetail(id, tailLines));
  server.handle(followRun, ({ id, tailLines }) => store.follow(id, tailLines));

  return () => {
    store.dispose();
  };
}
