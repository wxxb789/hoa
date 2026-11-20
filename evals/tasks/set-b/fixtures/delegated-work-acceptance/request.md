# North Quay intake, batch 18

The worker owns `intake/normalize.ts`, intake alias changes for this batch, and
the batch report in `audit/`. The operator owns `desk/` and retains decisions on
any pre-existing local edits. No release or commit from the acceptance desk.

The shipped command will be `normalize --apply`, not preview. The release gate
cases are `preview-list` (plan correct changes without writing), `apply-success`
(write normalized records in the test store), and `apply-rollback` (restore the
test store after a simulated write failure). Lab exports in this packet are the
only independently captured gate evidence available for desk review.

Report the missing receipt coverage for the intake checker at the batch cut.
