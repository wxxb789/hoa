# Audit a delivery batch

1. Inventory source review rounds and retain stable recommendation IDs.
   Match plans by ID and scope rather than number or position. Check for
   orphaned recommendations and sub-items.
2. Read the actual plan verdict and checkpoint evidence. Process exit 0 can
   mean that a dry run completed and paused for approval. Keep completed,
   partially executed and blocked work separate.
3. For each claimed completion, verify the expected behavior at the current
   revision and target, accounting for later renames and superseding work.
   For an independent audit, provide the recommendation IDs, claim table
   and raw evidence; ask for landing and residual risk, not redesign.
4. Record each row as applied, partial, not applied, contradicted or
   unverifiable, with the evidence and reason. Recheck the auditor's
   findings and distinguish bundle defects from real gaps.
5. Report uncovered items and the exact options and costs remaining at each
   checkpoint. Carry any accepted residual risk into the durable receipt.
   Follow only the option the owner authorized; do not broaden it.
