# Platform premises in a test suite

## The class

A case that is green on one OS and red on another is asserting a **host premise it never declared**.
The recurrence signature is the tell: local green, one matrix leg red, a per-case fix merges, the next
round produces another case of the same shape. By the third one the loop itself is the defect — stop
patching cases and build the premise layer (see `root-cause-consult`).

Start from the failing case names, which the harness's own summary prints (`N failing test(s):`, the nested
runner's per-case status lines) even in a hosted log that keeps no per-case traceback, then read the guard's
own assertion line — the expectation that is wrong is usually named right there.

Two kinds of premise, requiring opposite treatment. Conflating them is what produces the loop.

## 1. Separate path GRAMMAR from KERNEL semantics

- **Pure path grammar** — join/split, absoluteness, drive letters, UNC, separators, and `..` collapsing
  *as a string operation* — is logic, not environment. It can be exercised on **any** host through the
target platform's own module: `(posixpath, PurePosixPath)` and `(ntpath, PureWindowsPath)`. If a case
  about grammar has never run under the other dialect, the suite has a hole no green run reveals.
- **Real kernel / filesystem semantics** are properties of the machine the test runs on and are **not
  simulable**: whether the FS follows a reparse point before applying `..`, whether `O_EXCL` is refused
  on a dangling link, whether mode bits are enforced, case sensitivity, whether a non-admin can create a
  symlink, whether `os.replace` crosses devices, open-handle locking, the platform's own rename/delete
  syscalls.
- **A "simulated platform" run that only mocks capability or identity metadata, while still executing
  the host's own path module and VFS, is not evidence about the target platform.** It is a local run with
  a foreign label: every case carrying an undeclared local premise passes there and fails on the real leg.

## 2. Dual-dialect by construction, not by platform string

- Thread the path module in (`pathmod=os.path` default) or parameterise the pure helper, and assert
  **both dialects in one run on every host**. A grammar rule that only runs on the platform it came from
  will be found by the matrix, one leg at a time, at a cost of a round each.
- Pin version-dependent semantics explicitly instead of inheriting the running interpreter's strictness:
  an absoluteness rule that changed between interpreter versions is asserted through that version's own
  module so the suite states the rule it means.
- A single "host answer" seam that returns the expected value is **not** sufficient — it makes the
  foreign-platform assertion a tautology. Use a seam only where the real semantics cannot run, and always
  with the question "would this fail if the behaviour were removed?".

## 3. Every premise-dependent case declares itself

- A case that cannot hold on some platform keeps the invariant and says which platform it asserts, in its
  own words, or branches on the platform's **own** resolution of the situation (read the file each
  spelling resolves to) rather than on a hardcoded expectation.
- Never delete, narrow, or skip-widen a case to green a leg. A skip without a named reason is
  indistinguishable from a case that stopped being reached.
- **A guard that enumerates the expected skips is itself a platform premise, and it is the next red leg.**
  A nested run asserting "these names are the only cases that may be non-`ok`", or any pinned skip floor,
  carries the author's host as a literal: the first case added that legitimately skips on a host lacking a
  capability (no mode bits, no symlink privilege, no compiler) reddens the other leg over a *correct* skip,
  and the red names the guard rather than the case. Derive the inventory from the probe's own answer
  (expected = the guarded names + the capability-gated cases **iff** the probe reports that capability
  absent), which keeps the assertion's teeth in both directions: those cases must be `ok` where the
  capability exists, and every other skip still fails.
- **A forced platform answer does not move a probe measured at import.** A child that fakes `sys.platform`
  or a capability flag changes only the surface it fakes; the contract object built at import still reports
  the real machine, so the fix above is untested by that child. Pin the guard by driving it with fabricated
  per-case statuses under both answers of the measured field — accepted under the capability-absent answer,
  refused under the present one — and say in the report which leg only the real matrix can settle.

## 4. Probe the host once, at import

