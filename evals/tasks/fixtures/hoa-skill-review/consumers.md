# Consumer examples and sink contract

| Consumer | Mode | Binder | Destination |
|---|---|---|---|
| C-02 | inspect | binder-x | omitted |
| C-05 | inspect | binder-x | out/binder-x.json |
| C-09 | refresh | binder-x | omitted |

For these calls the destination, if provided, is an unused path in the
caller's workspace. Output Sink serializes the payload, creates a new file
at the destination, and then returns a handle. Returning a handle without
that file is an error. It never writes under the binder directory.

The summary decoder addresses keys by name, not position.
