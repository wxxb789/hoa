# One CLI, several installers — keep one, prove it

## 1. Enumerate every provider of the binary

```bash
which -a <bin>
readlink -f "$(command -v <bin>)"
mise ls                                   # installed versions per tool
mise which <bin>                          # also errors loudly when the tool is installed but not active
cat ~/.config/mise/config.toml            # `rename_exe = "omp"` maps a tool to a differently named binary
bun pm ls -g                              # ~/.bun/install/global + ~/.bun/bin/<bin> symlinks
npm ls -g --depth=0                       # ~/.npm-global/bin
ls -la ~/.local/bin ~/.cargo/bin ~/.local/share/pnpm/bin
find "$HOME" /usr/local/bin /opt -maxdepth 6 -name <bin> \( -type f -o -type l \)   # or search_files(target='files')
```

Run `<path> --version` against every hit. Two sources at different versions is a finding to report
before deleting anything: PATH order decides which one the owner has actually been using.

A manager's shim (`~/.local/share/mise/shims/<bin>`) is a symlink to the manager binary itself, not a
second install — count it as the keeper's chain, not as a duplicate.

## 2. Pick the keeper (owner's stated manager wins)

When the owner names the manager, that is the keeper even if another copy is newer; note the version
skew instead of quietly upgrading. Otherwise prefer the manager that can own the most: mise covers
most standalone CLIs, and its npm backend covers JS-published ones — `mise ls-remote npm:<pkg>` to
check availability, `mise use -g npm:<pkg>@latest` to take ownership (this needs a node the backend can
use; verify before promising the migration).

## 3. Remove the rest with the owning verb

| Source | Where it lives | Remove with | Residue to re-check |
|---|---|---|---|
| mise | `~/.local/share/mise/{installs,shims}` | `mise uninstall <tool>@<v>` (+ drop the `[tools]` line) | shim, stale `latest` symlink |
| bun global | `~/.bun/install/global`, `~/.bun/bin/*` symlinks | `bun remove -g <pkg>` | `~/.bun/bin/<bin>` symlink |
| npm global | `~/.npm-global/lib/node_modules`, `~/.npm-global/bin/*` | `npm rm -g <pkg>` | bin symlink |
| standalone release | `~/.local/bin/<bin>`, `/usr/local/bin/<bin>` | `mv` into the scratch dir | nothing (space goes at prune) |

Move stray binaries to scratch rather than `rm`: the removal is reversible until scratch pruning, and
the disk still gets reclaimed. Record the version you moved so a reinstall is exact.

## 4. Verify through the keeper's chain

```bash
hash -r                                    # a stale shell hash keeps resolving the deleted path
which -a <bin>                             # exactly one hit
readlink -f "$(command -v <bin>)"          # lands in the keeper's install dir
<bin> --version                            # the kept version
```

Re-probe from a fresh login shell too, and confirm the manager still lists the tool
(`mise ls <tool>`, `bun pm ls -g`). A global package removal can also take a *different* command with
it — check `bun pm ls -g` / `npm ls -g --depth=0` before and after, and restore immediately if a
command the owner still uses disappeared.

## 5. Family mates are not duplicates

Check the `bin` map inside the candidate's `package.json` before touching it. Same project family,
different command = different tool, and uninstalling it removes a working tool the owner never asked
to lose. Known mapping on this machine:

| Package | Provides |
|---|---|
| `@oh-my-pi/pi-coding-agent` | `omp` |
| `omo-ai` | `omo` |
| `pi` (mise tool) | `pi` |

A vague "clean it up" following a message where both were listed is not consent to remove the
one you had just described as a different tool — restate it as its own question and get a yes.

If a removal turns out to be wrong, the restore is the original install verb at the original
version (`bun add -g <pkg>@<version>`), then re-verify the symlink and the package listing.
