# Block templates

Fill every value before handing a block over; the operator should change nothing. Replace the
example names in these skeletons with the real ones, not with placeholders.

## PowerShell (Windows PowerShell 5.1 or 7, ConstrainedLanguage-safe)

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $work = "$HOME\ops\deploy-2026-11-20"
    $ctx  = 'prod-cluster-admin'
    $env:KUBECONFIG = "$work\prod-cluster.kubeconfig"
    Set-Location $work

    # Gates: identity, artifacts, target.
    az account show --subscription 'expected-subscription-id' --query "{sub:id,tenant:tenantId,user:user.name}" -o json
    if ((Get-FileHash -Algorithm SHA256 .\Invoke-Change.ps1).Hash -ne 'EXPECTEDHASH') { throw 'Stop: script hash mismatch.' }
    if ((kubectl --context $ctx config current-context) -ne $ctx) { throw 'Stop: wrong kube context.' }

    $run = "$work\plan-$(Get-Date -Format yyyyMMdd-HHmmss)"
    "== Evidence: $run"
    try { .\Invoke-Change.ps1 -Context $ctx -OutputDirectory $run }
    finally { '== summary'; Get-Content "$run\session.json" }
}
```

The execute block is the same text with the execute switch added and `plan-` renamed `exec-`.

## Read-only diagnosis (any outcome you did not predict)

```powershell
& {
    $ErrorActionPreference = 'Continue'   # every probe runs even if one fails
    '== 1. live object'
    az rest --method get --url 'https://management.example/resource?api-version=2025-01-01' --query '{state:properties.provisioningState,error:properties.errorInfo}' -o json
    '== 2. dependent workload'
    kubectl --context 'prod-cluster-admin' get deploy,pods -n target-namespace -o wide
}
```

## Mutation with a compare-and-set guard and readback

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $old = 'expected-current-value'
    $new = 'desired-value'
    $current = az some-resource show --name example --query field -o tsv
    if ($current -cne $old) { throw "Stop: unexpected current value: $current" }
    az some-resource update --name example --field $new -o none
    '== readback'
    az some-resource show --name example --query '{field:field}' -o json
}
```

## bash (jump host)

```bash
(
  set -euo pipefail
  umask 077
  KUBE_CONTEXT=prod-cluster-admin
  WORK="$(mktemp -d "$HOME/deploy.XXXXXX")"
  echo "expected-sha256  $HOME/bundle.tar.gz" | sha256sum -c -
  kubectl --context "$KUBE_CONTEXT" auth whoami
  tar -xzf "$HOME/bundle.tar.gz" -C "$WORK"
  rc=0
  bash "$WORK/deploy.sh" preflight --context "$KUBE_CONTEXT" --evidence-dir "$WORK/evidence" || rc=$?
  echo "preflight exit=$rc"
)
```

State above each block: the host, read-only or mutating, the expected output (counts, named items),
and "if anything else appears, do not rerun; paste the output".
