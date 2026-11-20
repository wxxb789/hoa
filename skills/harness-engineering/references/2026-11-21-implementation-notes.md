# Implementation notes (2026-11-21)

- **Mechanical extraction:** use a reproducible one-shot script with checked block boundaries
  and a clean, authorized input snapshot for each attempt; do not retry on partial output.
  Run the repo's unresolved-name, unused-import and redefinition checks. Check both qualified
  usages and `from` imports. A unittest loader error can replace a full module with one
  error entry; compare discovery, not just exit status.
- **Commit gates:** consume NUL-delimited paths, not Git's quoted display names, for allowlist
  matching. In short porcelain status the first column is the index, the second is the working
  tree. Check the gate's rejection behavior before diagnosing staged residue; do not reset
  unrelated work.
- **Draft vs promotion:** if a full gate drives authors to bypass it, keep the same core
  invariant in a lightweight draft check. Enforce the draft root and exclude promotion-only
  flags; the full gate remains mandatory on promotion.
- **Wiring evidence:** synthetic fixtures prove code paths, not live ordering. Use an isolated
  maintenance artifact and trace the real writer, gate and independent reader in order.
- **Architecture second opinion:** for a costly decision, ask a different model family to
  review a bounded evidence packet without write or inspection tools. Verify its claims against
  the repository yourself.
