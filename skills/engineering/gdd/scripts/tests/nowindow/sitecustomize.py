"""Fail before Windows process creation if a child could open a console."""

import os


def install():
    if os.name != "nt":
        return

    import _winapi
    import ctypes

    create_process = _winapi.CreateProcess
    if getattr(create_process, "_gdd_no_window_guard", False):
        return
    system = os.system
    has_console = ctypes.WinDLL("kernel32", use_last_error=True).GetConsoleCP

    def refuse(message):
        if log := os.environ.get("NOWINDOW_GUARD_LOG"):
            with open(log, "a", encoding="utf-8") as handle:
                print(f"pid={os.getpid()} gdd no-window guard: {message}", file=handle)
        raise OSError(f"gdd no-window guard: {message}")

    def create(application, command, process_attrs, thread_attrs, inherit, flags, *args, **kwargs):
        if flags & 0x18 or (not flags & 0x08000000 and not has_console()):
            refuse(f"unsafe CreateProcess flags {flags:#x}: {command!r}")
        return create_process(application, command, process_attrs, thread_attrs, inherit, flags, *args, **kwargs)

    def guarded_system(command):
        if not has_console():
            refuse(f"os.system without an inherited console: {command!r}")
        return system(command)

    def guarded_startfile(path, *args, **kwargs):
        refuse(f"os.startfile: {path!r}")

    create._gdd_no_window_guard = True
    _winapi.CreateProcess = create
    os.system = guarded_system
    os.startfile = guarded_startfile


install()
