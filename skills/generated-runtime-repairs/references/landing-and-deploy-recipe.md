# Landing a repair and deploying it to a profile runtime

Concrete command recipe behind §1–§5 of the parent skill, for a repository whose generator
materializes wrappers, scheduled jobs, and role identity into per-role profile roots. Placeholders:
`<repo>` (checkout), `<gen>` (the materializer, e.g. `tools/materialize.py`), `<lease-tool>`, `<p1>`
/ `<p2>` (target paths), `<role>`, `<state-root>` (the owning agent's persistent state), and
`<profile-root>` (where materialized profiles live). Coordinates are repo-relative unless absolute.

## A. Gate before writing

```bash
cd <repo>
git fetch --quiet
git rev-parse --short HEAD; git rev-parse --short origin/main   # equal
git status --porcelain=v1 -uall                                  # know whose other files are dirty
git diff --stat -- <path1> <path2>                               # empty: no foreign edits on targets
git diff --stat <candidate_base> HEAD -- <path1> <path2>         # empty: targets unchanged since base
git apply --check <candidate.patch>                              # applies cleanly
```

- Candidate built on an older base: apply-check passing is necessary, not sufficient. Prove the
  target files are byte-identical to the base (`git show <base>:<path> > <scratch>/base; cmp
  <scratch>/base <backup>`), because the shared HEAD moving on can otherwise silently change the
  semantic context the tests assumed. Write comparisons to real files under the scratch dir.
- No reviewer backup for a file (e.g. a test module): `git show <candidate_base>:<path>` IS the
  pre-state; record that you used it instead of asserting byte identity against nothing.

## B. Lease the exact paths

Use the repo's lease tool; the shape below is the contract, not a shipped filename:

```bash
python3 <lease-tool> acquire --bot <role> --no-worktree --ttl 3600 \
  --allow-path <p1> --allow-path <p2> --task "<one line>" --json
python3 <lease-tool> release --lease-id <id>     # flag form; positional id is rejected
python3 <lease-tool> status                     # silent = no active lease (the release proof)
```

## C. Apply, read back, check in a sandbox

```bash
git apply <candidate.patch>
grep -n '<load-bearing marker>' <p1>        # e.g. handoff guard, receipt field, forbidden CLI
python3 - <<'PY'                            # parse both YAML blocks, compare dicts — not eyeballing
import re, subprocess, yaml
def fm(t): return yaml.safe_load(re.match(r'^---\n(.*?)\n---', t, re.S).group(1))
new = open('<p1>').read()
old = subprocess.run(['git', 'show', 'HEAD:<p1>'], capture_output=True, text=True).stdout
print(fm(new) == fm(old))
PY
python3 -B <test-runner> --pattern <focused-test>
```

Sandbox checks (never run a linter in the shared checkout if it writes report files):

```bash
SB=$(mktemp -d "${TMPDIR:-/tmp}/landing-check.XXXXXX")
rsync -a --exclude=.git --exclude=__pycache__ --exclude=.agents/runtime <repo>/ $SB/
cd $SB && python3 -B <repo-validator> <args> --repo-root . --format json
python3 -B <linter>            # compare dangling count with the pre-change baseline
python3 -B <portability-check>
python3 -B <test-runner> --pattern <contract-test>
```

- A role-scoped write checker on role-definition/test files reports a violation by design — no
  runtime role owns those paths; acceptance is the generator's contract tests. Report it as expected.

## D. Commit and push explicit paths

```bash
git add -- <p1> <p2>; git diff --cached --name-status        # exactly the approved paths
git commit -m "<scope>: <one line>"                          # use the repo's required identity
git push --quiet; git fetch --quiet
git rev-parse --short HEAD; git rev-parse --short origin/main
git ls-remote origin refs/heads/main | cut -c1-12             # all three equal
```

## E. Deploy the routine to the profile runtime

Authorization for source landing does not imply runtime writes; get the runtime decision explicitly,
then:

```bash
tar czf <taskdir>/backups/profile-<role>-pre-apply-<ts>.tar.gz -C <profile-root> <role>
python3 <gen> --plan  --only <role>   # review intended writes first
python3 <gen> --apply --only <role>   # "applied N change(s)"
python3 <gen> --check --only <role>   # SILENT when healthy
```

- `--check` silence is the pass proof, not an error. Never report an empty output as failure.
- Read back the live job, not the template: parse `<profile-root>/<role>/cron/jobs.json`, find the
  job by id, assert the new prompt markers are present, and confirm non-prompt fields
  (schedule/script/timezone/silence) match the pre-write record.
- `--apply` without `--only` reconciles every role (identity, model, skill whitelist, memory mode,
  workspace anchors) and repoints stored sessions — too broad for a routine repair; it also makes
  the "N stored sessions" line expected noise, which must still be reported.
- Hand-editing `<profile-root>/<role>/cron/` or `scripts/` is never the fix; regenerate through the
  generator so `--check` stays silent.

## F. Receipt checklist

Commit + parent, numstat per file, push equality (HEAD / origin/main / ls-remote), gates run with
rc, sandbox report path, dangling-wikilink delta vs baseline, profile backup tarball, `--check`
silence, job-id read-back markers, lease release silence, and what was deliberately NOT done (no
linter `--apply`, no wiki page edits, no live slot run).
