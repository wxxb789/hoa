"""Windows transport and Ubuntu supervisor for the Pi filesystem sandbox."""

import base64
import errno
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

DISTRO = "Ubuntu-24.04"
USER = "hoa-trial"
INSTALL = PurePosixPath("/opt/hoa-pi-sandbox")
HELPER = INSTALL / "wsl_pi.py"
RUNTIME = PurePosixPath("/opt/pi")
PI = RUNTIME / "pi"
TRIAL = PurePosixPath("/trial")
PYTHON = "/usr/bin/python3"
MOUNT_NS = ("/usr/bin/unshare", "--mount", "--propagation", "private", "--")
DRIVES = {"/mnt/c": "/mnt/c/Windows/win.ini", "/mnt/q": "/mnt/q/repos/hoa/README.md"}
BOUNDARY = "Pi sandbox boundary check failed"


def wsl_command(wsl, distro, *command):
    return [str(wsl), "--distribution", distro, "--user", "root", "--cd", "/", "--exec", *map(str, command)]


class WslPi:
    def __init__(self, process, wsl, distro, cwd):
        self.process, self.wsl, self.distro, self.cwd = process, wsl, distro, cwd

    def call(self, operation, *, payload=None, timeout=30):
        command = wsl_command(self.wsl, self.distro, *MOUNT_NS, PYTHON, "-I", HELPER, operation)
        proc = self.process(command, input=json.dumps(payload), cwd=self.cwd, capture_output=True, timeout=timeout)
        if proc.returncode:
            # Do not expose subprocess stderr, which can include provider data.
            if proc.returncode == 78:
                raise OSError(BOUNDARY)
            if proc.returncode == 79:
                raise OSError("Pi provider credentials changed; rerun setup_pi_wsl.py")
            raise OSError(f"WSL Pi {operation} failed (exit {proc.returncode}); see evals/README.md")
        return json.loads(proc.stdout)

    def run(self, root, command, prompt, outputs, timeout):
        files = {path.relative_to(root).as_posix(): base64.b64encode(path.read_bytes()).decode("ascii")
                 for tree in (root / "work", root / "home/.pi/agent/skills")
                 for path in tree.rglob("*") if path.is_file()}
        result = self.call("--trial", payload={"files": files, "args": command[1:], "prompt": prompt,
                                               "outputs": sorted(outputs), "timeout": timeout}, timeout=timeout + 30)
        if result["timed_out"]:
            raise subprocess.TimeoutExpired(command, timeout)
        for name in result["outputs"]:
            if name not in outputs:
                raise OSError("WSL Pi returned an unexpected artifact")
        for name in outputs:
            path = root / "work" / name
            if name in result["outputs"]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(result["outputs"][name], validate=True))
            elif path.is_file():
                path.unlink()
        return subprocess.CompletedProcess(command, result["exit"], result["events"])


def blocked(path, check):
    try:
        check(path)
    except OSError as error:
        return error.errno in {errno.ENOENT, errno.EACCES, errno.EPERM, errno.ENOTDIR}
    return False


def read_byte(path):
    with open(path, "rb") as file:
        file.read(1)


