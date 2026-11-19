# Troubleshooting script commands

Read this only after a script command from this skill fails.

## `uv` is not found

Symptom: a `uv run` command fails with "command not found", "is not recognized", or similar.

1. Confirm with `uv --version`. If it prints a version, uv is installed; the failure has another
   cause, so report the error verbatim.
2. Ask the user for approval to install uv. Never install it without explicit approval. Show the one
   official command for their OS
   ([installation docs](https://docs.astral.sh/uv/getting-started/installation/)):
   - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
     (or `winget install --id=astral-sh.uv -e`)
   - macOS and Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh` (or `brew install uv`)
3. After install, the current shell may not see uv on `PATH` yet. The installer prints the directory
   it installed to (usually `~/.local/bin`, `%USERPROFILE%\.local\bin` on Windows); check with
   `uv --version`, or with that full path, and open a new shell if needed.
4. Re-run the command that failed.

If the user declines: open the script and read its PEP 723 block (`# /// script`). With
`dependencies = []`, run it with `python3 <script> <args>` (`python` on Windows). With any
dependency listed, it cannot run without uv: stop and tell the user uv is required.

## uv cannot download Python or packages

Symptom: uv fails fetching an interpreter or a package (offline, proxy, or registry policy).
Report the error verbatim and ask the user how to proceed. Do not change indexes, proxies, or uv
configuration yourself.
