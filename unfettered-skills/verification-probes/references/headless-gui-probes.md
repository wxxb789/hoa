# Probing a real desktop application on a headless host

Use when the claim under test belongs to a desktop app plus a local bridge (an add-on exposing an HTTP
API, a plugin, a daemon) and no human is sitting at a display. The point is to exercise the real
application, not a stub of it, and then read the landed state back through the app's own API.

## Display and window plumbing

```bash
Xvfb :99 -screen 0 1280x900x24 -ac -nolisten tcp &     # -ac: without it, local clients hit "Authorization required"
export DISPLAY=:99
```

- **Qt apps abort without the xcb cursor library**: `qt.qpa.plugin: Could not load the Qt platform plugin
  "xcb"` means install the Qt xcb set (`libxcb-cursor0` plus the usual icccm/image/keysyms/randr/shape/
  xfixes set) before blaming the app. Treat it as a dependency of the probe.
- **With no window manager, X focus is `PointerRoot`**: keystrokes go to the window under the *pointer*.
  `xdotool windowactivate` fails (`_NET_ACTIVE_WINDOW` unsupported) — move the pointer into the dialog
  first (`xdotool mousemove X Y`), then `xdotool click 1` or `xdotool key <kbd>`. Clicking the computed
  centre of the button beats sending Return to a focus you cannot see.
- **Never `head` a launcher binary** to inspect it: an installer/launcher is often a compiled ELF and you
  dump a page of escaped garbage into the transcript. Use `file`, `ldd | grep 'not found'`, or the app's
  own `--help`.

## Seeing what the app shows

```bash
ffmpeg -loglevel error -y -f x11grab -video_size 1280x900 -i :99 -frames:v 1 shot.png
ffmpeg -loglevel error -y -i shot.png -q:v 2 shot.jpg          # hand the JPEG to the image tool
```

Re-encode to JPEG before an image-analysis tool sees it; a raw x11grab PNG can come back as "not a
recognized image" while the same frame as JPEG is accepted. Read the dialog text from the image, then
compute click coordinates by scaling the model's estimate against the real window geometry (`xdotool
getwindowgeometry --shell ID`) — an image model reports coordinates in its own downscaled frame.

## First-run and per-profile state

- A GUI app's first launch shows language/profile/consent dialogs and only *then* loads add-ons and opens
  its API port. Poll the API rather than sleeping a fixed time, and keep polling after the process exists:
  "a window exists" is not "the bridge is listening".
- A command-line profile selector usually requires the profile to exist already; let the app create it once
  through its own dialogs instead of inventing its on-disk format.
- A crashed run leaves lock/journal files that produce `database is locked` on the next start. Remove the
  app's metadata database together with its `-journal`/`-wal` siblings to get a clean first run again.
- A release archive may wrap an inner archive (`*.tar.zst` containing a `*.tar` whose payload sits next to
  the launcher). Extract both layers; a missing bundled runtime surfaces as
  `error while loading shared libraries: libpythonX.Y.so`.
- An add-on whose published download endpoint 404s can be built from its source tree: copy the add-on's
  payload directory into the app's `addons*` directory. Record in the evidence that the add-on came from
  source — version-sensitive behaviour then belongs to the finding, not to the product.

## Shut down deliberately

Kill the app before the display, and treat the app's exit code after a teardown as noise: an X connection
broken under a running GUI ends in a segfault or abort that says nothing about the verification. Report
what ran and what the API answered, stop the app and the X server, then write the evidence — the next probe
should not be competing for memory.

## What the app-specific half must do

Whatever the bridge exposes, the verdict comes from the bridge's own read calls, never from the product's
summary line: ask for the object by identifier, check the field the claim is about
(location / collection / label), and add a control call made directly against the bridge to attribute any
mismatch. See §10 of the parent skill.
