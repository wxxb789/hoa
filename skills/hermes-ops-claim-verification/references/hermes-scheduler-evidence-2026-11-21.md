# Hermes scheduler evidence (2026-11-21)

Resolve the effective profile data root first. On installs with Markdown cron
receipts, inspect `cron/output/<job-id>/<timestamp>.md` below that root for
stdout, stderr and `Script exited with code N`. Match the receipt to the trigger;
the agent log may carry only a prompt summary. If the install differs, inspect
its scheduler implementation rather than assuming this layout.

When a script gates agent invocation, `wake=false, skipping agent run` records
a skip, not a payload health verdict. A job output delivered to the agent may
be actionable work or an error. Read the payload status and gate decision
before interpreting either event.
