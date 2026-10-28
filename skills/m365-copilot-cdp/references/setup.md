# Existing-profile desktop setup

Read this when CDP is unavailable, the target is wrong, or native Code is not
ready. The messaging adapter never creates a profile or changes these settings.

- [Application and profile](#application-and-profile)
- [Enable consent-based CDP](#enable-consent-based-cdp)
- [Native Code readiness](#native-code-readiness)
- [Restore the debugging preference](#restore-the-debugging-preference)
- [Uncertain sends](#uncertain-sends)

## Application and profile

The observed Windows executable is
`C:/Program Files (x86)/Microsoft/Copilot/Application/copilotapp.exe`.
The current user's signed-in profile is normally
`%LOCALAPPDATA%/Microsoft/Copilot/User Data`. Verify the installed application
rather than assuming a similarly named PWA is equivalent. The working Chromium
`webview` target is on `cr.m365copilotapp.svc.cloud.microsoft/hwav2/chat` or
`/hwav2/code`; `edge://olympia.top-chrome/` is its shell.

Reuse this existing profile. Never create an independent automation profile,
copy a profile, or export/import cookies, tokens, or credentials. Prefer an
application-provided new window in this profile, verify its exact target ID,
and do not silently fall back to the user's active window. Multiple windows do
not guarantee separate conversation state; verify the selected session before
mutating it. Sharing the main window requires explicit permission and sequential
operation while the user is not interacting with it.

## Enable consent-based CDP

Observed Copilot builds 157.0.4341.16 and 157.0.4341.24 reject
`--remote-debugging-port` on the default profile:

```text
DevTools remote debugging requires a non-default data directory. Specify this using --user-data-dir.
```

A different profile is not an allowed workaround. Recent Chromium instead
supports [user-approved connections to an existing profile](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/advanced-usage.md#automatically-connecting-to-a-running-chrome-instance).
The installed Copilot engine contains this mode. Its shell did not expose the
normal `chrome://inspect/#remote-debugging` settings page during verification.

With separate, explicit user authorization, the bundled `scripts/consent.ts`
helper can set only `devtools.remote_debugging.user-enabled` in the existing
profile's `Local State`. It preserves other values and uses an atomic replacement
within that same profile; it does not export authentication or create a second
profile. Before enabling, it exclusively creates, flushes, and closes the required
rollback receipt containing only the previous debugging value. If that receipt
cannot be saved, Local State remains unchanged. An existing receipt is never
overwritten: restore it before enabling again. The helper refuses to change state
while `copilotapp.exe` is running.

First have the user preserve work and quit Copilot normally. Do not terminate an
active user session automatically. In PowerShell, with `SkillDir` replaced by
the installed skill directory and the caller's repository as the working directory:

```powershell
$SkillDir = 'PATH_TO_SKILL'
$Profile = Join-Path $env:LOCALAPPDATA 'Microsoft\Copilot\User Data'
New-Item -ItemType Directory -Force '.tmp-artifacts/copilot-run' | Out-Null
$Receipt = '.tmp-artifacts/copilot-run/consent-previous.json'
bun "$SkillDir/scripts/consent.ts" --profile-root "$Profile" --inspect
bun "$SkillDir/scripts/consent.ts" --profile-root "$Profile" --enable --receipt "$Receipt" --confirm-app-closed
if ($LASTEXITCODE -ne 0) { throw 'CDP consent setup failed. Preserve any rollback receipt and resolve the error before continuing.' }
```

Start Copilot normally. Do not also pass `--remote-debugging-port` or
`--remote-debugging-pipe`: the command-line route takes precedence over consent
mode and rejects the default profile. Connection approval remains under the
application's control; ask the user to approve the local debugging connection if
prompted. Do not bypass organization policy, sandboxing, or connection consent.

The app writes `DevToolsActivePort` in its existing profile. The driver reads only
that endpoint file when given `--profile-root`; it does not read authentication
state. Consent mode does not serve the usual HTTP `/json/version` discovery.
Start one persistent session, rather than listing targets in a separate connection
and reconnecting for each command:

```powershell
bun "$SkillDir/scripts/copilot.ts" --profile-root "$Profile" --session
```

Before connection, tell the user that Copilot may show **Allow remote debugging?**
and that this grants automation control of the signed-in app. Ask them to choose
**Allow** for this expected connection; never click it automatically. After the
`ready` JSON lists the available targets, send one JSON object per stdin line:

```json
{"operation":"select-target","target":"EXACT_AUTOMATION_WINDOW_TARGET_ID"}
{"operation":"inspect"}
{"operation":"models","mode":"chat"}
{"operation":"disconnect"}
```

Keep that process and connection alive between operations. `targets` refreshes
the inventory within the same connection. No operation uses an unselected window.
All session responses, including errors, are JSONL on stdout; connection notices
and startup errors go to stderr. A one-shot `--request` remains available, but
each new consent-mode connection can prompt again.

**Approval is not permanent across connections.** The observed dialog has no
remember-forever option; [Chromium's implementation](https://github.com/chromium/chromium/blob/main/chrome/browser/devtools/devtools_connection_dialog.cc)
returns an allow/deny result for the pending connection. One approved connection
supports repeated commands without another handshake. An app restart or lost
connection can require renewed user consent; never reconnect in a prompt loop
or claim a permanent grant. Disconnecting leaves the app running. The connector
uses `noDefaults: true` so it does not change download, focus, or media settings.

The app's `enableCdpWl` feature flag was observed **false** while the authorized
Code CDP probe successfully sent and received its response. It is not required
for this connection path. Its full product-specific meaning was not established,
and no verified evidence links it to native connection consent. Do not infer a
whitelist or permanent authorization mechanism from its name, or toggle it.

## Native Code readiness

Code is not Chat with a coding prompt. Its native host must be running as well
as the Chromium shell. In the observed installation the normal native launcher
was `undocked_copilot/copilotapphost.exe` with these arguments:

```powershell
Start-Process 'C:\Program Files (x86)\Microsoft\Copilot\Application\undocked_copilot\copilotapphost.exe' -ArgumentList '--launch','connect-to-browser','--browser-owned','--launch-undocked-bridge-framing','v1'
```

This is an observed version-specific launch recipe, not a private IPC protocol.
Use normal app activation first; use this recipe only after confirming the
installed launcher and obtaining authority for any necessary restart. Never
replay pipe names or start another host against a running user's session.

After attaching through consent mode to the existing profile and normal native
host, Code was verified with an enabled composer and
`Model: Claude Opus 5.5, effort: Medium`. Wait for real model/composer readiness;
`Models unavailable` during initialization is not proof of missing licensing.
The preliminary separate-profile experiment was rejected and is not the supported
setup. The generic CDP `Target.createTarget` new-window route did not yield a
verified working app window and is not used as a fallback.

Native dual-window Chat/Code operation was not established on build 157.0.4341.24.
The app and conversation menus inspected during integration exposed no new-window
action; Shift-clicking the native mode link did not create another Copilot target.
The current runner therefore uses one approved connection and sequential requests.
Different target IDs alone would not prove independent drafts, models, or sessions.
Do not enable parallel dispatch without verifying those properties in native windows.

Code onboarding and tool permissions are separate authority. A harmless prompt
does not authorize project selection, file changes, command execution, package
installation, GitHub access, or disabling permission prompts. Leave those prompts
for the user; never approve them just to finish a test.

## Restore the debugging preference

After preserving work and closing Copilot normally, restore only the recorded
previous debugging value using the receipt written by the helper:

```powershell
bun "$SkillDir/scripts/consent.ts" --profile-root "$Profile" --restore "$Receipt" --confirm-app-closed
if ($LASTEXITCODE -ne 0) { throw 'CDP consent restore failed. Preserve the rollback receipt and resolve the error.' }
```

An originally absent preference is removed; a prior boolean is restored without
reverting unrelated changes made since enabling. A successful restore consumes
the receipt; a failed Local State replacement leaves it available for recovery.
Keep the receipt if enabling reports an error after saving it, and restore before
trying to enable again. No profile backup or authentication data is needed.
Relaunch Copilot normally.

## Uncertain sends

Do not repeat a send after a click error or response timeout. Read the same
conversation or inspect the app to establish whether the prompt and a new reply
exist. Keep drafts and permission dialogs intact. If the result cannot be
established, report uncertainty instead of sending again.
