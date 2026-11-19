"""Subprocess entry points that never allocate a visible Windows console."""

import os
import subprocess

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
NEW_GROUP = 0x00000200  # CREATE_NEW_PROCESS_GROUP
BREAKAWAY = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
IS_WINDOWS = os.name == "nt"


def _options(options):
    if IS_WINDOWS:
        flags = options.get("creationflags", 0)
        if flags & 0x18:
            raise ValueError(f"console-creating Windows process flags: {flags:#x}")
        options["creationflags"] = flags | NO_WINDOW
        if hasattr(subprocess, "STARTUPINFO"):
            startup = options.get("startupinfo") or subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            options["startupinfo"] = startup
    if options.get("text") or options.get("universal_newlines"):
        options.setdefault("encoding", "utf-8")
        options.setdefault("errors", "replace")
    return options


def _command(argv):
    if (IS_WINDOWS and not isinstance(argv, (str, bytes)) and argv[1:2] == ["/c"]
            and len(argv) >= 3 and os.path.splitext(argv[2])[1].lower() in (".cmd", ".bat")):
        # /s strips the outer quotes, leaving the quoted shim path and arguments intact.
        return subprocess.list2cmdline([argv[0], "/d", "/s", "/c"]) + ' "' + subprocess.list2cmdline(argv[2:]) + '"'
    return argv


def run(argv, **options):
    return subprocess.run(_command(argv), **_options(options))


def popen(argv, **options):
    return subprocess.Popen(_command(argv), **_options(options))
