# Configuration

How every value that differs between installs is supplied to this skill.

Resolution order, everywhere:

```
CLI flag → environment variable → operator config file → documented default
```

- **Config file:** `$XDG_CONFIG_HOME/<skill>/config.yaml`, falling back to
  `~/.config/<skill>/config.yaml`; a flat `key: value` document.
- **Environment variable:** one variable overrides one key. Its name is
  `<SKILL_BIG_SNAKE>_<KEY_BIG_SNAKE>`, except that a key already shaped like an environment variable
  (`GDD_STATE_FILE`) is used verbatim.
- **Default:** documented in the skill's SKILL.md; "no default" is stated where the operator must
  supply the value.

A skill may, and should, read that file to customise itself. What it may not do is encode one
machine's answer as the only answer.

A skill whose scripts resolve values ships its own copy of `skill_config.py`:
`resolve(skill, key, *, flag=None, env=None, default=None, root=None)` returns the value, and
`explain(...)` also returns which step supplied it; run with `--skill <name> --key <KEY>` it prints the
value and its provenance.
