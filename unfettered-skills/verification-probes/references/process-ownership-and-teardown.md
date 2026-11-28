# Is that process mine, and did it actually go away?

Two claims a runner, watchdog or job wrapper makes about child processes, both of which read as settled while
being wrong. Probe them by identity and by observed effect — never by the number you wrote down, and never by
the cleanup step's own success line.

## Ownership: a recorded pid or pgid is not identity

Between the spawn and the cleanup the number may name a different, unrelated process. Before signalling a
recorded id, establish ownership from something the runner itself recorded:

- **Creation identity** — field 22 (`starttime`) of `/proc/<pid>/stat`, captured at spawn, compared before the
  signal. A recycled id has a different start time.
- **The resource relation** — the process still refers to the resource you own: its cwd or its environment
  carries your task-local scratch/temp root.
- **An unreaped child** — a child you have not waited for keeps its pid reserved (the kernel does not recycle
  it). **Prove unreaped-ness at the kernel, never with `Popen.returncode`:** that is a cached field, so a child
  somebody else collected — a handler's `os.waitpid`, or `SIGCHLD` set to `SIG_IGN` so the kernel reaps it —
  leaves `returncode` at `None` while its pid is already released and reusable, i.e. the anchor reads intact
  exactly when it has failed. Ask instead with the non-reaping probe: `os.waitid(os.P_PID, pid,
  os.WEXITED | os.WNOWAIT | os.WNOHANG)` raises `ChildProcessError` once that child is no longer waitable, and
  while it answers it reports the status **without reaping**, so the id stays reserved. Pair it with
  `os.getpgid(pid) == pid` (true only while your own child, spawned with `start_new_session`, is unreaped).
  `subprocess.wait()` reaps, so the anchor dies with the reap — this is the one anchor that survives a leader
  killed by a signal, and where `waitid`/`WNOWAIT` is unavailable ownership goes with it.

None available → **refuse to signal and report the cleanup as unverified**. Fail closed, the way the repo's
other guards do; a cleanup that guesses can kill an unrelated job on a shared host.

Probe it both ways in one run: model a group that is not yours (an unrelated live process group, no resource
relation) and show the code refuses; then a worker you started, and show it dies. An arm that only ever
reports "stopped" is indistinguishable from one that signals everything.

## The proof has a lifetime: pin identity at delivery

An anchor that is *observed* is not a target that is *reserved*. `waitid(… WNOWAIT)` proves the kernel still
holds that child at the instant it answers — it does not stop the next instant: another waiter (a library's
`waitpid`, a signal handler, an inherited `SIGCHLD = SIG_IGN` that makes the kernel reap automatically) can
collect the child before the signal goes out, after which the number is free and the signal reaches a
stranger. Every fix shaped as "check ownership once more, then signal" re-opens the class, because one more
observation is one more instant with the same gap after it.

- **Move the proof into the act.** Open a handle that names the process *instance* and deliver through it:
  `fd = os.pidfd_open(pid)`, re-read field 22 and require equality with the start time recorded at spawn, then
  `signal.pidfd_send_signal(fd, signum)`. The descriptor pins the instance, so a number recycled before the
  open is rejected there, and `ProcessLookupError` at the send means *gone*, reported as unverified. Keep one
  delivery site for every route, and re-pin per escalation round: a handle opened for an earlier attempt is
  never authority for a later delivery.
- **Fix the runner's own disposition before anything is spawned.** Put `SIGCHLD` in `SIG_DFL` (restoring what
  you replaced when the run ends) and re-read the *live* disposition at decision time: a disposition sampled
  once into a flag goes stale the moment something installs a handler, and an inherited `SIG_IGN` silently
  invalidates every reaping proof.
- **A group id, and every member you enumerate from it, is the one thing you cannot prove you own.** The
  descriptor above pins the *instance* of one process; it says nothing about the numeric group allocation, so
  a group enumerated after its original members were reaped can already be another job's group — whose members
  pass every per-pid check you can make (live, a start time, even your resource relation read one call
  earlier). Per-member pinning is therefore not an ownership proof either: it is one more observation with the
  same gap after it. Where a group is the only handle, the rung that ends the class is the **refusal** — signal
  **only the process this run spawned** (the one identity it recorded itself) and *report* the enumerated rest
  (named pids, teardown `unverified`) instead of signalling it. `os.killpg(group, 0)` stays only as a liveness
  probe (signal 0 delivers nothing); delete every path that turns a recorded number into a signal.
- **Identity is not two lookups: evidence and identity must come from one read.** Asking `does this pid refer
  to my scratch?` and then `what is this pid's start time?` is two unprotected queries, and a reap plus reuse
  between them joins one process's evidence to another's identity — a splice no per-field check can see.
  Bind pid and start time in a single pass (both read from the same `/proc/<pid>/stat` line, or the same loop
  iteration), or re-read the whole tuple after opening the handle; a helper returning one field *about* a pid
  is evidence only beside the other field read with it.
- **A signal constant is a capability too.** `signal.SIGKILL` does not exist on Windows, so a module-level
  default breaks the import on the platform that lacks it — resolve it inside the cleanup path
  (`getattr(signal, "SIGKILL", signal.SIGTERM)`).
- **Declare the residual window instead of claiming it shut.** A member's *membership* is evidence read just
  before delivery, so a member that leaves the group in that gap is signalled while its identity is still
  pinned: a stated limit, not the same sentence as "ownership is proven". Cases asserting a *successful*
  delivery need the full conjunction of capabilities (`pidfds` + `/proc` + `waitid`/`WNOWAIT` + a live
  established disposition) in one guard; where one is missing, the pinned case is the **refusal** — nothing
  signalled, the limit recorded.

