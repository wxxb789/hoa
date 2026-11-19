"""Process creation for detached POSIX runners and no-window Windows children."""

import os
import signal
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


def daemonize(argv, cwd, env, log_path):
    """Return the POSIX grandchild PID (or a pre-exec error) over a close-on-exec pipe."""
    with log_path.open("ab", buffering=0) as log, open(os.devnull, "rb") as null:
        read_fd, write_fd = os.pipe()
        try:
            first = os.fork()
        except OSError:
            os.close(read_fd)
            os.close(write_fd)
            raise
        if first == 0:
            os.close(read_fd)
            try:
                signal.signal(signal.SIGHUP, signal.SIG_IGN)
                os.setsid()
                if os.fork():
                    os._exit(0)
                os.umask(0o077)
                os.chdir(cwd)
                for target, source in enumerate((null, log, log)):
                    os.dup2(source.fileno(), target)
                os.write(write_fd, f"{os.getpid()}\n".encode("ascii"))
                os.execve(argv[0], argv, env)
            except BaseException as exc:
                os.write(write_fd, str(exc).encode("utf-8", "replace")[:2048])
            finally:
                os._exit(1)
        os.close(write_fd)
        with os.fdopen(read_fd, "rb") as pipe:
            payload = pipe.read()
        _, status = os.waitpid(first, 0)
        pid, sep, error = payload.partition(b"\n")
        if status or not sep or not pid.isdigit() or error:
            raise OSError(f"setsid: {error.decode('utf-8') or payload.decode('utf-8') or 'fork failed'}")
        return int(pid)
