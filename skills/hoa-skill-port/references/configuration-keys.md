# Skill porting configuration keys

| Key | Env | Default |
|---|---|---|
| `repo` | `PORTING_REPO` | current working tree |
| `package_root` | `PORTING_PACKAGE_ROOT` | `skills` |
| `private_dir` | `PORTING_PRIVATE_DIR` | `private` (must be git-ignored) |
| `ci_file` | `PORTING_CI_FILE` | `.github/workflows/ci.yml` if present, else discover |
| `catalog_command` | `PORTING_CATALOG_CMD` | none — read it from the repo's CI |
| `validator_command` | `PORTING_VALIDATE_CMD` | none — read it from the repo's CI |
| `version_command` | `PORTING_VERSION_CMD` | none — the repo's own version command |
| `base_branch` | `PORTING_BASE_BRANCH` | the remote HEAD branch |
| `dirty_age_hours` | `PORTING_DIRTY_AGE_HOURS` | `24` |

No key in this table is a repo name. These keys resolve in the order in
[configuration.md](configuration.md); the file is
`$XDG_CONFIG_HOME/hoa-skill-port/config.yaml` (fallback `~/.config/...`).
