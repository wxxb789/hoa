# Preview intake (excerpt)

- Schedule dates are ISO date strings; `friday_extra` is a boolean.
- Each observation gives its period, integer value, source locator and the
  source's measure label, or `unverified` when no label can be established.
  Relationship: `lower`, `higher`, `equal`, `not_comparable`, or null.
- Index: `listed`, `delisted`, or `unverified`. An attempt contains
  `client`, `date`, `path`, and integer `http_status`. Alternative is
  the confirmed public copy locator or null. Filing and filing requirement
  each use `yes`, `no`, or `unverified`.

The text renderer quotes source locators as given. Intake does not update
timestamps or autocorrect labels.