def boundary(uid):
    # A filesystem allowlist, not a check for only the two usual drive letters.
    # In particular reject recursive binds of DrvFs or the WSL /init host bridge.
    fs_types = {line.split(" - ", 1)[1].split()[0]
                for line in Path("/proc/self/mountinfo").read_text().splitlines()}
    status = dict(line.split(":\t", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":\t" in line)
    if (uid == 0 or os.getuid() != uid or os.getgid() != uid or set(os.getgroups()) - {uid}
            or status.get("NoNewPrivs") != "1" or int(status["CapEff"], 16)
            or fs_types - {"ext4", "tmpfs", "proc", "devpts", "devtmpfs"}
            or any(Path(path).exists() for path in ("/init", "/run/WSL", "/root", "/home", "/sys"))
            or not blocked("/mnt", os.listdir)):
        raise PermissionError(BOUNDARY)
    proof = []
    for drive, file in DRIVES.items():
        if not blocked(drive, os.listdir) or not blocked(file, read_byte):
            raise PermissionError(BOUNDARY)
        proof.append(f"{drive}: list denied; file read denied")
    return proof


def copy_artifact(path):
    # Resolve each component without following links and never block on a FIFO.
    parts = PurePosixPath(path).parts
    if not parts or PurePosixPath(path).is_absolute() or ".." in parts:
        return None
    fd = None
    try:
        fd = os.open(TRIAL / "work", os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        with os.fdopen(os.open(parts[-1], os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd), "rb") as file:
            if stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                data = file.read(65537)
                if len(data) <= 65536:
                    return base64.b64encode(data).decode("ascii")
    except OSError:
        pass
    finally:
        if fd is not None:
            os.close(fd)
    return None


def inside(operation, uid):
    proof = boundary(uid)
    if operation == "--probe":
        return {"uid": uid, "drives": proof}
    if operation == "--check":
        version = subprocess.check_output([PI, "--version"], text=True).strip()
        return {"version": version}
    request = json.load(sys.stdin)
    try:
        # JSON stdout is the ephemeral session log. No Pi profile sessions are retained.
        with tempfile.TemporaryFile() as events:
            proc = subprocess.run([PI, *request["args"]], input=request["prompt"], text=True, stdout=events,
                                  env=request["env"] | dict(os.environ), stderr=subprocess.DEVNULL,
                                  timeout=request["timeout"])
            events.seek(0)
            log = events.read().decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"timed_out": True}
    outputs = {name: data for name in request["outputs"] if (data := copy_artifact(name)) is not None}
    return {"timed_out": False, "exit": proc.returncode, "events": log, "outputs": outputs}


def supervise(operation):
    import pwd

    account = pwd.getpwnam(USER)
    uid = account.pw_uid
    if not uid or account.pw_gid != uid or set(os.getgrouplist(USER, uid)) != {uid}:
        raise PermissionError(BOUNDARY)
    install = Path(INSTALL)
    config = json.loads((install / "provider.json").read_text(encoding="utf-8"))
    request = json.load(sys.stdin)
    if operation == "--check":
        if request != config["secrets"]:
            return None
        request = None
    with tempfile.TemporaryDirectory(prefix="trial-", dir=account.pw_dir) as temp:
        outer = Path(temp)
        # The account cannot rename the bind source or access this directory outside the sandbox.
        trial = outer / "profile"
        agent = trial / "home/.pi/agent"
        for directory in (agent / "skills", trial / "home/.pi/sessions", trial / "work"):
            directory.mkdir(parents=True)
        for name, data in config["files"].items():
            (agent / name).write_text(json.dumps(data), encoding="utf-8")
        if operation == "--trial":
            for name, data in request.pop("files").items():
                relative = PurePosixPath(name)
                if (".." in relative.parts or not relative.is_relative_to("work")
                        and not relative.is_relative_to("home/.pi/agent/skills")):
                    raise ValueError("unexpected Pi sandbox input path")
                path = trial / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(data, validate=True))
        for path in (trial, *trial.rglob("*")):
            os.chown(path, uid, uid)
        trial.chmod(0o700)
        # Bind just the resolver data, not its /mnt/wsl parent or host sockets.
        resolver = outer / "resolv.conf"
        shutil.copyfile("/etc/resolv.conf", resolver)
        outer.chmod(0o711)
        command = ["/usr/bin/setpriv", f"--reuid={uid}", f"--regid={uid}", "--clear-groups", "--no-new-privs",
                   "/usr/bin/bwrap", "--unshare-user", "--disable-userns", "--unshare-pid", "--unshare-ipc",
                   "--unshare-uts", "--new-session", "--die-with-parent", "--clearenv", "--proc", "/proc",
                   "--dev", "/dev", "--tmpfs", "/tmp",
                   "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
                   "--symlink", "usr/lib64", "/lib64", "--bind", str(trial), str(TRIAL)]
        for source, target in [*system_mounts(), (install / "runtime", RUNTIME), (HELPER, "/supervisor.py"),
                               (resolver, "/etc/resolv.conf"),
                               (install / "passwd", "/etc/passwd"), (install / "group", "/etc/group")]:
            command += ["--ro-bind", str(source), str(target)]
        command += ["--tmpfs", "/usr/lib/wsl", "--tmpfs", "/usr/lib/modules"]
        env = {"HOME": str(TRIAL / "home"), "USER": USER, "LOGNAME": USER, "SHELL": "/bin/bash",
               "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PI_TELEMETRY": "0", "TMPDIR": "/tmp",
               "PI_CODING_AGENT_DIR": str(TRIAL / "home/.pi/agent"),
               "PI_CODING_AGENT_SESSION_DIR": str(TRIAL / "home/.pi/sessions")}
        for key, name in {"CONFIG_HOME": "config", "CACHE_HOME": "cache", "DATA_HOME": "data",
                          "STATE_HOME": "state", "RUNTIME_DIR": "run", "CONFIG_DIRS": "system-config",
                          "DATA_DIRS": "system-data"}.items():
            path = trial / "home/xdg" / name
            path.mkdir(parents=True, exist_ok=True)
            os.chown(path.parent, uid, uid)
            os.chown(path, uid, uid)
            env[f"XDG_{key}"] = str(TRIAL / path.relative_to(trial))
        for key, value in env.items():
            command += ["--setenv", key, value]
        command += ["--chdir", str(TRIAL / "work"), PYTHON, "-I", "/supervisor.py", "--inside", operation, str(uid)]
        if operation == "--trial":
            request["env"] = config["env"]
        proc = subprocess.run(command, input=json.dumps(request), text=True, capture_output=True,
                              timeout=request["timeout"] + 10 if operation == "--trial" else 20)
        if proc.returncode:
            raise PermissionError(BOUNDARY)
        return json.loads(proc.stdout)


