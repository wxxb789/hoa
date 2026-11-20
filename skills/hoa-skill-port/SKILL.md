---
name: hoa-skill-port
description: >-
  Port a private runtime skill to a shared repository and make that package canonical. When home
  paths, personal identifiers, model IDs or a vendor CLI prevent reuse, externalize them into
  configuration or adapter contracts and validate before publication. Not for hoa-skill-curate.
metadata:
  revision: "7"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "make a shared repo canonical for a private skill: externalize environment values, verify destination gates, and separate live swap from publication"
  summary_zh: "将私有技能移入共享仓库作为权威副本：外置环境参数、通过目标仓库门禁，并区分运行时切换与发布"
  kind: "entry"
---


# Port a skill to a shared repository

Port the method without changing its behavior. Name the canonical repo and package before
editing; keep private instances out of the package and avoid a second copy maintained by sync.
Use hoa-skill-create to change behavior and hoa-skill-curate to trace installed provenance.

1. **Read the destination's contract.** Check placement, agent instructions, a neighboring
   artifact, ignore rules, catalog generation, and CI. Decide whether this is a shared capability
   or a repo-owned workflow. Preserve the supported behavior and public inputs/outputs.
2. **De-couple and prove it.** Apply the [five-axis checklist](references/de-coupling-checklist.md)
   to identity, paths, transport, vendor constants, and private data. Use role names, portable
   resolution, and capability contracts with a reference adapter when needed. Publish templates,
   not private instances; prove ignore coverage and block release on unexpected scan hits.
3. **Validate locally.** Follow the destination's actual gates: frontmatter, revisions, catalog
   regeneration, CI and fixtures as applicable. Never hand-edit generated files or hard-code
   the repo's current version. When delegating, bound the writes and require runnable acceptance
   commands; independently rerun them and check action and failure paths, not just dry runs.
4. **Report the port.** For each artifact record source and target, line counts, copied files,
   sections merged or removed and why, and every demoted literal with its replacement and
   default or required input. Include verification and known limits.

**Optional operations require separate authority.** Use
[runtime swap](references/runtime-swap.md) only for an authorized live cutover or drift probe:
validate before changing the loader, back up, verify exact config and loader state, and send
policy discrepancies to the owner. Use [branch publication](references/pitfalls.md) only for
authorized publication. Never push directly to the default branch or force-push.

## Configuration

Resolve these keys using [configuration.md](references/configuration.md), under the
`hoa-skill-port` config directory. Defaults are local discovery, not authority to change state.

| Key | Env | Default |
|---|---|---|
| `repo` | `PORTING_REPO` | current working tree |
| `package_root` | `PORTING_PACKAGE_ROOT` | `skills` |
| `private_dir` | `PORTING_PRIVATE_DIR` | `private` (must be ignored) |
| `ci_file` | `PORTING_CI_FILE` | `.github/workflows/ci.yml` if present, else discover |
| `catalog_command` | `PORTING_CATALOG_CMD` | none; use the repo's CI |
| `validator_command` | `PORTING_VALIDATE_CMD` | none; use the repo's CI |
| `version_command` | `PORTING_VERSION_CMD` | none; use the repo's version command |
| `base_branch` | `PORTING_BASE_BRANCH` | remote HEAD branch |
| `dirty_age_hours` | `PORTING_DIRTY_AGE_HOURS` | `24` |
