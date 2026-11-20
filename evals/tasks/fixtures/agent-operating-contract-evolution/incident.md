# Queue incident R-38

The peer-review worker wrote a note into the candidate when it was only asked to review. The dashboard's policy editor shows that the peer role is read-only. The dashboard launches local dry runs; the queue service takes production review requests. Both routes run the same workflow.

The owner's identity sheet says "North Desk"; the dashboard still shows the old "Intake Desk" name. That is a separate branding ticket.

Use the local Bash harness: `source ./exercise.sh before` records the baseline and snapshots the exact input text; `source ./exercise.sh after` records the final routes and changed input paths. Run them around the edit. The operations are synthetic and never write to a candidate. Only the copies of policy files in this fixture are in scope. Use Bash builtins to run the harness (do not substitute an installed review tool).
