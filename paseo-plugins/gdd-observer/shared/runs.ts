import { defineRpc } from "@getpaseo/plugin";
import { z } from "zod";

/** Run state as written by the launcher in `state.json`. A missing file is `unknown`, never success. */
export const RUN_STATES = ["running", "done", "killed", "failed", "unknown"] as const;
/** Liveness derived from pids, `lock`, and `finalized`; `settled` means the launcher finalized the run. */
export const RUN_LIVENESS = ["running", "settled", "stale", "unknown"] as const;
export const RUN_ROOT_SOURCES = ["setting", "env", "xdg", "home", "localappdata", "default"] as const;
export const COUNTER_SOURCES = ["state", "events", "none"] as const;
export const LIVENESS_PROBES = ["posix", "win32", "unavailable"] as const;
/** Longest event tail a client may ask for; both tail RPCs and the server-side clamp use it. */
export const MAX_TAIL_LINES = 2000;
/** Machine-readable per-run diagnostics; the client resolves them to text. */
export const RUN_WARNINGS = [
  "state-missing",
  "state-unreadable",
  "no-lock",
  "no-pids",
  "liveness-unknown",
  "log-unreadable",
  "log-truncated",
] as const;

export const runEventSchema = z.object({
  type: z.string(),
  at: z.string().nullable(),
  tool: z.string().nullable(),
  intent: z.string().nullable(),
  detail: z.string().nullable(),
  role: z.string().nullable(),
});

/** One model the run's own event log attributes an assistant message to. */
export const runModelUsageSchema = z.object({
  provider: z.string().nullable(),
  model: z.string().nullable(),
  api: z.string().nullable(),
  /** Assistant messages in the retained log attributed to this model. */
  messages: z.number(),
});

/**
 * Model attribution for one run. `requested` is what the launcher asked for; `observed` is what the
 * run's own assistant events prove it used, in first-seen order. A log that named more than one
 * model says which models were seen, not which one is current, so the client shows the first and
 * lists the rest.
 */
export const runModelSchema = z.object({
  /** Verbatim `model` from `state.json`: `provider/model`, a link such as `@sol_high`, or null when the tool default was left in charge. */
  requested: z.string().nullable(),
  requestedProvider: z.string().nullable(),
  requestedModel: z.string().nullable(),
  /** Verbatim `thinking` from `state.json`; null when the tool default was left in charge. */
  thinking: z.string().nullable(),
  observed: z.array(runModelUsageSchema),
});

export const runStateCountsSchema = z.record(z.enum(RUN_STATES), z.number());
export const runLivenessCountsSchema = z.record(z.enum(RUN_LIVENESS), z.number());

export const runStatsSchema = z.object({
  total: z.number(),
  byState: runStateCountsSchema,
  byLiveness: runLivenessCountsSchema,
  /** Turns, tool calls, and cost summed over the runs that report them. */
  turns: z.number(),
  toolCalls: z.number(),
  costUsd: z.number(),
  /** Runs that report at least one counter; without them the totals say nothing. */
  countedRuns: z.number(),
  /** Runs whose counters cover less than the whole run, so the totals above are a floor. */
  partialRuns: z.number(),
  /** Runs carrying at least one warning. */
  flagged: z.number(),
});

export const runSummarySchema = z.object({
  id: z.string(),
  date: z.string(),
  slug: z.string(),
  runDir: z.string(),
  name: z.string(),
  state: z.enum(RUN_STATES),
  liveness: z.enum(RUN_LIVENESS),
  finalized: z.boolean(),
  exitCode: z.number().nullable(),
  startedAt: z.string().nullable(),
  endedAt: z.string().nullable(),
  durationS: z.number().nullable(),
  elapsedS: z.number().nullable(),
  model: runModelSchema,
  maxTime: z.string().nullable(),
  sessionId: z.string().nullable(),
  turns: z.number().nullable(),
  toolCalls: z.number().nullable(),
  costUsd: z.number().nullable(),
  countersFrom: z.enum(COUNTER_SOURCES),
  countersPartial: z.boolean(),
  currentTool: z.string().nullable(),
  currentToolIntent: z.string().nullable(),
  lastError: z.string().nullable(),
  errorCount: z.number(),
  answerChars: z.number().nullable(),
  hasAnswer: z.boolean(),
  eventsBytes: z.number(),
  eventsDroppedBytes: z.number(),
  eventsTruncated: z.boolean(),
  eventLines: z.number(),
  pids: z.object({ pid: z.number().nullable(), agentPid: z.number().nullable() }),
  livePids: z.array(z.number()),
  lastEventAt: z.string().nullable(),
  dirModifiedAt: z.string().nullable(),
  warnings: z.array(z.enum(RUN_WARNINGS)),
});

export const runPathSchema = z.object({
  label: z.string(),
  path: z.string(),
  exists: z.boolean(),
  bytes: z.number().nullable(),
});

export const eventStatsSchema = z
  .object({
    totalBytes: z.number().nullable(),
    retainedBytes: z.number().nullable(),
    droppedBytes: z.number().nullable(),
    truncated: z.boolean().nullable(),
  })
  .nullable();