def system_mounts():
    # The supervisor itself runs in a private mount namespace. Nonrecursive
    # staging binds omit host submounts that Bubblewrap would otherwise carry in.
    if os.readlink("/proc/self/ns/mnt") == os.readlink("/proc/1/ns/mnt"):
        raise PermissionError(BOUNDARY)
    subprocess.run(["/usr/bin/mount", "-t", "tmpfs", "-o", "mode=0755", "tmpfs", "/run"], check=True)
    for target in ("/usr/bin", "/usr/lib", "/usr/lib64", "/etc/ssl/certs"):
        if not Path(target).is_dir():
            continue
        source = Path("/run/hoa-pi-mounts") / target.lstrip("/")
        source.mkdir(parents=True)
        subprocess.run(["/usr/bin/mount", "--bind", target, source], check=True)
        yield source, target


def setup(version):
    import hashlib
    import platform
    import pwd

    config = json.load(sys.stdin)
    install = Path(INSTALL)
    if not Path("/usr/bin/bwrap").exists():
        subprocess.run(["/usr/bin/apt-get", "install", "-y", "--no-install-recommends", "bubblewrap"],
                       check=True, stdout=sys.stderr)
    try:
        account = pwd.getpwnam(USER)
    except KeyError:
        subprocess.run(["/usr/sbin/useradd", "--create-home", "--user-group", "--shell", "/usr/sbin/nologin", USER],
                       check=True)
        account = pwd.getpwnam(USER)
    uid = account.pw_uid
    home = Path(account.pw_dir)
    if (not uid or account.pw_gid != uid or set(os.getgrouplist(USER, uid)) != {uid}
            or account.pw_shell != "/usr/sbin/nologin" or home != Path("/home") / USER or home.is_symlink()):
        raise PermissionError("Existing Pi account does not match the dedicated account contract")
    os.chown(home, 0, 0)
    home.chmod(0o711)
    install.mkdir(mode=0o755, exist_ok=True)
    runtime = install / "runtime"
    if not ((runtime / "pi").is_file() and (runtime / "version").is_file()
            and (runtime / "version").read_text().strip() == version):
        arch = {"x86_64": "x64", "aarch64": "arm64"}[platform.machine()]
        name = f"pi-linux-{arch}.tar.gz"
        release = f"https://github.com/earendil-works/pi/releases/download/v{version}"
        with tempfile.TemporaryDirectory(dir=install) as temp:
            stage = Path(temp)
            assets = []
            for filename in (name, "SHA256SUMS"):
                asset = stage / filename
                subprocess.run(["/usr/bin/curl", "-fsSL", "--retry", "2", "-o", asset, f"{release}/{filename}"],
                               check=True)
                assets.append(asset)
            archive, checksums = assets
            digest = next(line.split()[0] for line in checksums.read_text().splitlines()
                          if line.split()[-1].lstrip("*") == name)
            with archive.open("rb") as file:
                if hashlib.file_digest(file, "sha256").hexdigest() != digest:
                    raise ValueError("Pi release checksum mismatch")
            unpacked = stage / "unpacked"
            with tarfile.open(archive) as tar:
                tar.extractall(unpacked, filter="data")
            candidate, = (path for path in unpacked.rglob("pi") if path.is_file())
            candidate.parent.chmod(0o755)
            (candidate.parent / "version").write_text(version + "\n")
            if runtime.exists():
                shutil.rmtree(runtime)
            shutil.move(candidate.parent, runtime)
    for name, contents, mode in [
        ("wsl_pi.py", Path(__file__).read_bytes(), 0o644),
        ("provider.json", json.dumps(config).encode("utf-8"), 0o600),
        ("passwd", f"{USER}:x:{uid}:{uid}::{TRIAL}/home:/bin/bash\n".encode(), 0o644),
        ("group", f"{USER}:x:{uid}:\n".encode(), 0o644),
    ]:
        with tempfile.NamedTemporaryFile(dir=install, delete=False) as file:
            os.fchmod(file.fileno(), mode)
            file.write(contents)
        os.replace(file.name, install / name)


def main():
    operation = sys.argv[1]
    try:
        if operation == "--setup":
            setup(sys.argv[2])
            return 0
        result = (inside(sys.argv[2], int(sys.argv[3])) if operation == "--inside" else supervise(operation))
    except PermissionError as error:
        print(BOUNDARY if str(error) == BOUNDARY else "Pi sandbox permission check failed", file=sys.stderr)
        return 78
    if result is None:
        return 79
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
