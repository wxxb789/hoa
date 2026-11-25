#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Goal-driven delivery stage dispatcher.

Renders one stage prompt from a template, guards against two writers in one
worktree, records the increment in the delivery ledger, and launches a headless
agent run through a launcher adapter.

Usage:
    gdd.py stage --repo PATH --goal 0041 --stage implement
    gdd.py stage --repo PATH --goal 0041 --stage simplify --dry-run
    gdd.py stage --repo PATH --goal 0041 --stage apply --findings FILE --wait
    gdd.py setup --repo PATH --goal 0041 [--plan-file FILE]
    gdd.py status --repo PATH --goal 0041

Agent stages: implement, simplify, apply, review, fix. Every other stage is
mechanical and belongs to the orchestrator.

Environment or operator config file:
    GDD_STATE_FILE  ledger path passed to delivery-state.py
                    (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/ledger.tsv)
    GDD_TASK_ROOT   prompt/state root
                    (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/tasks)
    GDD_RUN_ROOT    run root exported to the launcher and used when it prints no
                    run dir (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs)
    GDD_LAUNCHER    launcher command (default <script dir>/agent_run.py)
    GDD_AGENT       agent CLI exported to the launcher when set
                    (agent_run.py: an installed route; default omp, claude uses gdd-route-cc)
    GDD_TEMPLATES   template root
                    (default <script dir>/../references/stage-templates)
    GDD_GOAL_GLOB   goal-contract glob (default docs/goals/*<goal>*.md)
    GDD_RUN_PLAN_DEFAULTS
                    JSON defaults `setup` merges under --plan-file
    GDD_MODEL, GDD_THINKING, GDD_MAX_TIME
                    passed to the launcher only when set; never defaulted here

The eight keys above GDD_MODEL resolve through the shared resolver: flag, then environment,
then $XDG_CONFIG_HOME/gdd/config.yaml (fallback ~/.config/...),
then the default. The rule is owned by hoa-skill-port.

Launcher contract (agent_run.py is the bundled implementation):
    <launcher> start --name SLUG --prompt FILE --schema FILE [--cwd DIR] [--model M] [--thinking L]
                     [--max-time D]
    <launcher> list | status SLUG | result SLUG | answer SLUG | kill SLUG

The launcher owns <run_root>/<date>/<SLUG>/state.json with at least
{"name","state","exit","cwd","started","ended","duration_s"} (state is one of
running|done|killed|failed|unknown) and answer.md holding the final assistant text.
--schema is references/stage-result.schema.json; a launcher that checks the answer against
it records state.result (valid|invalid|missing) and writes result.json when valid.
This tool polls that file and treats a missing file as unknown, never success; a
`running` run whose recorded runner and agent pids are both gone reads as `stale`; a
launcher that records neither `pid` nor `agent_pid` is trusted as recorded.
Native Paseo runs reserve their worktree while running or unknown, regardless
of local monitor liveness, until a terminal state or finalized marker is recorded.

Each successful launch also writes a best-effort lineage sidecar, `lineage.json`
inside the run directory: the goal and stage of this dispatch plus, when the
dispatcher inherited one, `parentAgentId` from `PASEO_AGENT_ID`. A sidecar failure
warns on stderr and never affects the run or the ledger.
"""

import argparse
import glob
import json
import math
import os
import re
import secrets
import shlex
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from subprocess import CalledProcessError

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
sys.dont_write_bytecode = True  # no __pycache__ inside an installed skill
import agent_run
import gdd_process
import skill_config
import stage_result

STAGES = [
    "setup",
    "contract",
    "implement",
    "verify",
    "simplify",
    "apply",
    "review",
    "fix",
    "gates",
    "pr",
    "babysit",
    "merge",
    "done",
    "blocked",
]
AGENT_STAGES = {"implement", "simplify", "apply", "review", "fix"}
NEEDS_FINDINGS = {"apply", "fix"}

SKILL = "gdd"
DEFAULT_GOAL_GLOB = "docs/goals/*<goal>*.md"
DELIVERY_STATE = os.path.join(SCRIPT_DIR, "delivery-state.py")
DEFAULT_LAUNCHER = os.path.join(SCRIPT_DIR, "agent_run.py")
DEFAULT_TEMPLATES = os.path.normpath(
    os.path.join(SCRIPT_DIR, "..", "references", "stage-templates")
)


def fail(message, code=2):
    print(f"gdd: {message}", file=sys.stderr)
    sys.exit(code)


class LaunchError(Exception):
    """The launcher could not start the run; the ledger must not claim otherwise."""


class LedgerError(Exception):
    pass


class CommitRefusal(Exception):
    def __init__(self, code, detail, exit_code=3):
        super().__init__(detail)
        self.code = code
        self.exit_code = exit_code


def xdg_state_home():
    return os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )


def config(key, *, flag=None, default=None):
    """Resolve one documented GDD key through the shared resolver."""
    return skill_config.resolve(SKILL, key, flag=flag, default=default)


def configured_gates():
    try:
        gates = json.loads(config("GDD_GATES", default="[]"))
        if not isinstance(gates, list) or not all(isinstance(gate, str) and gate.strip() for gate in gates):
            raise ValueError("expected an array of non-empty command strings")
    except ValueError as exc:
        raise ValueError(f"GDD_GATES: {exc}") from exc
    return gates


def state_file():
    return config(
        "GDD_STATE_FILE", default=os.path.join(xdg_state_home(), "gdd", "ledger.tsv")
    )


def task_root():
    return os.path.expanduser(
        config("GDD_TASK_ROOT", default=os.path.join(xdg_state_home(), "gdd", "tasks"))
    )


def run_root():
    return os.path.expanduser(
        config("GDD_RUN_ROOT", default=os.path.join(xdg_state_home(), "gdd", "runs"))
    )


def git(repo, *args):
    proc = gdd_process.run(
        ["git", "-C", repo, *args], capture_output=True, text=True
    )
    if proc.returncode != 0:
        reason = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        fail(f"git {' '.join(args)} failed: {reason.splitlines()[0]}")
    return proc.stdout.strip()


def git_inventory(repo):
    data = gdd_process.run(
        ["git", "-C", repo, "status", "--porcelain=v1", "-z", "-uall", "--no-renames"],
        capture_output=True, check=True,
    ).stdout.decode("utf-8")
    return [(entry[:2], entry[3:]) for entry in data.split("\0") if entry]


def pending_paths(inventory, excluded=()):
    return {path for _, path in inventory} - set(excluded)


def process_detail(proc):
    detail = proc.stderr or proc.stdout
    if isinstance(detail, bytes):
        detail = detail.decode("utf-8", "replace")
    return (detail or f"exit {proc.returncode}").strip()


def scope_run(tool, repo, goal, verb, *options):
    return gdd_process.run(
        [agent_run.interpreter(), tool, verb, "--repo", repo, "--label", goal, "--json", *options],
        capture_output=True, text=True,
    )


def scope_baseline(tool, repo, goal):
    proc = scope_run(tool, repo, goal, "status")
    if proc.returncode == 2 and proc.stderr.startswith("worktree-scope: no state for "):
        return None
    proc.check_returncode()
    return json.loads(proc.stdout)["baseline"] or None


def validate_stage(stage):
    if stage not in STAGES:
        fail(f"invalid stage {stage!r}; expected one of: {', '.join(STAGES)}")
    if stage not in AGENT_STAGES:
        fail(
            f"stage {stage!r} is mechanical and belongs to the orchestrator, "
            f"not the agent (agent stages: {', '.join(sorted(AGENT_STAGES))})"
        )


def render(template_text, variables):
    text = template_text
    for key, value in variables.items():
        text = text.replace("${" + key + "}", str(value))
    unresolved = sorted(set(re.findall(r"\$\{([^}]+)\}", text)))
    if unresolved:
        fail("unresolved placeholders: " + ", ".join(unresolved))
    return text


def resolve_ref(repo, value):
    """Full SHA for a supplied endpoint; the value unchanged when git cannot resolve it."""
    if not value:
        return value
    proc = gdd_process.run(
        ["git", "-C", repo, "rev-parse", "--verify", "--quiet", str(value)],
        capture_output=True,
        text=True,
    )
    resolved = (proc.stdout or "").strip()
    return resolved if proc.returncode == 0 and resolved else value


def resolve_goal_file(repo, goal):
    """Contract file for a goal from GDD_GOAL_GLOB; '-' when nothing matches."""
    pattern = config("GDD_GOAL_GLOB", default=DEFAULT_GOAL_GLOB)
    expanded = os.path.expanduser(pattern.replace("<goal>", goal))
    matches = sorted(glob.glob(os.path.join(repo, expanded)))
    if not matches and pattern == DEFAULT_GOAL_GLOB:
        archive = os.path.join(
            "docs", "goals", "archive", os.path.basename(expanded)
        )
        matches = sorted(glob.glob(os.path.join(repo, archive)))
    return matches[0] if matches else "-"


def active_runs(repo_path):
    """(name, run_dir) for runs reserving repo_path, including unresolved native runs."""
    active = []
    for state_path in glob.glob(os.path.join(run_root(), "*", "*", "state.json")):
        run_dir = os.path.dirname(state_path)
        state = agent_run.read_state(run_dir)
        if state.get("backend") == "paseo":
            # The daemon owns execution; a dead/offline monitor cannot release its worktree.
            if (state.get("state") not in ("running", "unknown") or
                    os.path.exists(os.path.join(run_dir, "finalized"))):
                continue
        elif agent_run.observed_state(run_dir, state) != "running":
            continue
        cwd = state.get("cwd")
        if not cwd:
            continue
        if os.path.realpath(os.path.expanduser(cwd)) != repo_path:
            continue
        name = state.get("name") or os.path.basename(run_dir)
        active.append((name, run_dir))
    return active


NOT_READY_STATES = ("provisional", "superseded", "completed", "draft")
DIFF_STAGES = ("simplify", "apply", "review", "fix")


def goal_state_header(goal_file):
    """(state, status) words from the first 15 lines of a contract file."""
    try:
        with open(goal_file, encoding="utf-8", errors="replace") as handle:
            head_text = "".join(handle.readline() for _ in range(15))
    except OSError:
        return ""
    found = re.search(
        r"(?im)^[\s*#]*(?:state|status)[\s*]*:[*\s]*([a-z]+)", head_text
    )
    return found.group(1).lower() if found else ""


def dispatch_problems(stage, goal_file, goal_state, dirty_paths, base, head, has_baseline, force=False):
    """Why this dispatch must not start. Pure: the caller supplies the facts."""
    if force:
        return []
    problems = []
    if stage == "implement":
        if goal_file in ("", "-"):
            problems.append(
                "no goal contract found — pass --goal that matches GDD_GOAL_GLOB, "
                "or write the contract first (phase 0)"
            )
        elif "/archive/" in goal_file.replace("\\", "/"):
            problems.append(
                f"contract {goal_file} is archived — an increment starts from an active goal"
            )
        elif goal_state in NOT_READY_STATES:
            problems.append(
                f"contract {goal_file} declares state {goal_state!r}; refine and activate it "
                "in its own commit before implementing"
            )
    if stage in ("implement", *DIFF_STAGES) and dirty_paths:
        hint = "commit stage output first with gdd.py commit --no-push"
        if not has_baseline:
            hint = ("review the dirt and run worktree-scope.py snapshot --label <goal> explicitly"
                    if stage == "implement" else "resolve the dirt before dispatching without a baseline")
        problems.append(f"worktree is dirty before {stage}: {', '.join(dirty_paths)} — {hint}")
    if stage in DIFF_STAGES and base and head and base == head:
        problems.append(
            f"base == head ({head[:7]}): there is no committed range to read — commit the "
            "stage output first (phase 4) or pass --base/--head explicitly"
        )
    return problems


AUTHORING_STAGES = ("implement", "apply", "fix")


def final_head_for(stage, head_supplied, head, post_head):
    """The SHA a finished-stage row should record.

    An authoring stage changed the tree, so the post-run HEAD is the increment. A report-only
    stage (review, simplify) reviewed the head it was given: when the operator supplied one, the
    checkout may have moved on and the supplied SHA is the fact worth keeping.
    """
    if head_supplied:
        return head
    if stage in AUTHORING_STAGES:
        return post_head
    return head


STAGE_BUDGETS = {"implement": 2, "simplify": 2, "review": 2}
RUN_PLAN_ROLE_FIELDS = ("agent", "model", "thinking", "max_time")
LEDGER_COLUMNS = (
    "ts repo goal stage base_sha head_sha pr gates rounds_simplify rounds_review "
    "findings next_action note"
).split()


def budget_problem(stage, rounds, cap, over_budget=False):
    """The message that refuses one dispatch too many, or None."""
    if over_budget or not cap or rounds < cap:
        return None
    return (
        f"{stage} has already run {rounds}x for this goal (cap {cap}) — read the ledger, "
        "decide what changes the outcome, and pass --over-budget only if it does"
    )


def non_negative_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def run_usage(state):
    """The launcher's normalized token count, or None when it reports none.

    `total_tokens` when the launcher records it; otherwise input + output only.
    Cache reads are never added: some routes count them inside the total. An
    all-zero accumulator is the bundled launcher's no-usage placeholder and is
    unknown, never an explicit zero: no state field records a usage event.
    """
    usage = state.get("usage") if isinstance(state.get("usage"), dict) else {}
    total = usage.get("total_tokens")
    if total is not None:
        return total if non_negative_int(total) and total > 0 else None
    parts = []
    for key in ("input_tokens", "output_tokens"):
        value = usage.get(key)
        if not non_negative_int(value):
            return None
        parts.append(value)
    total = sum(parts)
    return total if total > 0 else None


def path_segment_problem(value):
    """Why `value` cannot stand as one portable path segment, or None."""
    if not isinstance(value, str) or not value.strip():
        return "is empty"
    if "/" in value or "\\" in value:
        return "contains a path separator"
    if os.path.splitdrive(value)[0]:
        return "contains a drive prefix"
    if value in (".", ".."):
        return "is a relative path component"
    return None


DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)([smh]?)")
DURATION_SCALES = {"": 1, "s": 1, "m": 60, "h": 3600}


def duration_seconds(value):
    """Positive finite seconds for a plan duration, or None when the launcher would reject it.

    Mirrors agent_run.max_time_seconds, which exits the launcher on invalid input, so setup
    cannot reuse it. A string keeps the launcher's grammar and is forwarded verbatim; a number is
    checked in the plain decimal form `forwarded_duration` sends.
    """
    value = forwarded_duration(value)
    if value is None:
        return None
    match = DURATION_RE.fullmatch(value.strip())
    if not match:
        return None
    try:
        seconds = float(match.group(1)) * DURATION_SCALES[match.group(2)]
    except (OverflowError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def forwarded_duration(value):
    """The string a plan duration reaches the launcher as, or None for a non-duration type.

    Numbers use plain decimal notation: `str(0.00001)` is `1e-05`, which the launcher rejects.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return format(value, "f").rstrip("0").rstrip(".") or "0"
    return value if isinstance(value, str) else None


def plan_path_problem(repo_name, goal):
    """Why this repo+goal cannot name a plan path, or None when it can."""
    for value, label in ((repo_name, "repo"), (goal, "goal")):
        if problem := path_segment_problem(value):
            return f"run plan: {label} {value!r} {problem}"
    root = os.path.realpath(task_root())
    directory = os.path.join(root, f"{repo_name}-{goal}")
    resolved = os.path.realpath(directory)
    if resolved != directory and not resolved.startswith(root + os.sep):
        return f"run plan directory {directory} resolves outside the task root {root}"
    return None


def run_plan_path(repo_name, goal):
    """The goal's plan file under the resolved task root; refuse a segment or link escape."""
    if problem := plan_path_problem(repo_name, goal):
        fail(problem)
    return os.path.join(os.path.realpath(task_root()), f"{repo_name}-{goal}", "run-plan.json")


def plan_problem(plan):
    """The validation message for a run plan, or None when it is well-formed."""
    if not isinstance(plan, dict):
        return "run plan: top level must be a JSON object"
    for key in plan:
        if key not in ("roles", "budgets", "notes"):
            return f"run plan: unknown key '{key}'"
    roles = plan.get("roles", {})
    if not isinstance(roles, dict):
        return "run plan: 'roles' must be an object"
    for stage, role in roles.items():
        if stage not in AGENT_STAGES:
            return f"run plan: unknown role 'roles.{stage}'"
        if not isinstance(role, dict):
            return f"run plan: 'roles.{stage}' must be an object"
        for field, value in role.items():
            if field not in RUN_PLAN_ROLE_FIELDS:
                return f"run plan: unknown field 'roles.{stage}.{field}'"
            if not isinstance(value, str) or not value.strip():
                return f"run plan: 'roles.{stage}.{field}' must be a non-empty string"
            if field == "max_time" and duration_seconds(value) is None:
                return (f"run plan: 'roles.{stage}.max_time' must be a positive duration "
                        "like 30m")
            if field in ("agent", "model", "thinking") and (
                    re.search(r"\s", value) or "=" in value):
                return (f"run plan: 'roles.{stage}.{field}' must not contain whitespace "
                        "or '='")
    budgets = plan.get("budgets", {})
    if not isinstance(budgets, dict):
        return "run plan: 'budgets' must be an object"
    for key in budgets:
        if key not in ("rounds", "max_time", "token_cap"):
            return f"run plan: unknown key 'budgets.{key}'"
    rounds = budgets.get("rounds", {})
    if not isinstance(rounds, dict):
        return "run plan: 'budgets.rounds' must be an object"
    for stage, cap in rounds.items():
        if stage not in AGENT_STAGES:
            return f"run plan: unknown stage 'budgets.rounds.{stage}'"
        if cap is None:
            continue  # null means the default cap
        if not (isinstance(cap, int) and not isinstance(cap, bool) and cap > 0):
            return f"run plan: 'budgets.rounds.{stage}' must be a positive integer or null"
    for key in ("max_time", "token_cap"):
        if key not in budgets:
            continue
        value = budgets[key]
        if key == "token_cap":
            if value is None or non_negative_int(value):
                continue
            return "run plan: 'budgets.token_cap' must be a non-negative integer or null"
        if duration_seconds(value) is None:
            return "run plan: 'budgets.max_time' must be a positive duration like 30m"
    notes = plan.get("notes", [])
    if not isinstance(notes, list):
        return "run plan: 'notes' must be a list of strings"
    for index, note in enumerate(notes):
        if not isinstance(note, str):
            return f"run plan: 'notes[{index}]' must be a string"
    return None


def merge_plans(defaults, override):
    """The plan file wins field by field over the defaults file; notes are replaced whole."""
    merged = {}
    roles = {stage: dict(role) for stage, role in (defaults.get("roles") or {}).items()}
    for stage, role in (override.get("roles") or {}).items():
        roles[stage] = {**(roles.get(stage) or {}), **role}
    if roles:
        merged["roles"] = roles
    default_budgets = defaults.get("budgets") or {}
    override_budgets = override.get("budgets") or {}
    budgets = {}
    rounds = {**(default_budgets.get("rounds") or {}), **(override_budgets.get("rounds") or {})}
    if rounds:
        budgets["rounds"] = rounds
    for key in ("max_time", "token_cap"):
        if key in override_budgets:
            budgets[key] = override_budgets[key]
        elif key in default_budgets:
            budgets[key] = default_budgets[key]
    if budgets:
        merged["budgets"] = budgets
    if "notes" in override:
        merged["notes"] = override["notes"]
    elif "notes" in defaults:
        merged["notes"] = defaults["notes"]
    return merged


def read_plan_source(path, label):
    """Load and validate one JSON plan source; fail naming the file and the offending key."""
    expanded = os.path.expanduser(path)
    try:
        with open(expanded, encoding="utf-8") as handle:
            plan = json.load(handle)
    except OSError as exc:
        fail(f"{label}: cannot read {expanded}: {exc}")
    except ValueError as exc:
        fail(f"{label}: invalid JSON in {expanded}: {exc}")
    problem = plan_problem(plan)
    if problem:
        fail(f"{problem} (in {expanded})")
    return plan


def read_run_plan(repo_name, goal):
    """The validated plan for one repo+goal; None when setup has not run or the selector is legacy.

    A selector that cannot name a plan path (or whose directory redirects outside the task root)
    is treated as "no plan": plan lookup must not change the failure text, exit status or bytes
    of a command origin/main accepted. `setup` still refuses such a selector before writing.
    """
    if plan_path_problem(repo_name, goal):
        return None
    path = run_plan_path(repo_name, goal)
    if not os.path.exists(path):
        return None
    return read_plan_source(path, "run plan")


def write_run_plan(path, plan):
    """Replace the plan atomically: a temp sibling keeps an interrupted write from truncating it."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".run-plan.json.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(plan, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def resolve_field(flag, plan_value, env_value):
    """One field's resolution: explicit flag, then the run plan, then the environment."""
    if flag is not None:
        return flag
    if plan_value:
        return plan_value
    return env_value


def ledger_rows(state_path, repo_name, goal, *, exact=False):
    """(stage, note) for this repo+goal's ledger rows, oldest first.

    A plan-governed reader matches the canonical repo key exactly; without a plan the
    legacy substring match is kept.
    """
    try:
        with open(os.path.expanduser(state_path), encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return []
    if not lines:
        return []
    header = lines[0].split("\t")
    try:
        i_repo = header.index("repo")
        i_goal = header.index("goal")
        i_stage = header.index("stage")
    except ValueError:
        return []
    i_note = header.index("note") if "note" in header else None
    rows = []
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) <= max(i_repo, i_goal, i_stage):
            continue
        if cells[i_goal] != goal:
            continue
        if repo_name:
            same_repo = cells[i_repo] == repo_name if exact else repo_name in cells[i_repo]
            if not same_repo:
                continue
        note = cells[i_note] if i_note is not None and len(cells) > i_note else ""
        rows.append((cells[i_stage], note))
    return rows


def ledger_rounds(state_path, repo_name, goal, stage, *, exact=False):
    """How many runs of this stage the ledger already records for this repo+goal."""
    # `--wait` writes a dispatch row and then a completion row for the same stage (its note
    # starts with `exit=`). The cap counts dispatches, so a completion must not spend a round.
    return sum(
        1 for row_stage, note in ledger_rows(state_path, repo_name, goal, exact=exact)
        if row_stage == stage and not note.startswith("exit=")
    )


RUN_NOTE_RE = re.compile(r"^run=(\S+)$")

# agent_run.observed_state() may also answer "stale" for a dead `running` run; a stale attempt
# is terminal for accounting.
TERMINAL_RUN_STATES = tuple(
    name for name in agent_run.STATES if name != "running"
) + ("stale",)


def dispatch_run_name(note):
    """The run name a dispatch row records, or None for a legacy row."""
    match = RUN_NOTE_RE.match(note.strip())
    return match.group(1) if match else None


def run_state_for(run_name):
    """(state, run_dir) for one recorded run name; ({}, None) when it is missing or ambiguous.

    A plan-governed dispatch names its run `<repo>-<goal>-<stage>-a<n>`, so the name
    identifies exactly one `<run_root>/<date>/<run_name>/state.json`; zero or several
    matches stay unknown instead of a newest-mtime guess.
    """
    if not run_name or path_segment_problem(run_name):
        return {}, None
    try:
        matches = glob.glob(os.path.join(run_root(), "*", glob.escape(run_name), "state.json"))
    except (OSError, ValueError):
        return {}, None
    if len(matches) != 1:
        return {}, None
    run_dir = os.path.dirname(matches[0])
    return agent_run.read_state(run_dir), run_dir


def accounted_usage(state_path, repo_name, goal, stage=None, *, exact=True):
    """(tokens known from launcher state, unknown attempts) over agent dispatch rows.

    Reading is best effort: a running, missing or malformed run state is unknown and is
    never summed, and accounting never fails the stage.
    """
    known = unknown = 0
    for row_stage, note in ledger_rows(state_path, repo_name, goal, exact=exact):
        if row_stage not in AGENT_STAGES or note.startswith("exit="):
            continue
        if stage is not None and row_stage != stage:
            continue
        value = None
        try:
            state, run_dir = run_state_for(dispatch_run_name(note))
            if state and agent_run.observed_state(run_dir, state) in TERMINAL_RUN_STATES:
                value = run_usage(state)
        except (OSError, ValueError, TypeError):
            value = None
        if value is None:
            unknown += 1
        else:
            known += value
    return known, unknown


def ledger_append(repo, goal, stage, base, head, gates, next_stage=None, note=None, pr=None, rounds=None):
    cmd = [
        agent_run.interpreter(),
        DELIVERY_STATE,
        "append",
        "--repo",
        repo,
    ]
    state = state_file()
    if state:
        cmd += ["--state-file", os.path.expanduser(state)]
    cmd += [
        "--goal",
        goal,
        "--stage",
        stage,
        "--base",
        base,
        "--head",
        head,
    ]
    if pr:
        cmd += ["--pr", str(pr)]
    if rounds and stage in ("simplify", "review"):
        cmd += ["--rounds-simplify" if stage == "simplify" else "--rounds-review", str(rounds)]
    if gates and gates != "-":
        cmd += ["--gates", gates]
    if next_stage:
        cmd += ["--next", next_stage]
    if note:
        cmd += ["--note", note]
    proc = gdd_process.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        reason = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise LedgerError(f"ledger append failed: {reason}")


def launcher_command(launcher):
    """Run Python launchers without relying on a shebang or executable bit."""
    path = os.path.expanduser(launcher)
    if path.lower().endswith(".py"):
        return [agent_run.interpreter(), path]
    if os.name == "nt" and path.lower().endswith((".cmd", ".bat")):
        return agent_run.command_prefix(path)
    return [path]


LINEAGE_FILE = "lineage.json"


def _lineage_text(value, limit, label):
    """Trim one lineage string and hold it to the TypeScript field bounds.

    The observer validates in TypeScript, where `.length` counts UTF-16 units and
    an astral character is two of them; checking the UTF-16 length as well keeps
    values this writer accepts acceptable to that reader.
    """
    if not isinstance(value, str):
        raise ValueError(f"{label} is not a string")
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(f"{label} is empty")
    if len(trimmed) > limit:
        raise ValueError(f"{label} is longer than {limit} codepoints")
    if len(trimmed.encode("utf-16-le")) // 2 > limit:
        raise ValueError(f"{label} is wider than {limit} UTF-16 units")
    return trimmed


def lineage_payload(goal, stage):
    """The lineage object for one launched run: the dispatch's own goal and stage.

    `parentAgentId` is read from the `PASEO_AGENT_ID` this process inherited — the
    launcher's initiating environment, before any adapter strips it for its own
    child. It is never derived from the run's own name, and a missing or malformed
    value stays absent rather than being guessed.
    """
    payload = {
        "goal": _lineage_text(goal, 256, "goal"),
        "stage": _lineage_text(stage, 32, "stage"),
    }
    parent = os.environ.get("PASEO_AGENT_ID", "").strip()
    if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", parent):
        payload["parentAgentId"] = parent
    return payload


def resolve_lineage_dir(run_root, run_name, run_dir):
    """The run directory when it is exactly `<run_root>/<date>/<run_name>`.

    Both sides resolve symlinks before the comparison: a run root reached through
    a link still matches its real path, while a run directory whose link points
    outside the root stops containing it. Anything else — outside the root, other
    depths, a different name than the launcher printed, a missing directory —
    raises, so nothing is created and nothing is written outside the root.
    """
    root = Path(os.path.expanduser(run_root)).resolve()
    target = Path(os.path.expanduser(run_dir)).resolve()
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise ValueError(f"run dir {target} is outside GDD_RUN_ROOT {root}") from None
    parts = relative.parts
    if (
        len(parts) != 2
        or parts[1] != run_name
        or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", parts[0])
    ):
        raise ValueError(f"run dir {target} is not <GDD_RUN_ROOT>/<date>/{run_name}")
    if not target.is_dir():
        raise ValueError(f"run dir does not exist: {target}")
    return target


def write_lineage_sidecar(run_root, run_name, run_dir, goal, stage):
    """Write lineage.json inside the run directory, best effort only.

    The run has already started when this is called, so no failure here may fail
    the dispatch: an invalid value or unusable directory warns on stderr and
    leaves the launcher's state, the ledger and the reported launch success
    untouched. The file is replaced atomically through a temporary file in the
    same directory, so a reader never sees a partial object.
    """
    try:
        payload = lineage_payload(goal, stage)
        target = resolve_lineage_dir(run_root, run_name, run_dir)
        fd, temp_path = tempfile.mkstemp(
            dir=str(target), prefix="." + LINEAGE_FILE + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            os.replace(temp_path, str(target / LINEAGE_FILE))
        except BaseException:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise
    except Exception as exc:
        reason = str(exc).strip() or exc.__class__.__name__
        print(f"gdd: warning: lineage sidecar not written: {reason}", file=sys.stderr)


RUN_NAME_LIMIT = len(agent_run.sanitize("x" * 4096))


def plan_run_name(repo_name, goal, stage, attempt, ident):
    """A plan-governed run name whose `-<goal>-<stage>-a<n>-<id>` tail survives the launcher's sanitize.

    The launcher lowercases, substitutes and truncates the requested slug itself, so only the
    repo part is shortened here, using the launcher's own limit; the goal stays whole because
    `delivery-state.py show` finds a goal's runs by name. The result is verified through the
    same function.
    """
    suffix = f"-a{attempt}-{ident}"
    tail = "-" + agent_run.sanitize(f"{goal}-{stage}").strip("-") + suffix
    keep = RUN_NAME_LIMIT - len(tail)
    repo_part = agent_run.sanitize(repo_name).strip("-")[:max(keep, 0)].rstrip("-")
    name = (repo_part or "run") + tail
    final = agent_run.sanitize(name)
    if not final.endswith(suffix):
        raise LaunchError(f"launcher sanitize would drop the attempt suffix from {name!r}")
    return final


def unused_plan_run_name(root, repo_name, goal, stage, attempt, new_id=None):
    """A plan run name no retained run dir under `root` uses, live or archived.

    The random id alone can repeat, and a ledger reset reuses attempt numbers, so the
    name is checked against every date directory before it is handed out.
    """
    new_id = new_id or (lambda: secrets.token_hex(3))
    while True:
        name = plan_run_name(repo_name, goal, stage, attempt, new_id())
        if not glob.glob(os.path.join(glob.escape(root), "*", glob.escape(name) + "*")):
            return name


def launch(launcher, prompt_path, repo, goal, stage, agent, model, thinking, max_time,
           attempt=None):
    name = f"{os.path.basename(repo)}-{goal}-{stage}"
    if attempt is not None:
        # A plan-governed re-dispatch must not alias the previous attempt's run dir.
        name = unused_plan_run_name(run_root(), os.path.basename(repo), goal, stage, attempt)
    resolved_run_root = run_root()
    prefix = launcher_command(launcher)
    cmd = [
        *prefix,
        "start",
        "--name",
        name,
        "--prompt",
        prompt_path,
        "--cwd",
        repo,
        "--schema",
        stage_result.SCHEMA,
    ]
    for flag, value in (
        ("--model", model),
        ("--thinking", thinking),
        ("--max-time", max_time),
    ):
        if value:
            cmd += [flag, str(value)]
    # The final vector is what a Windows .cmd shim receives through cmd.exe; guard it after
    # every plan/flag/env value is in, immediately before the spawn.
    if prefix[1:2] == ["/c"] and (problem := agent_run.shim_hazard(prefix[-1], cmd[len(prefix):])):
        raise LaunchError(f"{problem}; configure a native executable or Python launcher")
    # The launcher resolves its run root and agent from GDD_RUN_ROOT / GDD_AGENT; export
    # what this process resolved so a config-file value reaches it too.
    child_env = dict(os.environ)
    child_env["GDD_RUN_ROOT"] = resolved_run_root
    child_env["PYTHONIOENCODING"] = "utf-8"
    if agent:
        child_env["GDD_AGENT"] = agent
    try:
        proc = gdd_process.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
        )
    except OSError as exc:
        raise LaunchError(str(exc)) from exc
    if proc.returncode != 0:
        reason = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise LaunchError(reason or f"exit {proc.returncode}")
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    run_name = name
    run_dir = None
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("started:"):
            run_name = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("run dir"):
            run_dir = stripped.split(":", 1)[1].strip()
    if not run_dir:
        run_dir = os.path.join(
            resolved_run_root, datetime.now().strftime("%Y-%m-%d"), run_name
        )
    write_lineage_sidecar(resolved_run_root, run_name, run_dir, goal, stage)
    return run_name, run_dir, resolved_run_root


def print_answer_head(run_dir, limit=40):
    path = os.path.join(run_dir, "answer.md")
    print(f"answer: {path}")
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= limit:
                    break
                print(line.rstrip("\n"))
    except OSError as exc:
        print(f"answer: unknown ({exc})")


def cmd_stage(args):
    validate_stage(args.stage)
    if args.stage in NEEDS_FINDINGS:
        if not args.findings:
            fail("--findings is required for stage " + args.stage)
        if not os.path.isfile(args.findings):
            fail(f"--findings file does not exist: {args.findings}")
    elif args.findings and not os.path.isfile(args.findings):
        fail(f"--findings file does not exist: {args.findings}")

    if not os.path.isdir(args.repo):
        fail(f"--repo is not a directory: {args.repo}")
    repo = os.path.realpath(git(args.repo, "rev-parse", "--show-toplevel"))
    repo_name = repo_key(args.repo)
    plan = read_run_plan(repo_name, args.goal)
    role = ((plan or {}).get("roles") or {}).get(args.stage) or {}

    templates = os.path.expanduser(
        config("GDD_TEMPLATES", flag=args.templates, default=DEFAULT_TEMPLATES)
    )
    launcher = os.path.expanduser(
        config("GDD_LAUNCHER", flag=args.launcher, default=DEFAULT_LAUNCHER)
    )
    template_path = os.path.join(templates, args.stage + ".md")
    if not os.path.isfile(template_path):
        fail(f"template not found: {template_path}")
    with open(template_path, encoding="utf-8") as handle:
        template_text = handle.read()

    goal_file = resolve_goal_file(repo, args.goal)

    if args.base:
        base = args.base
    else:
        base = git(repo, "merge-base", "origin/main", "HEAD")

    if args.head:
        head = args.head
    else:
        head = git(repo, "rev-parse", "HEAD")
    # Resolve supplied endpoints to commit SHAs: `--base <sha> --head HEAD` names one commit
    # twice, and a string compare would call that a non-empty range. A value git cannot resolve
    # is kept literally, so a caller may pass a SHA from another checkout.
    base = resolve_ref(repo, base)
    head = resolve_ref(repo, head)

    # `GDD_DISPATCH_GUARDS=off` exists for harness fixtures that dispatch synthetic
    # goals on purpose; a real run leaves it unset.
    guard_off = os.environ.get("GDD_DISPATCH_GUARDS", "on").lower() in (
        "off",
        "0",
        "false",
        "no",
    )
    snapshot_tool = None
    problems = []
    if not guard_off and args.stage in ("implement", *DIFF_STAGES):
        inventory = git_inventory(repo)
        dirty = pending_paths(inventory)
        baseline = None
        if inventory or args.stage == "implement":
            tool = scope_tool()
            baseline = scope_baseline(tool, repo, args.goal)
            if baseline and inventory:
                diff = scope_run(tool, repo, args.goal, "diff")
                diff.check_returncode()
                dirty = pending_paths(inventory, json.loads(diff.stdout)["excluded_preexisting_paths"])
            elif args.stage == "implement" and not baseline and not inventory:
                snapshot_tool = tool
        problems = dispatch_problems(
            args.stage, goal_file, goal_state_header(goal_file), sorted(dirty), base, head,
            bool(baseline), force=args.force,
        )
    if problems:
        for problem in problems:
            print(f"gdd: {problem}", file=sys.stderr)
        print("gdd: dispatch refused (use --force to override)", file=sys.stderr)
        return 3

    rounds_state = os.path.expanduser(state_file())
    # A plan governs accounting with the exact repo key; without one, keep the legacy match.
    rounds_seen = ledger_rounds(rounds_state, repo_name, args.goal, args.stage,
                                exact=plan is not None)
    budgets = (plan or {}).get("budgets") or {}
    cap = budgets.get("rounds", {}).get(args.stage)
    if cap is None:
        cap = STAGE_BUDGETS.get(args.stage)
    budget_message = budget_problem(
        args.stage, rounds_seen, cap, over_budget=args.over_budget
    )
    if budget_message:
        print(f"gdd: {budget_message}", file=sys.stderr)
        return 3

    token_cap = budgets.get("token_cap")
    if token_cap is not None and not args.over_budget:
        used, unknown = accounted_usage(rounds_state, repo_name, args.goal, exact=True)
        if used >= token_cap:
            print(
                f"gdd: {args.stage}: goal {args.goal} token cap {token_cap} reached "
                f"({used} used, {unknown} unknown) — pass --over-budget only if a "
                "different attempt is worth the tokens",
                file=sys.stderr,
            )
            return 3

    gates = args.gates
    if not gates:
        legacy = os.environ.get("GDD_GATES", "").strip()
        gates = legacy if legacy and not legacy.startswith("[") else "\n".join(configured_gates()) or "-"
    findings = os.path.abspath(os.path.expanduser(args.findings)) if args.findings else "-"

    variables = {
        "REPO_PATH": repo,
        "REPO_NAME": repo_name,
        "GOAL": args.goal,
        "GOAL_FILE": goal_file,
        "BASE_SHA": base,
        "HEAD_SHA": head,
        "GATES": gates,
        "FINDINGS_FILE": findings,
        "DATE": datetime.now().strftime("%Y-%m-%d"),
        "RESULT_SCHEMA": stage_result.SCHEMA,
    }
    rendered = render(template_text, variables)
    notes = (plan or {}).get("notes") or []

    stamp = datetime.now().strftime("%H%M%S")
    prompt_dir = os.path.join(
        task_root(),
        datetime.now().strftime("%Y-%m-%d"),
        f"{repo_name}-{args.goal}",
        "prompts",
    )
    prompt_path = os.path.join(prompt_dir, f"{args.stage}-{stamp}.md")
    counter = 2
    while os.path.exists(prompt_path):
        prompt_path = os.path.join(prompt_dir, f"{args.stage}-{stamp}-{counter}.md")
        counter += 1
    os.makedirs(prompt_dir, exist_ok=True)
    with open(prompt_path, "w", encoding="utf-8") as handle:
        handle.write(rendered.rstrip("\n") if notes else rendered)
    if notes:
        # The notes suffix is written without newline translation, so a CRLF inside one
        # note reaches the prompt byte for byte.
        with open(prompt_path, "a", encoding="utf-8", newline="") as handle:
            handle.write(
                "\n\n## Owner notes (run plan)\n\n"
                + "\n".join(f"- {note}" for note in notes)
                + "\n"
            )
    print(f"prompt: {prompt_path}")

    running = [] if args.dry_run else active_runs(repo)
    if running and not args.force:
        names = ", ".join(name for name, _ in running)
        fail(
            f"refusing to start: run(s) still active in {repo}: {names} "
            f"(use --force to override)",
            3,
        )

    if snapshot_tool and args.dry_run:
        print("scope snapshot: would record a clean baseline before launching")
    elif snapshot_tool:
        if git_inventory(repo):
            fail("worktree changed before the automatic snapshot; review the dirt and run snapshot explicitly", 3)
        snapshot = scope_run(snapshot_tool, repo, args.goal, "snapshot")
        snapshot.check_returncode()
        print(f"scope snapshot: {json.loads(snapshot.stdout)['state_file']}")

    if args.dry_run:
        print("----- first 5 lines -----")
        with open(prompt_path, encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index >= 5:
                    break
                print(line.rstrip("\n"))
        return 0

    agent = resolve_field(args.agent, role.get("agent"), config("GDD_AGENT"))
    model = resolve_field(args.model, role.get("model"), os.environ.get("GDD_MODEL") or None)
    thinking = resolve_field(args.thinking, role.get("thinking"), os.environ.get("GDD_THINKING") or None)
    max_time = resolve_field(
        args.max_time,
        role.get("max_time") or budgets.get("max_time"),
        os.environ.get("GDD_MAX_TIME") or None,
    )
    if isinstance(max_time, (int, float)) and not isinstance(max_time, bool):
        max_time = forwarded_duration(max_time)
    try:
        run_name, run_dir, launch_run_root = launch(
            launcher,
            prompt_path,
            repo,
            args.goal,
            args.stage,
            agent,
            model,
            thinking,
            max_time,
            attempt=rounds_seen + 1 if plan is not None else None,
        )
    except (LaunchError, OSError) as exc:
        message = str(exc).strip() or exc.__class__.__name__
        first_line = message.splitlines()[0]
        print(f"gdd: launch failed: {first_line}", file=sys.stderr)
        ledger_append(
            repo,
            args.goal,
            "blocked",
            base,
            head,
            gates,
            note=f"launch-failed: {first_line}",
        )
        return 3

    ledger_append(
        repo,
        args.goal,
        args.stage,
        base,
        head,
        gates,
        next_stage=args.stage,
        note=f"run={run_name}" if plan is not None else None,
        rounds=rounds_seen + 1 if args.stage in ("simplify", "review") else None,
    )
    print(f"run: {run_name}")
    print(f"run_dir: {run_dir}")
    print(f"poll: GDD_RUN_ROOT={shlex.quote(launch_run_root)} {launcher} status {run_name}")

    if args.wait:
        deadline, delay = time.time() + 6 * 3600, 1
        while True:
            state = agent_run.read_state(run_dir)
            if state and agent_run.observed_state(run_dir, state) != "running":
                break
            if time.time() > deadline:
                fail(f"wait: run still not finished after 6h: {run_name}", 1)
            time.sleep(delay)
            delay = min(delay * 2, 30)  # a short stage returns in seconds, a long one polls every 30 s

        final_state = agent_run.observed_state(run_dir, state)
        exit_code = state.get("exit")
        duration = state.get("duration_s")
        if final_state != "done":
            ended = (
                f"wait: run ended in {final_state} "
                f"(exit={exit_code if exit_code is not None else '-'}) instead of done"
            )
            # Reconciliation is phase 7's job; the attempt is already recorded, and a raw
            # launcher resume would spend no round and skip the plan's routing and budgets.
            remedy = (
                "the attempt is recorded; the operator reconciles the run's partial work "
                "first (phase 7); a further attempt is a new gdd.py stage dispatch that "
                "spends a round (or --over-budget with the owner's approval)"
            )
            if args.stage == "implement":
                remedy += "; a delegated ce-work run is never resumed"
            fail(f"{ended} — {remedy}", 1)
        post_head = git(repo, "rev-parse", "HEAD")
        final_head = final_head_for(args.stage, bool(args.head), head, post_head)
        result = agent_run.read_json(os.path.join(run_dir, "result.json"), {})
        verdict = result.get("verdict") if state.get("result") == "valid" else None
        tokens = run_usage(state)
        wall = f"{duration}s" if duration is not None else "unknown"
        note = (
            f"exit={exit_code if exit_code is not None else '-'} "
            f"dur={duration if duration is not None else '-'} "
            f"head={post_head[:7]}"
        )
        if plan is not None:
            note += (
                f" role={args.stage} route={reported_field(state, 'agent', agent)}"
                f" model={reported_field(state, 'model', model, observed=True)}"
                f" thinking={reported_field(state, 'thinking', thinking, observed=True)}"
                f" wall={wall} tokens={tokens if tokens is not None else 'unknown'}"
            )
        if verdict:
            note += f" verdict={verdict}"
        ledger_append(
            repo,
            args.goal,
            args.stage,
            base,
            final_head,
            gates,
            note=note,
            rounds=rounds_seen + 1 if args.stage in ("simplify", "review") else None,
        )
        print(f"finished: state={final_state} {note}")
        print_answer_head(run_dir)
        if verdict:
            print(f"result: {verdict}")
            for criterion in result.get("unmet_criteria") or []:
                print(f"  unmet: {criterion}")
        elif state.get("result"):
            print(f"result: {state['result']} {state.get('result_error') or ''}".rstrip())
    return 0


def cmd_setup(args):
    """Write the goal's run plan and record one setup row; never invent a field."""
    if not os.path.isdir(args.repo):
        fail(f"--repo is not a directory: {args.repo}")
    repo = os.path.realpath(git(args.repo, "rev-parse", "--show-toplevel"))
    repo_name = repo_key(args.repo)
    defaults = {}
    defaults_path = config("GDD_RUN_PLAN_DEFAULTS")
    if defaults_path:
        defaults = read_plan_source(defaults_path, "GDD_RUN_PLAN_DEFAULTS")
    override = read_plan_source(args.plan_file, "--plan-file") if args.plan_file else {}
    path = run_plan_path(repo_name, args.goal)
    write_run_plan(path, merge_plans(defaults, override))
    ledger_append(repo, args.goal, "setup", "-", "-", "-", note=f"plan={path}")
    print(f"run plan: {path}")
    return 0


def scope_tool():
    resolved = os.path.expanduser(
        config(
            "GDD_WORKTREE_SCOPE",
            default="../delegated-work-acceptance/scripts/worktree-scope.py",
        )
    )
    if not os.path.isabs(resolved):
        resolved = os.path.normpath(os.path.join(os.path.dirname(SCRIPT_DIR), resolved))
    if not os.path.isfile(resolved):
        raise skill_config.ConfigError(f"GDD_WORKTREE_SCOPE does not resolve to a file: {resolved}")
    return resolved


def cmd_scope(args):
    print(scope_tool())
    return 0


def run_commit(args, repo, report):
    def run_git(*argv, check=True, **options):
        return gdd_process.run(["git", "-C", repo, *argv], capture_output=True, check=check, **options)

    def git_text(*argv):
        return run_git(*argv).stdout.decode("utf-8").strip()

    def diff_paths(*argv):
        return set(run_git("diff", "--name-only", "-z", "--no-renames", *argv, "--").stdout
                   .decode("utf-8").split("\0")) - {""}

    def refuse_paths(code, paths):
        raise CommitRefusal(code, ", ".join(sorted(paths)))

    if running := active_runs(repo):
        raise CommitRefusal("ACTIVE_RUN", ", ".join(name for name, _ in running))
    fetched = run_git("fetch", "--", args.remote, check=False)
    if fetched.returncode:
        raise CommitRefusal("FETCH_FAILED", process_detail(fetched))
    main_ref = f"refs/remotes/{args.remote}/main"
    main = git_text("rev-parse", "--verify", main_ref)
    report["oid"] = git_text("rev-parse", "HEAD")
    merged = run_git("merge-base", report["oid"], main, check=False)
    if merged.returncode != 1:
        merged.check_returncode()
    report["base"] = merged.stdout.decode("ascii").strip() or None
    if report["base"] != main:
        raise CommitRefusal("BEHIND_MAIN", f"merge base {report['base']} != {main_ref} ({main})")
    report["branch"] = git_text("branch", "--show-current") or None
    if not report["branch"]:
        raise CommitRefusal("DETACHED_HEAD", "HEAD is not on a branch")

    tool = scope_tool()
    baseline = scope_baseline(tool, repo, args.goal)
    if not baseline:
        raise CommitRefusal("NO_BASELINE", f"no scope snapshot for label {args.goal!r}")
    if baseline["head"] != main:
        raise CommitRefusal("BASELINE_MISMATCH", f"snapshot {baseline['head']} != merge base {main}")
    diff = scope_run(tool, repo, args.goal, "diff")
    diff.check_returncode()
    scope = json.loads(diff.stdout)
    if scope["overlapping_paths"] and not args.accept_overlap:
        refuse_paths("OVERLAP", scope["overlapping_paths"])

    inventory = git_inventory(repo)
    pending = pending_paths(inventory, scope["excluded_preexisting_paths"])
    purposes = {}
    if args.result:
        schema = json.loads(Path(stage_result.SCHEMA).read_text(encoding="utf-8"))
        for result in args.result:
            try:
                changes = json.loads(Path(result).read_text(encoding="utf-8"))["changed_files"]
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise CommitRefusal("INVALID_INPUT", f"{result}: {exc}", 2) from exc
            problem = stage_result.error(changes, schema["properties"]["changed_files"], "changed_files")
            if problem:
                raise CommitRefusal("INVALID_INPUT", f"{result}: {problem}", 2)
            for change in changes:
                purpose = " ".join(change["purpose"].splitlines()).strip()
                if purpose or change["path"] not in purposes:
                    purposes[change["path"]] = purpose
    if unexplained := {path for path in pending if not purposes.get(path)}:
        refuse_paths("UNEXPLAINED_CHANGE", unexplained)
    if extra := purposes.keys() - pending:
        committed = diff_paths(main, report["oid"])
        if phantom := extra - committed:
            refuse_paths("PHANTOM_CHANGE", phantom)

    staged = {path for code, path in inventory if code[0] != " " and code != "??"}
    unresolved = {path for code, path in inventory if code in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}}
    if mismatch := (staged - pending) | unresolved:
        refuse_paths("INDEX_MISMATCH", mismatch)
    unstaged = {path for code, path in inventory if path in pending and code[1] != " "}
    partial = staged & unstaged
    if partial and (vanishing := partial - diff_paths("HEAD")):
        refuse_paths("INDEX_MISMATCH", vanishing)
    paths = [{"path": path, "purpose": purposes[path]} for path in sorted(pending)]
    if pending:
        try:
            subject = args.message if args.message is not None else Path(args.message_file).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CommitRefusal("INVALID_INPUT", str(exc), 2) from exc
        subject = subject.strip()
        if not subject or len(subject.splitlines()) != 1:
            raise CommitRefusal("INVALID_INPUT", "commit subject must be one non-empty line", 2)
        if unstaged:
            added = run_git(
                "--literal-pathspecs", "add", "--pathspec-from-file=-", "--pathspec-file-nul",
                input=("\0".join(sorted(unstaged)) + "\0").encode("utf-8"), check=False,
            )
            if added.returncode and partial:
                raise CommitRefusal("INDEX_MISMATCH", f"{', '.join(sorted(partial))}: {process_detail(added)}")
            added.check_returncode()
        if mismatch := diff_paths("--cached") ^ pending:
            refuse_paths("INDEX_MISMATCH", mismatch)

    seal = scope_run(tool, repo, args.goal, "seal", "--index",
                     *(["--accept-overlap"] if args.accept_overlap else []))
    if seal.returncode:
        raise CommitRefusal("SEAL_FAILED", process_detail(seal))
    report["scope_sha"] = json.loads(seal.stdout)["commit_seal"]["scope_sha"]
    if pending:
        with tempfile.TemporaryDirectory(prefix="gdd-commit-") as directory:
            message = Path(directory) / "message.txt"
            body = "\n".join(f"- {row['path']}: {row['purpose']}" for row in paths)
            message.write_text(f"{subject}\n\n{body}\n", encoding="utf-8")
            run_git("commit", "-F", str(message))
        report["committed"] = True
        report["paths"] = paths
        report["oid"] = git_text("rev-parse", "HEAD")

    oid = report["oid"]
    verified = scope_run(tool, repo, args.goal, "verify", "--commit", oid)
    if verified.returncode == 1:
        drift = json.loads(verified.stdout)["drift"]
        raise CommitRefusal("SCOPE_DRIFT", ", ".join(f"{row['kind']} {row['path']}" for row in drift), 1)
    verified.check_returncode()
    report["scope_sha"] = json.loads(verified.stdout)["scope_sha"]

    remaining = git_inventory(repo)
    if remaining:
        diff = scope_run(tool, repo, args.goal, "diff")
        diff.check_returncode()
        if leftovers := pending_paths(remaining, json.loads(diff.stdout)["excluded_preexisting_paths"]):
            refuse_paths("LEFTOVERS", leftovers)
    if args.no_push:
        return

    gates = args.gate or configured_gates()
    if not gates:
        raise CommitRefusal("NO_GATES", "supply --gate or configure GDD_GATES before pushing")
    for command in gates:
        start = time.monotonic()
        try:
            argv = shlex.split(command, posix=os.name != "nt")
            # Non-POSIX shlex retains surrounding quotes; subprocess expects raw arguments.
            if os.name == "nt":
                argv = [arg[1:-1] if arg[:1] == arg[-1:] and arg.startswith(('"', "'")) else arg for arg in argv]
            if not argv:
                raise ValueError("empty command")
            gate = gdd_process.run(argv, cwd=repo, capture_output=True, text=True)
            rc, detail = gate.returncode, process_detail(gate)
        except OSError as exc:
            rc, detail = 127, str(exc)
        except ValueError as exc:
            rc, detail = 2, str(exc)
        report["gates"].append(dict(command=command, exit_code=rc, duration_s=time.monotonic() - start))
        if rc:
            raise CommitRefusal("GATE_FAILED", f"{command} rc={rc}: {detail}", 4)
    pushed = run_git("push", "--", args.remote, f"{oid}:refs/heads/{report['branch']}", check=False)
    if pushed.returncode:
        raise CommitRefusal("PUSH_FAILED", process_detail(pushed), 5)
    report["pushed"] = True


def cmd_commit(args):
    report = dict(ok=False, error_code=None, exit=0, detail="", branch=None, base=None, oid=None,
                  scope_sha=None, committed=False, paths=[], gates=[], pushed=False)
    repo = None
    try:
        root = gdd_process.run(["git", "-C", args.repo, "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True)
        repo = os.path.realpath(root.stdout.strip())
        run_commit(args, repo, report)
    except CommitRefusal as exc:
        report.update(error_code=exc.code, exit=exc.exit_code, detail=str(exc))
    except CalledProcessError as exc:
        code = "GIT_ERROR" if exc.cmd[0] == "git" else "SCOPE_FAILED"
        report.update(error_code=code, exit=2, detail=f"{' '.join(exc.cmd)}: {process_detail(exc)}")
    except (OSError, ValueError, KeyError, TypeError, skill_config.ConfigError) as exc:
        report.update(error_code="INVALID_INPUT", exit=2, detail=str(exc))
    if repo is not None:
        base, oid, scope = (report[key] or "-" for key in ("base", "oid", "scope_sha"))
        pushed = "yes" if report["pushed"] else "no"
        note = (f"exit={report['exit']} code={report['error_code'] or 'ok'} "
                f"head={oid[:7]} scope={scope[:12]} pushed={pushed}")
        gates = ";".join(f"{gate['command']} rc={gate['exit_code']}" for gate in report["gates"])
        try:
            ledger_append(repo, args.goal, "commit", base, oid, gates, note=note)
        except (LedgerError, OSError, skill_config.ConfigError) as exc:
            if report["exit"]:
                report["detail"] += f"\n{exc}"
            else:
                report.update(error_code="LEDGER_FAILED", exit=5, detail=str(exc))
    report["ok"] = report["exit"] == 0
    if args.json:
        print(json.dumps(report))
    else:
        print(f"commit: {report['error_code'] or 'ok'} (exit={report['exit']})")
        for key in ("branch", "base", "oid", "scope_sha", "committed", "pushed"):
            print(f"{key}: {report[key] if report[key] is not None else '-'}")
        for row in report["paths"]:
            print(f"- {row['path']}: {row['purpose']}")
        for gate in report["gates"]:
            print(f"gate: {gate['command']} rc={gate['exit_code']} ({gate['duration_s']:.3f}s)")
        if report["detail"]:
            print(report["detail"])
    return report["exit"]


def cmd_close(args):
    """Write the landing row: stage=done with the PR and the merged head.

    The operator used to record this by hand, and stopped: 36 ledger rows held zero
    `pr`/`done` entries, so a new session read every merged goal as still in `fix`.
    """
    if not os.path.isdir(args.repo):
        fail(f"--repo is not a directory: {args.repo}")
    repo = os.path.realpath(git(args.repo, "rev-parse", "--show-toplevel"))
    base = args.base or git(repo, "merge-base", "origin/main", "HEAD")
    head = args.head or git(repo, "rev-parse", "HEAD")
    pr = args.pr or "-"
    note = args.note or f"pr={pr} head={head[:7]}"
    ledger_append(repo, args.goal, "done", base, head, args.gates or "-", note=note, pr=pr)
    print(
        f"closed: {os.path.basename(repo)} {args.goal} pr={pr} head={head[:7]}"
    )
    return 0


def repo_key(value):
    """The repo key delivery-state.py writes for --repo: git toplevel basename, else the value.

    Kept identical to delivery-state.py's normalize_repo so the ledger reader and the plan
    reader agree, including tilde expansion.
    """
    path = os.path.expanduser(value)
    if os.path.isdir(path):
        try:
            proc = gdd_process.run(
                ["git", "-C", path, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True,
            )
        except OSError:
            proc = None
        root = (proc.stdout or "").strip() if proc is not None and proc.returncode == 0 else ""
        return os.path.basename(root) if root else os.path.basename(os.path.abspath(path))
    default_root = os.environ.get("GDD_REPO_ROOT") or ""
    if default_root:
        candidate = os.path.join(os.path.expanduser(default_root), value)
        if os.path.isdir(candidate):
            return os.path.basename(os.path.abspath(candidate))
    return value


def reported_field(state, key, requested, *, observed=False):
    """The launcher-observed value, else the requested value marked `req:`, else `default`.

    The bundled launcher records its request arguments as model/thinking, not what the
    provider actually resolved, so those fields are trusted only when the state marks them
    observed (`<key>_observed`: true). The route is what the launcher ran, so it stands as-is.
    """
    value = state.get(key)
    if observed and state.get(f"{key}_observed") is not True:
        value = None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"req:{requested}" if requested else "default"


def cmd_status(args):
    cmd = [
        agent_run.interpreter(),
        DELIVERY_STATE,
        "show",
        "--repo",
        args.repo,
        "--goal",
        args.goal,
        "--state-file",
        os.path.expanduser(state_file()),
        "--task-root",
        task_root(),
        "--run-root",
        run_root(),
    ]
    result = gdd_process.run(cmd, capture_output=True, text=True,
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        return result.returncode

    repo_name = repo_key(args.repo)
    plan = read_run_plan(repo_name, args.goal)
    if plan is None:
        return 0  # no plan file: exactly the legacy show output
    state_path = os.path.expanduser(state_file())
    print()
    print("RUN PLAN")
    print(f"plan: {run_plan_path(repo_name, args.goal)}")
    print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
    budgets = plan.get("budgets") or {}
    token_cap = budgets.get("token_cap")
    if token_cap is not None:
        total, unknown = accounted_usage(state_path, repo_name, args.goal, exact=True)
        print(f"tokens: {total} used, {unknown} unknown (cap {token_cap})")
    for stage in [name for name in STAGES if name in AGENT_STAGES]:
        role = (plan.get("roles") or {}).get(stage)
        cap = budgets.get("rounds", {}).get(stage)
        if cap is None:
            cap = STAGE_BUDGETS.get(stage)
        used = ledger_rounds(state_path, repo_name, args.goal, stage, exact=True)
        if role is None and cap is None and not used:
            continue
        total, unknown = accounted_usage(state_path, repo_name, args.goal, stage, exact=True)
        print(
            f"{stage}: rounds={used}/{cap if cap is not None else '-'} "
            f"tokens={total} unknown={unknown}"
        )
    return 0


EPILOG = """\
Environment or operator config file:
  GDD_STATE_FILE  ledger path passed to delivery-state.py
                  (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/ledger.tsv)
  GDD_TASK_ROOT   prompt/state root
                  (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/tasks)
  GDD_RUN_ROOT    run root exported to the launcher, and the fallback when it
                  prints no run dir
                  (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs)
  GDD_LAUNCHER    launcher command (default <script dir>/agent_run.py)
  GDD_AGENT       agent CLI exported to the launcher when set
                  (agent_run.py: an installed route; default omp, claude uses gdd-route-cc)
  GDD_TEMPLATES   template root (default <script dir>/../references/stage-templates)
  GDD_GOAL_GLOB   goal-contract glob (default docs/goals/*<goal>*.md)
  GDD_RUN_PLAN_DEFAULTS
                  JSON defaults `setup` merges under --plan-file
  GDD_MODEL, GDD_THINKING, GDD_MAX_TIME
                  passed to the launcher only when set; never defaulted here

The eight keys above GDD_MODEL also resolve from
$XDG_CONFIG_HOME/gdd/config.yaml (fallback ~/.config/...).
Order: CLI flag, then environment variable, then that file, then the default.
The shared rule is documented in hoa-skill-port.

Launcher contract:
  <launcher> start --name SLUG --prompt FILE --schema FILE [--cwd DIR] [--model M] [--thinking L]
                   [--max-time D]
  <launcher> list | status SLUG | result SLUG | answer SLUG | kill SLUG

The launcher writes <run_root>/<date>/<SLUG>/state.json with at least
{"name","state","exit","cwd","started","ended","duration_s"} and answer.md.
A missing state.json is unknown, never success.

Agent stages: implement, simplify, apply, review, fix
"""


def build_parser():
    parser = argparse.ArgumentParser(
        description="Render a stage prompt and launch one headless agent run.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    stage = sub.add_parser("stage", help="render a prompt and launch a run")
    stage.add_argument("--repo", required=True, help="repo path")
    stage.add_argument("--goal", required=True, help="goal / increment id")
    stage.add_argument("--stage", required=True)
    stage.add_argument("--base", default=None, help="base sha (default merge-base)")
    stage.add_argument("--head", default=None, help="head sha (default HEAD)")
    stage.add_argument("--findings", default=None, help="findings file (apply/fix)")
    stage.add_argument("--gates", default=None, help="gate command text")
    stage.add_argument(
        "--launcher",
        default=None,
        help="launcher command (default: $GDD_LAUNCHER, config file, or the bundled adapter)",
    )
    stage.add_argument(
        "--agent", default=None,
        help="agent route exported to the launcher (default: $GDD_AGENT, config file, "
             "or the launcher's own default)",
    )
    stage.add_argument("--model", default=None, help="passed through only when set")
    stage.add_argument("--thinking", default=None, help="passed through only when set")
    stage.add_argument("--max-time", default=None, help="passed through only when set")
    stage.add_argument("--templates", default=None, help="template directory")
    stage.add_argument("--dry-run", action="store_true", help="render only")
    stage.add_argument("--wait", action="store_true", help="poll until the run ends")
    stage.add_argument("--force", action="store_true", help="ignore active-run guard")
    stage.add_argument(
        "--over-budget",
        action="store_true",
        help="dispatch past the stage's round cap (implement/simplify/review: 2)",
    )
    stage.set_defaults(func=cmd_stage)

    setup = sub.add_parser("setup", help="write the goal's run plan and record a setup row")
    setup.add_argument("--repo", required=True, help="repo path")
    setup.add_argument("--goal", required=True, help="goal / increment id")
    setup.add_argument(
        "--plan-file", default=None, help="plan JSON merged over $GDD_RUN_PLAN_DEFAULTS"
    )
    setup.set_defaults(func=cmd_setup)

    scope = sub.add_parser(
        "scope", help="print the resolved worktree-scope.py path (GDD_WORKTREE_SCOPE)"
    )
    scope.set_defaults(func=cmd_scope)

    commit = sub.add_parser("commit", help="seal, verify and optionally push a goal's increment")
    commit.add_argument("--repo", required=True)
    commit.add_argument("--goal", required=True)
    message = commit.add_mutually_exclusive_group(required=True)
    message.add_argument("-m", dest="message", metavar="SUBJECT")
    message.add_argument("-F", dest="message_file", metavar="MSGFILE")
    commit.add_argument("--result", action="append", default=[])
    commit.add_argument("--gate", action="append")
    commit.add_argument("--accept-overlap", action="store_true")
    commit.add_argument("--no-push", action="store_true")
    commit.add_argument("--remote", default="origin")
    commit.add_argument("--json", action="store_true")
    commit.set_defaults(func=cmd_commit)

    close = sub.add_parser(
        "close", help="record the landing row for a goal (stage=done, pr, merged head)"
    )
    close.add_argument("--repo", required=True)
    close.add_argument("--goal", required=True)
    close.add_argument("--pr", default=None, help="PR number")
    close.add_argument("--base", default=None, help="base sha (default merge-base)")
    close.add_argument("--head", default=None, help="merged head sha (default HEAD)")
    close.add_argument("--gates", default=None, help="gate summary")
    close.add_argument("--note", default=None, help="free-form note")
    close.set_defaults(func=cmd_close)

    status = sub.add_parser("status", help="delegate to delivery-state.py show")
    status.add_argument("--repo", required=True)
    status.add_argument("--goal", required=True)
    status.set_defaults(func=cmd_status)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except (skill_config.ConfigError, OSError, ValueError) as error:
        fail(str(error))
    except CalledProcessError as error:
        fail(process_detail(error))
    except LedgerError as error:
        fail(str(error), 1)


if __name__ == "__main__":
    sys.exit(main())
