# Restricted shells on privileged hosts

Facts observed on locked-down Windows admin workstations and Linux jump hosts. Treat each as a
hypothesis to probe on your host, not as a guarantee.

## Windows PowerShell under application control

- **Language mode.** Application control (WDAC/AppLocker) often forces Windows PowerShell 5.1 into
  ConstrainedLanguage. Probe `$ExecutionContext.SessionState.LanguageMode`. Under it, method calls
  on non-core types fail ("Method invocation is supported only on core types"): `[IO.File]`,
  `[IO.Path]`, `[Text.Encoding]`, hashing classes, `[DateTimeOffset]::Parse`, generic collection
  constructors, `New-Object` collections, `[pscustomobject]@{}` creation. `Import-PowerShellDataFile`
  (`.psd1`) fails with "Cannot create type", so keep configuration data in JSON. Dot-sourcing and
  `.psm1` modules, regex, `-match`, hashtables, arrays, `Get-FileHash`, `ConvertFrom-Json` and
  `Invoke-WebRequest` keep working.
- **Testing it locally.** Setting the language mode inside a session approximates enforcement but
  is not the same: functions defined before the switch keep full language, and modules loaded after
  it run constrained. Define the code under test after switching, assert the mode inside the test,
  and still confirm cross-file loading on the real host.
- **Edition differences (5.1 vs 7).** 5.1 `ConvertFrom-Json` does not unroll arrays; `1..0` yields
  two items; `-Encoding utf8` writes a BOM; native-argument quoting drops embedded quotes (a
  `jsonpath` containing `"\n"` breaks; use a literal separator and split afterwards). In both
  editions a function `return` unrolls a one-element array (`,$x` keeps it).
- **Blocked binaries.** Inbox tools such as `curl.exe` may be blocked while vendor tools installed
  under Program Files are allowed. Probe each binary before designing around it.
- **Patched CLIs.** A host-specific build of a cloud CLI may break long-running operations or write
  calls while reads work. Isolate with a no-op write sent directly over REST (setting a value to what
  it already is): success there clears permissions and network and pins the CLI.
- **Logging.** Module logging can record cmdlet parameters (a request `-Body` in full; a hashtable
  `-Headers` only by type name) and script block logging records pasted text. Keep tokens out of
  bodies and command text; pass them in header hashtables obtained inside the block.
- **Paste semantics.** An interactive paste executes line by line: a top-level `throw` stops only its
  own line, so wrap the block in `& { ... }`. `$LASTEXITCODE` keeps the previous native command's
  value after a thrown error. A new window loses every variable.
- **Native error preference.** With `$PSNativeCommandUseErrorActionPreference = $true`, a failing
  native command throws before the script's own diagnostic message prints; read the exception's
  command and exit code.

## Linux jump hosts

- `read -r -p` inside a pasted block consumes the next pasted line; assign values directly.
- Shell functions or aliases may wrap tools (`kubectl` appending a context); use `command <tool>`.
- A tool may read a sibling file by default (a stale manifest next to the script); pass the input
  file explicitly.
- The host identity may be unable to reach a source of truth (a code host in another tenant).
  Fetch that data on a host that can and transfer it, or move the step.

## Windows `cmd` wrappers on the agent side

Cloud CLIs installed as `.cmd` wrappers pass through `cmd.exe`, which splits arguments at `&`:
a URL with a second query parameter silently loses the rest of the command line, including output
filters. Pass query parameters through the CLI's parameter option or a body file.
