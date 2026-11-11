#!/usr/bin/env python3
"""Bounded writer for one launcher run's NDJSON event stream.

Usage: events-writer.py RUN_DIR < agent-events.ndjson > terminal

The agent's stdout is piped through this writer: every line is passed to stdout
unchanged (the terminal keeps the complete stream) and appended to the retained
file RUN_DIR/events.ndjson subject to the bound. A run directory carries this
file next to finalize.py so run.sh stays replayable by hand.

Configuration: OMP_RUN_EVENTS_MAX_BYTES (integer bytes, default 8388608).
The value bounds the rolling tail region; the first complete lines (up to
64 KiB, where the session event lives) are kept in addition. Unset, empty,
non-integer, zero or negative values fall back to the default with one warning
on stderr (run.sh redirects it to the run's stderr.log) and never mean unbounded.

Retained layout over the cap:

    <head lines, <= 64 KiB>
    {"type":"truncated","dropped_bytes":N,"dropped_lines":M}
    <most recent lines, <= max_bytes - marker reserve>

Under the cap the file is byte-for-byte the input stream. Sidecar counters are
written atomically to RUN_DIR/events.stats.json every 64 KiB of input and at
exit; the session id from the first `{"type":"session"}` event is persisted to
RUN_DIR/session.id as soon as it is seen.

The writer never exits non-zero because of truncation. File or terminal write
errors are reported once on stderr, the failed sink is disabled, and the
process still exits 0: with `set -o pipefail`, only the agent's exit code may
fail the run.
"""

from __future__ import annotations

import collections
import json
import os
import sys

DEFAULT_MAX_BYTES = 8 * 1024 * 1024
HEAD_LIMIT = 64 * 1024
MARKER_RESERVE = 128
SIDECAR_EVERY = 64 * 1024
SLACK_MIN = 64 * 1024
SLACK_MAX = 1024 * 1024


