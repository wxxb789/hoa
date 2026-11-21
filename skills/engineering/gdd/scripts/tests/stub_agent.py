#!/usr/bin/env python3
"""Stand-in for any agent CLI, configured only by environment:

    STUB_FIXTURE=<ndjson>   lines to print ('#' comment lines skipped)
    STUB_EXIT=<code>        exit code (default 0)
    STUB_HANG=1             after the fixture, sleep until killed
    STUB_DRAIN_ENDPOINT=<port or path>   leave a grandchild holding stdout until local release
    STUB_PROGRESS_RELEASE=<path>   wait for the progress retry before exiting
    STUB_RECORD=<json>      write argv, stdin, cwd and the DSH_* env keys present
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_run
import gdd_process
from gdd_test_support import publish_json


def main():
    if sys.argv[1:2] == ["--hold-stdout"]:
        pid = os.getpid()
        publish_json(os.environ["STUB_RECORD"] + ".child", [pid, agent_run.identity(pid)])
        endpoint = os.environ["STUB_DRAIN_ENDPOINT"]
        with socket.socket(socket.AF_INET if os.name == "nt" else socket.AF_UNIX) as peer:
            peer.settimeout(60)
            peer.connect(("127.0.0.1", int(endpoint)) if os.name == "nt" else endpoint)
            peer.sendall(b"READY\n")
            return 0 if peer.recv(1) in (b"R", b"") else 1
    stdin = "" if sys.stdin is None else sys.stdin.read()
    if os.environ.get("STUB_RECORD"):
        publish_json(os.environ["STUB_RECORD"], {
            "argv": sys.argv[1:], "stdin": stdin, "cwd": os.getcwd(),
            "env": sorted(k for k in os.environ if k.startswith("DSH_")),
        })
    if os.environ.get("STUB_FIXTURE"):
        with open(os.environ["STUB_FIXTURE"], encoding="utf-8") as handle:
            for line in handle:
                if line.strip() and not line.startswith("#"):
                    sys.stdout.write(line)
                    sys.stdout.flush()
    if release := os.environ.get("STUB_PROGRESS_RELEASE"):
        if not agent_run.wait_until(lambda: Path(release).exists(), 10):
            print(f"stub timed out waiting for {release}", file=sys.stderr)
            return 2
    if os.environ.get("STUB_DRAIN_ENDPOINT"):
        gdd_process.popen(
            [sys.executable, __file__, "--hold-stdout"],
            stdin=subprocess.DEVNULL, stdout=sys.stdout.fileno())
    if os.environ.get("STUB_HANG"):
        time.sleep(3600)
    return int(os.environ.get("STUB_EXIT") or 0)


if __name__ == "__main__":
    sys.exit(main())
