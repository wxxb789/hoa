# Offline route replay

The exported dashboard and profile presets are in this workspace; they are not sessions. The offline stand-in has the following Bash commands, invoked from the fixture root. Each writes one receipt and prints it. Commands do not contact any service and do not modify settings.

- `source ./replay.sh PROFILE chat clarify` starts a normal one-shot session in PROFILE. The third argument specifies the inert toolset. Do not pin or override the model.
- `source ./replay.sh PROFILE session SESSION_ID` reads that profile's session row (model only).
- `source ./replay.sh PROFILE reasoning SESSION_ID` queries resolved effort for the model that actually served that session.

Profiles are `root` and `inbox`. The catalog is the adapter's picker list, not proof of what it served. The normal probe reports the provider separately from the session row.
