# Duplicated PATH entries — find the source, then make rc idempotent

Symptom: `which -a <bin>` prints the same path twice; `echo "$PATH" | tr ':' '\n'` repeats dirs.

## Two independent causes — separate them before editing any rc file

1. **The rc file is sourced twice.** Login+interactive bash reads `~/.profile`, which sources
   `~/.bashrc`, and then bash sources `~/.bashrc` again for the interactive shell. Every unguarded
   `export PATH="x:$PATH"` therefore runs twice.
2. **The inherited environment already carries the dir** (agent runtime, gateway, systemd unit,
   tmux/ssh session). No rc edit can remove those copies; rc can only stop adding more.

Baseline before editing — count on a shell that reads no rc, then compare:

```bash
bash --noprofile --norc -c 'printf %s "$PATH" | tr : "\n" | grep -cx "$HOME/.local/bin"'
bash -lic              -c 'printf %s "$PATH" | tr : "\n" | grep -cx "$HOME/.local/bin"'
```

Equal counts mean the duplication is inherited and no rc change will fix it — say where it comes from
and leave the runtime alone. A higher count in `bash -lic` is rc-attributable and worth fixing.

## Fix: guard the re-source, then make prepends idempotent

Back up first: `cp -p ~/.bashrc ~/.bashrc.bak-$(date +%Y%m%d-%H%M%S)`.

After the non-interactive `return` block near the top of `~/.bashrc`:

```bash
if [ -n "${__BASHRC_SOURCED:-}" ]; then
    return 0 2>/dev/null || exit 0      # allows the file being executed instead of sourced
fi
__BASHRC_SOURCED=1
```

Then route every dir-add through one helper instead of raw prepends:

```bash
path_add() { case ":$PATH:" in *":$1:"*) ;; *) PATH="$1:$PATH" ;; esac; }
path_add "$HOME/.npm-global/bin"
path_add "$BUN_INSTALL/bin"
```

Also guard `~/.profile`: its `$HOME/.local/bin` block prepends unconditionally *after* sourcing
`.bashrc`, so the same dir lands twice even with the guard above.

```bash
case ":$PATH:" in
    *:"$HOME/.local/bin":*) ;;
    *) PATH="$HOME/.local/bin:$PATH" ;;
esac
```

Leave alone: pnpm's generated block is already case-guarded; `nvm use` re-prepends its own bin dir by
design — accept that one duplicate rather than editing `nvm.sh`.

## Verify

```bash
bash -n ~/.bashrc
bash -lic 'echo "$PATH" | tr : "\n" | sort | uniq -d'
```

Report each remaining duplicate with its origin (rc vs inherited) instead of chasing zero. Preserve
PATH order semantics when converting a prepend pair: `PATH="$A:$B:$PATH"` becomes `path_add "$B"` then
`path_add "$A"`, otherwise the lookup priority of two overlapping dirs silently flips.
