# Enable desktop Teams CDP on Windows

Read this only when the local CDP endpoint is unavailable. Reuse the current
signed-in Teams profile; never supply an independent profile or copy auth.
Save work and quit Teams normally first. Do not stop a running meeting or kill
processes to make this command succeed. Sign in through the app if required;
never extract tokens.

Run in PowerShell. These environment values apply only to the launched process;
the previous shell value is restored. The installed package path is discovered,
not pinned to a machine-specific version.

```powershell
if (Get-Process ms-teams -ErrorAction SilentlyContinue) {
    throw 'Quit Teams normally before enabling CDP.'
}
$package = Get-AppxPackage -Name MSTeams
if (-not $package) { throw 'Installed MSTeams package not found.' }
$previous = $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
try {
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = '--remote-debugging-port=9222 --remote-debugging-address=127.0.0.1'
    Start-Process (Join-Path $package.InstallLocation 'ms-teams.exe')
} finally {
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = $previous
}
```

Run the skill's `--targets` command once Teams has loaded. Hidden bootstrap pages
and native popouts can have the same URL as the working Teams UI. Every request
requires the exact inspected `--target`; automatic selection is not supported.
Prefer an automation-owned native window in this profile. `open-window` requests
the observed new-message popout, not a second full main window; a blank or limited
popout cannot be used for global discovery. Sharing the human's main window needs
explicit permission and sequential use. A missing endpoint or unsupported popout
is a prerequisite, not a reason to create a raw Teams page, expose CDP on the
network, or silently use the main window.

CDP grants control of the signed-in application to local processes. Keep the
port loopback-only and quit/relaunch Teams normally without these arguments when
finished. Do not forward the port or change enterprise policy.

The WebView2 mechanism is documented by
[Playwright](https://playwright.dev/docs/webview2). The process-scoped launch was
observed with installed Teams 26295.2101.5271.4676; other versions may enforce
different policy. This is not a Microsoft Graph integration.
