# Go module boundary around a carried tree

The layout that gives a carried upstream tree its own folder and its own build unit, while your code keeps
importing it — with the carried bytes untouched.

## The rule, as measured

Go's `internal/` visibility rule is decided on **import paths**, not on directories. A package whose import
path contains an `internal` element is importable by code whose import path sits inside the tree rooted at
the parent of `internal`. Because that comparison is an import-path prefix, a module declaring a **subpath**
of the carrying module's path is inside the tree; an unrelated module path is not.

Measured with the local toolchain (three scratch modules, `go build ./...`):

| Module path | Target | Result |
|---|---|---|
| `go.kenn.io/agentsview/ours` | `go.kenn.io/agentsview/internal/db` via `replace` | builds and runs |
| `example.com/unrelated` | same package, same `replace` | `use of internal package go.kenn.io/agentsview/internal/db not allowed` |

The refusal in the second row is what makes the first meaningful: without a negative control, a quiet build
cannot be told from a probe that was never run. Re-run both directions with
`../scripts/go-internal-boundary-probe.py` on any new host or toolchain.

## Layout

```
<repo>/
  agentsview/            # the carried tree, verbatim, its own module root
    go.mod               # module go.kenn.io/agentsview   (upstream's own path)
    internal/...         # upstream import statements stay valid: unchanged
    cmd/...              # upstream binaries move with it
  ccc/                   # your half, its own module
    go.mod               # module go.kenn.io/agentsview/ccc  + require/replace below
    ...
  README.md, AGENTS.md   # yours, outside the carry — no longer collide at upstream paths
```

`agentsview/go.mod` (the carry): exactly upstream's own file — `module go.kenn.io/agentsview`. Because the
module root moves *with* the tree, every path inside it (`internal/x` → `go.kenn.io/agentsview/internal/x`)
resolves as it did upstream, so no file in the carry is edited.

`ccc/go.mod` (your side):

```
module go.kenn.io/agentsview/ccc

go 1.24

require go.kenn.io/agentsview v0.0.0

replace go.kenn.io/agentsview => ../agentsview
```

The module path is deliberately a subpath of the carry's: that is what satisfies the `internal` rule. The
`replace` is the single seam — point it at a pristine clone of the pin to prove portability, at the carried
folder for normal development.

## Shapes that do not work

- **Carry in a subfolder of the same module.** Moving `internal/...` down one directory while the module
  root stays at the repo root rewrites every import path in the tree; upstream's import statements no longer
  resolve, so you must edit its bytes → byte-parity is gone.
- **Two modules with unrelated paths.** The sibling module cannot import the carry's `internal/...` at all;
  the escape hatches are editing upstream to expose a public package (a deviation, in the file the parity
  gate is proudest of) or forking import lines.
- **One module, our code anywhere.** Works, and is the cheapest shape, but the boundary is an allowlist
  rather than a directory, and the carry cannot be built against a pristine checkout on its own.

## Facts that shrink the deviation list

- **GitHub reads workflows only from the repository-root `.github/`.** A nested `.github/` inside a
  subdirectory dispatches nothing, so upstream's workflow and action files can be carried verbatim instead
  of skipped — one reason class disappears entirely.
- **Root-level owned files stop colliding.** A repository that keeps its own `README.md`, `AGENTS.md`,
  `.gitignore` or `docs/README.md` at upstream paths must list each as a deviation while both trees share a
  root; moving its files outside the carry removes the collision.
- What legitimately remains is narrow: a generated build input upstream restores from a pinned artifact, and
  a fixture whose committed bytes differ.

## Costs to state when the shape is chosen

- A whole-tree rename lands in one commit: `git log` continuity breaks across it (keep provenance in the pin
  and ledger, or add the ignore-revs file if history matters to readers).
- Two build units: a root-level build/test command no longer covers the carry — the gate and CI need both
  invocations, and the parity step becomes "the folder's contents equal the pin" instead of a path allowlist.
- Any tool that assumed root-relative paths (release scripts, packaging, the parity tool itself) is part of
  the same increment, or the first thing that breaks after the rename.
