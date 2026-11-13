# Accepting a gate or publisher through its shipped entry point

A delegate's tests usually run in-process against injected seams. The shipped surface adds flag
parsing, configuration loading, the delivery seam and the real call order — exactly where wiring
defects live — so acceptance drives the packaged binary as a subprocess, with your own fake on the far
side of the wire. This is the pass that turns "its 34 tests pass" into "20/20 end-to-end checks pass".

## Shape of the probe

1. **Temp consumer repo**, not the delegated tree: content fixtures, the config under test, and any
   approval artefact the release path requires (an init/review step plus a commit, when the entry point
   refuses an unreviewed set).
2. **Your own server** for the remote side: only the operations the contract names, recording `method`,
   path, headers and final status per request.
3. **A `--import` preload** in the child that rewrites the contract's hostnames to your server:

   ```js
   const real = globalThis.fetch;
   globalThis.fetch = (input, init) => {
     const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
     if (new URL(url).hostname !== 'remote.invalid') return real(input, init);
     // `pathname` drops the query string: keep it, or an auth or version selector is silently lost.
     const { pathname, search } = new URL(url);
     const target = FAKE + pathname + search;
     // A signed request arrives as a Request, not as (url, init) — and init still applies on top.
     return typeof input === 'string' || input instanceof URL
       ? real(target, init)
       : real(new Request(target, input), init);
   };
   ```

   Credentials go in the child's environment under the names the config expects; the config holds
   variable *names*, never values.
4. **Spawn the real binary** (`node --import <shim> <entry> <args>`), capture stdout+stderr, and judge on
   exit code plus the recorded requests. Keep the probe in a scratch dir so it never ships and is never
   mistaken for the delegate's work.

## Pitfalls, each of which produced a false verdict

- **Spreading `{...init}` over a `Request` drops the method and the body.** The shim forwards a GET where
  the client sent a signed PUT, and the failure surfaces at the far end ("bucket not found", "object
  missing") — a verdict about the wrong layer. Build `new Request(target, input)`, then assert the
  server saw the expected method before interpreting anything else.
- **A permissive fake passes a client that sends nothing.** Refuse a write without the conditional
  header, verify the declared digest against the bytes received, require the credential in the
  authorization header. The fake is the contract's second implementation.
- **Judge repeat runs by the protocol, not by a zero counter.** A conditional-write client re-issues the
  same write and is answered "already present"; asserting "no requests on the second run" fails correct
  code. Assert the reported outcome and that previously stored bytes are unchanged.
- **A missing remote object proves nothing unless the client had to look at it.** Deleting the stored
  object before a re-run makes a correct client upload it again; model the serving failure as its own
  mode (write succeeds, read 404s).
- **Derive expected keys from the artefact's own bytes.** Hash the emitted files, build the expected
  path, compare sets — that proves the client published the content, not something it computed
  separately.
- **Assert absences explicitly.** A withheld input produces no request at all; no credential appears in
  stdout+stderr; no source path or private slug appears in a key. The delegate's suite usually omits
  these.
- **Sequence the failure modes with a mode switch**: conflict with matching bytes (reuse), conflict with
  different bytes (fail closed, stored bytes unchanged), public 404 after a successful write, rejected
  credentials, redirect to another host. Each needs a non-zero exit *and* the named reason.
- **Keep a positive control in the same run: a request you force through the shipped entry point and
  require the fake to record.** A zero-request build is only a *negative* control — it looks identical
  whether the shim works or was never loaded, so on its own it cannot show the probe can observe traffic
  at all, and an absence-based check then passes without exercising interception. Assert the recorded
  method and path of the forced request before reading any other verdict.

## Reporting

One `PASS`/`FAIL` line per case with the observed number, then one line in the verdict: the delegate's
suite count and your probe count are two different claims, and the second is the one you are signing.
Quote only numbers your own run printed; a commit message is the one place a wrong count becomes
permanent.
