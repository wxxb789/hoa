import type { PluginServerContext } from "@getpaseo/plugin/server";
import type { PluginSettingsState } from "@getpaseo/plugin/server";
import { createLivenessProbe } from "./server/liveness";
import { resolveRunRoot } from "./server/run-root";
import { createRunStore } from "./server/run-store";
import { followRun, listRuns, runPaths } from "./shared/runs";
import { OBSERVER_DEFAULTS, observerSettings, observerSettingsSchema, type ObserverSettings } from "./shared/settings";

export default function contribute(server: PluginServerContext) {
  const current: ObserverSettings = { ...OBSERVER_DEFAULTS };
  const probe = createLivenessProbe();
  const settings = server.registerSettings(observerSettings);
  // No `log` wiring on the store: per-poll diagnostics must not accumulate in the daemon log.
  const store = createRunStore({
    probe,
    config: () => ({
      runRoot: current.runRoot,
      tailLines: current.tailLines,
    }),
  });

  const apply = (state: PluginSettingsState<typeof observerSettingsSchema>) => {
    if (state.status !== "ready") return;
    // Copied wholesale: a new setting reaches the store without a second edit here.
    Object.assign(current, state.values);
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

  server.handle(listRuns, ({ knownRevision }) => store.listUpdate(knownRevision));
  server.handle(runPaths, ({ id }) => store.paths(id));
  server.handle(followRun, ({ id, tailLines }) => store.follow(id, tailLines));

  return () => {
    store.dispose();
  };
}
