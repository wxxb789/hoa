# Cross-platform increments

A repo that ships on more than one OS turns a Linux-only green into a false seal. The matrix is the
proof; a local pass proves nothing about the other platforms.

- **Fixtures carry platform assumptions.** `/tmp/...` or `C:\\...` literals are wrong wherever the other
  OS runs them: `filepath.IsAbs` is false for `/tmp/x` on Windows, so a *valid* input gets rejected and
  the test blames the product. Build fixtures with `t.TempDir()` + `filepath.Join`.
- **Never substitute a path into serialised JSON by text replace.** Encoders escape separators
  (`C:\\Users\\...`); decode first, substitute second, normalise separators third, compare last.
- **Prove a foreign-platform bug with a portable fixture.** Reproduce the *shape* (an escaped `C:\\...`
  string, a bracketed `[::1]` URL) so the assertion carries the same meaning on any OS; otherwise only
  the far CI can tell you, and nobody can debug it locally.
- **Signals, mode bits and process groups are POSIX API.** Use a durable control file the process polls;
  treat a signal as an optimisation. `os.Chmod(0o600)` creates no restrictive ACL on Windows — assert a
  mode only behind `runtime.GOOS != "windows"` and report it as skipped, never silently dropped.
- **Make the rule a gate, not a paragraph.** A deterministic check (path literals, banned APIs) with a
  mandatory justification comment per exception stops the next increment from re-introducing the class;
  the prose only explains why the gate exists.
- **A gate that reports a name without the reason costs a round trip.** When a matrix job fails, the
  failing test's own output has to reach the gate log, or every remote reader debugs blind.
- **One product decision hides per platform.** Printed shell commands are text for a specific shell:
  POSIX quoting is wrong in `cmd.exe`/PowerShell. Either render per detected shell or record the gap as
  open — never let it pass as cross-platform correctness.
