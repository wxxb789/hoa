import { defineSettings } from "@getpaseo/plugin";
import { z } from "zod";

/** The Windows extended-path ceiling in UTF-16 code units; longer values are not usable OS paths. */
const RUN_ROOT_MAX_UNITS = 32767;

export const observerSettingsSchema = z.object({
  /**
   * Absolute path to the launcher run root. Empty resolves from `GDD_RUN_ROOT`, then the documented
   * defaults. Counted on the JS string length because zod's string `.max()` measures code points,
   * which would let a surrogate-heavy value past the UTF-16 ceiling.
   */
  runRoot: z
    .string()
    .refine((value) => value.length <= RUN_ROOT_MAX_UNITS, {
      error: `runRoot must be at most ${RUN_ROOT_MAX_UNITS} UTF-16 code units`,
    })
    .default(""),
  pollIntervalMs: z.number().int().min(500).max(60000).default(2000),
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
