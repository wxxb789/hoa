import { defineSettings } from "@getpaseo/plugin";
import { z } from "zod";

export const observerSettingsSchema = z.object({
  /** Absolute path to the launcher run root. Empty resolves from `GDD_RUN_ROOT`, then the documented defaults. */
  runRoot: z.string().default(""),
  /** Scan interval for the run list, in milliseconds. */
  pollIntervalMs: z.number().int().min(500).max(60000).default(2000),
  /** Event lines kept in the tail view. */
  tailLines: z.number().int().min(10).max(500).default(80),
});

export const observerSettings = defineSettings({
  id: "observer",
  scope: "host",
  version: 1,
  schema: observerSettingsSchema,
});

export type ObserverSettings = z.infer<typeof observerSettingsSchema>;

export const OBSERVER_DEFAULTS: ObserverSettings = observerSettingsSchema.parse({});
