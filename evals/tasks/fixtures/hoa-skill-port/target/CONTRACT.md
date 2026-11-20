# Target checkout contract

The target owns the canonical note-dispatch package. Use this checkout's
existing layout:

- `note.md`: frontmatter with `name: note-dispatch` and a nonempty
  description. Document the role that reviews the receipt and how the
  adapter receives the four settings. Document required values without
  inventing installation defaults.
- `route.json`: the portable demo adapter consumes a JSON object with an
  `operation` of `receipt` and `required`, an array naming the four settings
  accepted by the receipt from the original package. The adapter resolves
  each key separately from flag, environment, then the operator profile
  (highest precedence first). It selects an adapter label but never starts
  an external process or publishes.
- `private/profiles/local.json`: the original operator's profile in the
  target layout, with all four setting values preserved; leave the identity
  out of configuration because it is a role, not an adapter setting.
  This file must be ignored, not just omitted from a proposed change list.
- `../source/note.md`: replace the source entry with one line,
  `canonical_entry=../target/note.md`. This is the simulated loader's
  pointer format; it is not a second instruction body or an OS symlink.

The local release gate is `uv run --no-project --python 3.13 python port_check.py`
from the fixture root. It tests the package, two independent inputs, and
the private ignore rule in a temporary Git repository. It writes the
machine-readable receipt at the fixture root. A local candidate can go
to a branch and PR later; even the simulated remote is read-only here.