export type RunEvent = z.infer<typeof runEventSchema>;
export type RunSummary = z.infer<typeof runSummarySchema>;
export type RunModel = z.infer<typeof runModelSchema>;
export type RunModelUsage = z.infer<typeof runModelUsageSchema>;
export type RunStats = z.infer<typeof runStatsSchema>;
export type RunPath = z.infer<typeof runPathSchema>;
export type EventStats = z.infer<typeof eventStatsSchema>;
export type RunState = (typeof RUN_STATES)[number];
export type RunLiveness = (typeof RUN_LIVENESS)[number];
export type RunWarning = (typeof RUN_WARNINGS)[number];
export type RunRootSource = (typeof RUN_ROOT_SOURCES)[number];

/**
 * The scan facts every list result carries: root resolution, diagnostics, and totals. The runs are
 * versioned separately below, so a delta can restate just these facts plus what changed.
 */
const listRunsSnapshotSchema = z.object({
  runRoot: z.string(),
  rootSource: z.enum(RUN_ROOT_SOURCES),
  rootExists: z.boolean(),
  candidates: z.array(
    z.object({ path: z.string(), source: z.enum(RUN_ROOT_SOURCES), exists: z.boolean() }),
  ),
  probe: z.enum(LIVENESS_PROBES),
  scannedAt: z.string(),
  stats: runStatsSchema,
  warnings: z.array(z.string()),
});

/** A complete population with no revision: the snapshot a surface renders. */
export const listRunsOutputSchema = listRunsSnapshotSchema.extend({
  runs: z.array(runSummarySchema),
});

/**
 * A list result relative to a known revision. `changes` replaces the listed summaries and adds
 * runs that the base revision did not have; `removed` drops run ids; `order` is the complete id
 * sequence of the resulting snapshot and is present only when that sequence changed. A delta
 * without `order` keeps the base order and only restates summaries in place.
 */
export const listRunsDeltaSchema = listRunsSnapshotSchema.extend({
  revision: z.string(),
  changes: z.array(runSummarySchema),
  removed: z.array(z.string()),
  order: z.array(z.string()).optional(),
});

/** A list result that restates the whole population at `revision`. */
export const listRunsFullSchema = listRunsOutputSchema.extend({
  revision: z.string(),
});

/**
 * One versioned list answer. `runs` marks the full variant and a delta never carries it, so the
 * full variant is tried first: any payload that carries `runs` stays a full population even if it
 * also carries delta fields.
 */
export const listRunsUpdateSchema = z.union([listRunsFullSchema, listRunsDeltaSchema]);

export type ListRunsDelta = z.infer<typeof listRunsDeltaSchema>;
export type ListRunsUpdate = z.infer<typeof listRunsUpdateSchema>;

/**
 * The whole run population plus its root diagnostics. The caller sends the revision of the
 * snapshot it already holds (`knownRevision`); the server answers with a delta against that
 * revision while it still describes the current state, and with a full snapshot when the caller
 * names no revision or one the server cannot delta from. The two answers are told apart by `runs`
 * alone: the full variant carries it, the delta variant carries `changes`/`removed` instead.
 */
export const listRuns = defineRpc({
  name: "runs.list",
  input: z.object({
    /** Revision of the snapshot the caller holds; omit to force a full population. */
    knownRevision: z.string().optional(),
  }),
  output: listRunsUpdateSchema,
});

/**
 * The files of one run, for the detail view's path list. The run's own state and events come from
 * `runs.follow`, which the detail view already polls, so this read stays cheap.
 */
export const runPaths = defineRpc({
  name: "runs.paths",
  input: z.object({ id: z.string() }),
  output: z.object({
    found: z.boolean(),
    paths: z.array(runPathSchema),
    scannedAt: z.string(),
  }),
});

export const runLineageSchema = z.object({
  goal: z.string().trim().min(1).max(256),
  stage: z.string().trim().min(1).max(32),
  parentAgentId: z.string().trim().regex(/^[A-Za-z0-9._-]{1,128}$/).optional(),
});

/**
 * Bounded live tail: the run's summary, its last `tailLines` events, and its answer tail. The
 * client polls this while a run is selected; the counters behind the summary reuse a per-run byte
 * offset, so the counting reads only what the launcher appended since the previous call. Revision
 * caches reuse unchanged bounded event/answer windows and extend them on append. Paseo 0.15 has no
 * plugin subscription transport, so polling is the available live channel and it stops the moment
 * the surface unmounts.
 * No `scannedAt`: an unchanged poll must be able to compare equal, and nothing renders it here.
 */
export const followRun = defineRpc({
  name: "runs.follow",
  input: z.object({
    id: z.string(),
    tailLines: z.number().int().min(1).max(MAX_TAIL_LINES).optional(),
  }),
  output: z.object({
    found: z.boolean(),
    summary: runSummarySchema.nullable(),
    lineage: runLineageSchema.optional(),
    events: z.array(runEventSchema),
    answerTail: z.string().nullable(),
  }),
});

export type ListRunsOutput = z.infer<typeof listRunsOutputSchema>;
export type RunPathsOutput = z.infer<typeof runPaths.output>;
export type FollowRunOutput = z.infer<typeof followRun.output>;
