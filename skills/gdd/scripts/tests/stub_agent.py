#!/usr/bin/env python3
"""Stand-in for any agent CLI, configured only by environment:

    STUB_FIXTURE=<ndjson>   lines to print ('#' comment lines skipped); STUB_DELAY seconds between
    STUB_EXIT=<code>        exit code (default 0)
    STUB_HANG=1             after the fixture, sleep until killed
    STUB_CHILD_HOLDS_STDOUT=<seconds>   leave a grandchild holding stdout open that long
    STUB_RECORD=<json>      write argv, stdin, cwd and the DSH_* env keys present
"""
import json
import os
import subprocess
import sys
import time


def main():
    stdin = "" if sys.stdin is None else sys.stdin.read()
    if os.environ.get("STUB_RECORD"):
        with open(os.environ["STUB_RECORD"], "w", encoding="utf-8") as handle:
            json.dump({"argv": sys.argv[1:], "stdin": stdin, "cwd": os.getcwd(),
                       "env": sorted(k for k in os.environ if k.startswith("DSH_"))}, handle)
    delay = float(os.environ.get("STUB_DELAY") or 0)
    if os.environ.get("STUB_FIXTURE"):
        with open(os.environ["STUB_FIXTURE"], encoding="utf-8") as handle:
            for line in handle:
                if line.strip() and not line.startswith("#"):
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    time.sleep(delay)
    if os.environ.get("STUB_CHILD_HOLDS_STDOUT"):
        subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({float(os.environ['STUB_CHILD_HOLDS_STDOUT'])})"],
                         stdin=subprocess.DEVNULL, stdout=sys.stdout.fileno(), stderr=subprocess.DEVNULL)
    if os.environ.get("STUB_HANG"):
        time.sleep(3600)
    return int(os.environ.get("STUB_EXIT") or 0)


if __name__ == "__main__":
    sys.exit(main())
