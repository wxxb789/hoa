# Shift brief change history

- H-03: Added one-question handling for a missing shift time. The rota
  resolution layer was introduced later; its output is equivalent to an
  explicit time in the request.
- H-08: After an unapproved handoff reached subscribers, release approval
  became mandatory before publication. This was not a request for approval
  before generating or staging the brief.
- H-12: The driver replaced two UI handlers with a single ordered table.
  Staging and publication kept their existing action names.
- R-17: The overnight operator asked to stage a brief. The rota had supplied
  a shift time, but the reply asked for release approval and did not stage it.
