# Audit and de-duplicate instruction files

1. Confirm which files exist and which are loaded for the effective profile and
   cwd. Clarify whether the user meant an editable file or the generated system
   prompt. Verify referenced paths before flagging them as stale.
2. Record each verified conflict, duplicate or wrong-scope instruction. Ask
   before changing policy reach, persona or structure. Keep the edits surgical.
3. Back up the exact files in a scoped private location before authorized
   changes. Preserve the authoritative rule and replace copies with pointers
   that preserve any binding guardrail at its point of use.
4. Keep user identity in the user profile rather than duplicated in memory.
   Use the runtime's memory tool for managed entries. If capped, remove stale
   facts or consolidate entries before retrying.
5. Verify the removed copies and retained rules, then read back the loaded
   context in a fresh session. Report paths, backup, any unchanged conflict,
   and what the next session should do differently.
