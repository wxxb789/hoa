# Passing the `windows-latest` row of a matrix

A `windows-latest` failure is an assumption, and the assumption is nearly always in a *test fixture*
or in a *path / process primitive* — not in the algorithm. Fix the assumption in one shared helper and
pin it with a test that takes the GOOS as a parameter, so the local suite proves the emitted value
while CI proves the platform (SKILL.md step 8).

## 1. POSIX literals are not absolute on win32

`/tmp/db.sqlite` is not absolute for `filepath.IsAbs` on Windows, so a validator that correctly demands
an absolute path rejects your own "valid" fixture and the test dies on its setup, not on the behaviour.
Build fixtures with `t.TempDir()` + `filepath.Join`, and derive the expected value the same way — never
a literal containing `/`.

## 2. `filepath.Abs` on a volume-less path roots it on the current drive

`filepath.Abs("/tmp/demo/app.sqlite")` yields `C:\…\tmp\demo\app.sqlite`. Any assertion comparing
against `/tmp/demo/app-agent.sqlite` fails on a value the code produced correctly. Express both sides
with `filepath.Join(dir, …)`.

## 3. A JSON document escapes the separator

Replacing the temp dir in raw JSON (`strings.ReplaceAll(raw, temp, "<tmp>")`) never matches on Windows:
the path appears as `C:\\Users\\…`. Decode first, walk the value, replace inside strings, and unify
separators (`\` → `/`) so one golden covers every OS. Pin it with a case that feeds a synthetic
`C:\Users\…` document **on Linux**, so the normaliser is proven without a Windows runner.

## 4. `os.FindProcess` + `Process.Signal` is not a cancellation channel

`FindProcess` succeeds for any pid and `Signal` refuses every signal except `Kill`, so a “send SIGTERM
and wait” cancel path never delivers: the child keeps running and its heartbeat / lock file stays
fresh, so status says running, resume refuses with "live host", and the lock outlives the cancel. Make
the durable control a file the child polls (its own request channel), keep signalling as an optional
accelerator that is allowed to fail, and `Process.Kill()` as the bounded fallback. Then the product has
one rule on all three OSes instead of a `runtime.GOOS` branch in the middle of the logic.

## 5. `URL.hostname` keeps the brackets on IPv6 literals

Node returns `[::1]` where Go's validators pass `::1`, so a loopback allow-list written on one side
rejects the other and a supported local provider fails with `config_error` before any request. Strip or
compare the bracketed form explicitly, and test both spellings.

## Reporting a win32 row

- Only CI executes win32. `GOOS=windows go vet ./...` and `GOOS=windows go test -c ./...` are *compile*
evidence — say that plainly instead of implying the tests ran.
- Quote the first error the gate itself printed, not the list of test names it cascaded into.
- Never translate "Linux is green" into "Windows is presumably fine"; the row is a separate runtime
and a separate verdict. State which rows only CI can prove.