## Which completions need cleanup

- Cleanup wired to the timeout path only misses the killed path: a subject killed by a signal never reaches
  its own exit path, so its own cleanup callbacks never run. Drive teardown from "did not finish under its own
  control" — timeout **or** a negative exit status.
- Leave clean exits (0/1) alone: there the subject's own cleanup ran and its declaration of what it detaches
  owns that contract. Adding teardown there changes behaviour that was already correct.
- A process group outlives its leader, and a killed leader is reaped before anyone can ask for its group.
  Capture each command's group at spawn (`start_new_session` makes `pgid == pid`) and keep the ids; after
  `wait`, the surviving members are findable only from the id you kept.
- Terminate a group once. A runner that kills the group on timeout and then hands the same ids to a generic
  abnormal-cleanup wrapper kills it twice and reopens the log twice more.
- **Sweep the group before you reap, and know which exits your own observer reaps.** The teardown opportunity
  and the ownership proof expire together (at the reap), and where non-reaping exit observation is unavailable
  the exit observer is itself the reaper: a *timed-out* command is still unreaped when its wait raises
  `TimeoutExpired`, so its group teardown works, while a *signal-killed* command is reaped inside the
  observation step, so its group teardown can only be reported **unverified** — not "unsupported on this
  platform". Order the steps: observe the exit, sweep the group, then reap.

## Reading `/proc` without a silently dead detection arm

- **`/proc/<pid>/cwd` is a symlink, `environ` is a file.** `read_bytes()` on the symlink raises
  `IsADirectoryError`, so a sweep written as `for field in ("cwd", "environ"): suppress(OSError):
  read_bytes(...)` loses the cwd half and reports "not ours" for every process, forever. Use `os.readlink` for
  cwd, `read_bytes` for environ; a symlink into a deleted directory still carries the path with a trailing
  `(deleted)`.
- **A capability guard that never calls the API proves nothing.** `hasattr(os, "killpg")` as a gate while the
  body delegates to a `/proc` reader: on a host with `killpg` and no `/proc` (macOS) nothing is signalled and
  the code believes the group was terminated.
- Feed the arm one input that **must** match before trusting its silence — the general rule is in the parent
  skill's pitfalls.

## Reporting: say which of the two you observed

- `reason: "process group terminated"` printed unconditionally is a claim that cannot fail: it appears just as
  readily when nothing was signalled, or on a platform where nothing could be. Carry observed-vs-unverified,
  and the ids actually signalled, into the outcome.
- **Record a clause when the termination is verified, not when the signal went out.**
  `clauses=("process group",) if signalled else ()` records the intent, which lets the printer emit a
  self-contradictory line ("process group terminated; … teardown is unverified"), and where that printer's own
  guard is `if clauses and not survivors`, an unrelated surviving *detached* pid suppresses the group clause on
  the merged record. Build each mechanism's clause after its own observation step has run.
- **One field per fact: make the unverified state unrepresentable as verified.** A record carrying both
  `verified: bool` and `unverified: str` encodes one fact twice, so a caller that sets only the message has it
  printed as nothing (`describe()` reading the bool) and six call sites repeat the flag. Keep the messages as a
  tuple merged by union (`tuple(dict.fromkeys(a + b))`), one entry per clause — deduplicating *before* any
  `"; "` joining, since `("a; b", "a")` survives a post-join comparison — and derive `verified` from emptiness
  (`not unverified`) rather than storing it beside.
- **A branch that cannot establish ownership must return early.** An `if group is None:` arm that falls through
  to the grace-period wait and the survivor merge reports "pids … survived SIGKILL" immediately after logging
  "not signalled", and burns the grace period on a process nothing was ever sent to. Every
  cannot-establish branch returns before the waiting code.
- Keep each mechanism on its own channel. Writing same-group survivors into a *detached-processes* counter
  makes the record wrong in both directions: it claims a detached termination when no detached process
  existed, and hides the group termination when one happened.
- State per-platform capabilities per platform, and per **capability** rather than per family: group teardown
  is POSIX (`os.killpg`), scratch-holder sweeping is `/proc`-backed, and non-reaping exit observation is
  `os.waitid` + `WNOWAIT` — which CPython does not expose on macOS before 3.13, so `hasattr(os, "killpg")` is
  true while `WAITID_WNOWAIT` is false on the same host. Equating the two turns a real limitation of one route
  into a false "POSIX only" claim. Say which capability each route needs, and guard each case with a
  `skipUnless(<that capability>, …)` matching the route it drives, or the suite reports an unsupported
  platform as a defect. Documentation that says unconditionally "survivors are stopped before the tree is
  deleted" is the next round's factual finding — qualify it or make the code true on every platform claimed.

## Pinning the behaviour

Cases that fail on the previous implementation, one per route that reaches the same verdict:

- a worker whose only tie to the resource is its cwd;
- a member or scratch holder whose evidence matches perfectly — assert it is **reported and still alive
  afterwards**, the only shape that separates the refusal rung from a signal plus an honest record;
- a subject whose leader is signal-killed while a same-group child survives;
- a contradictory counter line on the covered route as well as the scheduled one.

When the fix sits inside the enumerator that decides what runs, prove the plan is unchanged by diffing its own
listing across the two revisions — the rule and the stash recipe are in the parent skill §4–§5.
