# Release intake

T-15 (reporter priority: blocker): Language probe was red; the fallback
must be using the wrong locale. See L-03. Is that a proven regression?

T-22 (reporter priority: cosmetic): Inspect sometimes returns a handle
instead of a summary. The binder itself is still immutable. Does that
satisfy the no-write promise for both inspect consumers?

T-31 (reporter priority: blocker): Put title first to make the raw summary
easier to skim. No parse failure has been reported.