Build the fixture layer from the host's own answer — never from a platform string, and never from an
assumption about privilege or filesystem features. Probe, once at import, into a single contract object:
case sensitivity, symlink capability *and privilege*, reparse-point traversal, `O_EXCL` on a dangling
link, mode-bit enforcement, the absolute-path anchor.

Canonical fixture helpers on top of it: an absolute path in the platform's own form, a symlink factory
(link-to-dir vs link-to-file), an executable stub, and a "creation must be refused" assertion. Then:

- A case whose premise the probe reports as unavailable **skips with the reason**, never passes silently
  and never fails as if the product were broken.
- Keep the probe's own values readable in the failure output, so a red leg says which premise the host
  did not satisfy.
- Measure what is **stored** with `stat` and keep executable *lookup* a separate answer: `access(X_OK)`
  consults the mount's `noexec` policy as well, so a writable `noexec` scratch mount denies execution for
  a file whose execute bit is set. A probe built on it raises at import and takes the whole suite down
  before a single case runs — the probe's job is to report a premise it cannot satisfy, never to raise.

## 5. Make the idiom unwritable

A documented convention does not survive contact with the next author. Ban the POSIX-only idioms
mechanically, with an **AST** lint (a regex is defeated by equivalent spellings and by multi-line calls):

- a fabricated absolute path built by joining the separator onto the root;
- `assertRaises` of an OS error class against the real filesystem without a capability probe;
- a bare symlink/file-mode call outside the fixture helper;
- a hardcoded `:` (or `;`) used to split/join `PATH`;
- a permission or executability assertion that does not consult the mode-bit probe.

Place the lint beside the syntax-level checks the suite already runs, and prove it bites by feeding it a
seeded bad idiom that must be reported — then restore the planted file byte-exactly (digest equal before
and after) and re-run green. A plant left in the tree is not proof, and neither is reading the lint's own
source.

## 6. A byte contract pins the line-ending translation, not just the encoding

- Pinning `encoding="utf-8"` on a text-mode write leaves `newline=None`, so the host's own line separator
  goes out with the text: on Windows every `\n` becomes `\r\n`. A case — or a declared fixture digest, a
  manifest hash, a receipt — that compares the written bytes against the intended string is then green on
  the leg that writes LF and red only on the leg that translates, and the red survives the encoding pin
  that looks like it already addressed it.
- Where byte equality is the contract, pin the translation beside the encoding (`newline="\n"`, or write
  bytes from explicitly encoded text). Where CRLF is legitimate, compare parsed content or normalize both
  sides by a stated rule — never leave the comparison resting on `os.linesep`.
- Same family for every text surface whose bytes are the claim: a `subprocess` stream captured with
  `text=True`, a generated config/CSV/TSV hashed into a manifest, a transcript compared verbatim. Read it
  back in binary and decode explicitly.
- **A stub that forces one platform mechanism does not cover the others on the same path.** A case that
  patches the interpreter's encoding resolver (`io.text_encoding`) proves the `encoding=` pin and leaves
  the line-ending translation untouched, so its local green is evidence about one of the two host
  behaviours the write consults — and the untested one is exactly what the foreign leg reports.
  Enumerate every host-dependent behaviour on the path (default encoding, line-ending translation,
  separator, `os.linesep`, mode bits, path anchor), give each a real-leg oracle or its own forced answer,
  and say in the case's own docstring which of them the stub covers.

## 7. Say what only the real platform leg can answer

Write the boundary down where the suite's claims are stated: the target platform's real syscalls, the
probe's own values on that platform, open-handle/locking semantics, and end-to-end foreign-absolute paths
remain the matrix leg's job. A green local run — including a green simulation — is not evidence for them,
and a claim that a leg verifies something must be pinned to the artifact (the job runs the gate file, no
literal runner label bypasses the matrix).

## Do not

- Build a per-OS errno or exception table. Assert the **product's contract** and inject the exception to
exercise the branch.
- Report a simulation as platform evidence, or quote a local green as the answer for a foreign leg.
- Treat the third same-shape red as "one more case to fix". That is the signal to stop and build the
  premise layer.