def _stderr(message):
    try:
        sys.stderr.write("events-writer: " + message + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


def resolve_cap():
    raw = os.environ.get("OMP_RUN_EVENTS_MAX_BYTES")
    if raw is None or not raw.strip():
        return DEFAULT_MAX_BYTES, (
            "OMP_RUN_EVENTS_MAX_BYTES is unset; using default %d bytes"
            % DEFAULT_MAX_BYTES
        )
    text = raw.strip()
    try:
        value = int(text, 10)
    except ValueError:
        return DEFAULT_MAX_BYTES, (
            "OMP_RUN_EVENTS_MAX_BYTES=%r is not an integer; using default %d bytes"
            % (raw, DEFAULT_MAX_BYTES)
        )
    if value <= 0:
        return DEFAULT_MAX_BYTES, (
            "OMP_RUN_EVENTS_MAX_BYTES=%d is not positive; using default %d bytes"
            % (value, DEFAULT_MAX_BYTES)
        )
    return value, None


class Writer:
    def __init__(self, run_dir, max_bytes, defaulted=False):
        self.run_dir = run_dir
        self.max_bytes = max_bytes
        self.defaulted = defaulted
        self.events_path = os.path.join(run_dir, "events.ndjson")
        self.stats_path = os.path.join(run_dir, "events.stats.json")
        self.session_path = os.path.join(run_dir, "session.id")
        self.tail_budget = max(0, max_bytes - MARKER_RESERVE)
        self.slack = max(SLACK_MIN, min(SLACK_MAX, max_bytes // 8))
        self.head = []
        self.head_bytes = 0
        self.head_closed = False
        self.tail = collections.deque()
        self.tail_bytes = 0
        self.total_bytes = 0
        self.total_lines = 0
        self.dropped_bytes = 0
        self.dropped_lines = 0
        self.session_id = ""
        self.disk_bytes = 0
        self.last_stats_total = 0
        self.truncated = False
        self.file_ok = True
        self.stdout_ok = True
        self.warned_file = False
        self.warned_stats = False
        self.warned_terminal = False
        self.events = None
        try:
            # Truncate like tee: a replay of run.sh in the same run directory
            # replaces the log instead of mixing two streams into one file.
            self.events = open(self.events_path, "wb", buffering=0)
        except OSError as exc:
            self._file_error(exc)

    # -- sinks -----------------------------------------------------------

    def _file_error(self, exc):
        if not self.warned_file:
            _stderr("cannot write %s: %s; continuing without a bounded file"
                    % (self.events_path, exc))
            self.warned_file = True
        self.file_ok = False

    def _write_file(self, data):
        if not self.file_ok:
            return
        start = self.disk_bytes
        try:
            view = memoryview(data)
            while view:
                written = self.events.write(view)
                if not written:
                    raise OSError("short write")
                view = view[written:]
            self.disk_bytes += len(data)
        except (OSError, ValueError, AttributeError) as exc:
            self._file_error(exc)
            # A short write followed by an error (for example ENOSPC) must not
            # leave half a line: cut the file back to the last complete one.
            try:
                self.events.truncate(start)
            except (OSError, ValueError, AttributeError):
                pass

    def _append(self, line):
        self._write_file(line)

    def _marker(self):
        payload = {
            "type": "truncated",
            "dropped_bytes": self.dropped_bytes,
            "dropped_lines": self.dropped_lines,
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")

    def _compact(self):
        if not self.file_ok:
            return
        marker = self._marker() if self.dropped_lines else b""
        content = b"".join(self.head) + marker + b"".join(self.tail)
        tmp = "%s.tmp.%d" % (self.events_path, os.getpid())
        try:
            if self.events is not None:
                self.events.close()
                self.events = None
            with open(tmp, "wb") as handle:
                handle.write(content)
            os.replace(tmp, self.events_path)
        except OSError as exc:
            self._file_error(exc)
            try:
                os.unlink(tmp)
            except OSError:
                pass
        finally:
            try:
                self.events = open(self.events_path, "ab", buffering=0)
            except OSError as exc:
                self._file_error(exc)
        if self.file_ok:
            self.disk_bytes = len(content)

    def _passthrough(self, line):
        if not self.stdout_ok:
            return
        try:
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
        except (OSError, ValueError, AttributeError) as exc:
            if not self.warned_terminal:
                _stderr("terminal write failed: %s; continuing to bound the file"
                        % exc)
                self.warned_terminal = True
            self.stdout_ok = False

    def _write_session(self):
        if not self.session_id:
            return
        try:
            current = None
            try:
                with open(self.session_path, encoding="utf-8") as handle:
                    current = handle.read().strip()
            except OSError:
                pass
            if current == self.session_id:
                return
            tmp = "%s.tmp.%d" % (self.session_path, os.getpid())
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(self.session_id + "\n")
            os.replace(tmp, self.session_path)
        except OSError as exc:
            _stderr("cannot write %s: %s" % (self.session_path, exc))

    def _note_session(self, line):
        if self.session_id or b'"session"' not in line:
            return
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(event, dict) and event.get("type") == "session":
            sid = event.get("id")
            if isinstance(sid, str) and sid:
                self.session_id = sid
                self._write_session()

    def _write_stats(self):
        retained = 0
        try:
            retained = os.path.getsize(self.events_path)
        except OSError:
            pass
        stats = {
            "max_bytes": self.max_bytes,
            "head_limit_bytes": HEAD_LIMIT,
            "head_bytes": self.head_bytes,
            "total_bytes": self.total_bytes,
            "total_lines": self.total_lines,
            "retained_bytes": retained,
            "dropped_bytes": self.dropped_bytes,
            "dropped_lines": self.dropped_lines,
            "truncated": self.dropped_lines > 0,
            "defaulted": self.defaulted,
            "session_id": self.session_id,
        }
        tmp = "%s.tmp.%d" % (self.stats_path, os.getpid())
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(stats, handle, separators=(",", ":"), ensure_ascii=False)
                handle.write("\n")
            os.replace(tmp, self.stats_path)
            self.last_stats_total = self.total_bytes
        except OSError as exc:
            if not self.warned_stats:
                _stderr("cannot write %s: %s" % (self.stats_path, exc))
                self.warned_stats = True

    # -- stream ----------------------------------------------------------

    def feed(self, line):
        self.total_bytes += len(line)
        self.total_lines += 1
        self._note_session(line)
        self._passthrough(line)
        if not self.file_ok:
            return
        if not self.head_closed and (
            not self.head or self.head_bytes + len(line) <= HEAD_LIMIT
        ):
            self.head.append(line)
            self.head_bytes += len(line)
            if self.head_bytes >= HEAD_LIMIT:
                self.head_closed = True
            self._append(line)
        else:
            self.head_closed = True
            self.tail.append(line)
            self.tail_bytes += len(line)
            while self.tail_bytes > self.tail_budget and self.tail:
                dropped = self.tail.popleft()
                self.tail_bytes -= len(dropped)
                self.dropped_bytes += len(dropped)
                self.dropped_lines += 1
            if self.dropped_lines and not self.truncated:
                self.truncated = True
                self._compact()
            else:
                self._append(line)
            if self.truncated and self.disk_bytes > (
                self.head_bytes + self.max_bytes + self.slack
            ):
                self._compact()
        if self.total_bytes - self.last_stats_total >= SIDECAR_EVERY:
            self._write_stats()

    def finish(self):
        if self.file_ok and self.dropped_lines:
            self._compact()
        if self.events is not None:
            try:
                self.events.close()
            except OSError:
                pass
            self.events = None
        self._write_stats()


def _only_passthrough():
    out = getattr(sys.stdout, "buffer", None)
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            break
        if out is not None:
            try:
                out.write(line)
                out.flush()
            except (OSError, ValueError):
                out = None
    return 0


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: events-writer.py RUN_DIR\n")
        return 2
    run_dir = os.path.abspath(argv[1])
    try:
        os.makedirs(run_dir, exist_ok=True)
    except OSError as exc:
        _stderr("cannot create %s: %s; passing the stream through only"
                % (run_dir, exc))
        return _only_passthrough()

    max_bytes, warning = resolve_cap()
    if warning:
        _stderr(warning)

    writer = Writer(run_dir, max_bytes, defaulted=warning is not None)
    try:
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                break
            writer.feed(line)
    except KeyboardInterrupt:
        pass
    finally:
        writer.finish()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
