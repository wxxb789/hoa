#!/usr/bin/env python3
"""Archive local channel transcripts to markdown - run this BEFORE deleting a channel.

Why: the Discord-side copy dies with the channel. The machine-side copy stays in each
profile's ``state.db`` (fine for FTS retrieval, unreadable for a human), so write a plain
markdown transcript first - the irreversible step then costs nothing and the owner gets a
file they can actually read.

Usage:
    python3 archive-channel-transcripts.py --out ~/claw/tasks/<date>/<task>/transcripts \
        <CHANNEL_ID>:zz-eva <CHANNEL_ID>:zz-teach-me

    # also sweep the other profiles' stores, not just the default one
    python3 archive-channel-transcripts.py --out out \
        --db "$HERMES_HOME/state.db" --db "$HERMES_HOME/profiles/eva/state.db" <CHANNEL_ID>

Notes:
  * stdlib only, runs on the system ``python3``.
  * Every DB is opened read-only via ``file:<path>?mode=ro`` - the gateway may hold the
    same file, and a read-write open can abort under its lock.
  * Threads are included: sessions match ``chat_id like '<id>%'`` (thread sessions carry a
    suffix), so a channel's per-task threads land in the same archive.
  * A missing DB or an unknown chat_id is reported and skipped, never fatal.
  * Text is capped per message (``--cap``, 0 = no cap) so one pasted log can't produce a
    100 MB file; the omission is marked inline with the dropped char count.
"""

import argparse
import datetime
import os
import sqlite3
import sys

DEFAULT_CAP = 4000
HERMES_HOME = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")


def iso(value):
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return "-"
    if ts > 1e11:  # milliseconds
        ts /= 1000.0
    try:
        return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "-"


def clip(text, cap):
    text = (text or "").strip()
    if cap and len(text) > cap:
        return text[:cap] + "\n...[truncated %d chars]" % (len(text) - cap)
    return text


def archive(db_path, chat_id, label, cap):
    """Return (markdown, session_count, message_count) for one channel in one DB."""
    uri = "file:%s?mode=ro" % os.path.abspath(os.path.expanduser(db_path))
    con = sqlite3.connect(uri, uri=True)
    try:
        sessions = con.execute(
            "select id, title, started_at, message_count from sessions"
            " where chat_id like ? order by started_at",
            (chat_id + "%",),
        ).fetchall()
        lines = []
        written = 0
        for sid, title, started, count in sessions:
            lines.append("## session %s | start %s | title %r | messages %s" % (sid, iso(started), title, count))
            for role, content, ts in con.execute(
                "select role, content, timestamp from messages where session_id=? order by id", (sid,)
            ):
                text = clip(content, cap)
                if not text:
                    continue
                lines.append("\n### [%s] %s\n\n%s" % (iso(ts), role, text))
                written += 1
            lines.append("")
    finally:
        con.close()
    header = "# %s (%s) - local transcript archive\n\nsource: %s\n" % (label, chat_id, uri)
    if not sessions:
        header += "\n(no sessions for this chat_id in this store)\n"
    return header + "\n" + "\n".join(lines), len(sessions), written


def safe_name(label, chat_id):
    cleaned = "".join(ch if (ch.isalnum() or ch in "-_.") else "-" for ch in (label or ""))
    return (cleaned or chat_id) + ".md"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Archive channel transcripts from state.db to markdown.")
    ap.add_argument("channels", nargs="+", metavar="CHAT_ID[:LABEL]",
                    help="Discord chat/channel id, optionally with a readable label")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--db", action="append", default=None,
                    help="state.db to read (repeatable); default $HERMES_HOME/state.db")
    ap.add_argument("--cap", type=int, default=DEFAULT_CAP, help="per-message char cap, 0 = none")
    args = ap.parse_args(argv)

    dbs = args.db or [os.path.join(HERMES_HOME, "state.db")]
    out_dir = os.path.expanduser(args.out)
    os.makedirs(out_dir, exist_ok=True)

    for db_path in dbs:
        expanded = os.path.expanduser(db_path)
        if not os.path.exists(expanded):
            print("SKIP db (missing): %s" % expanded)
            continue
        for spec in args.channels:
            chat_id, _, label = spec.partition(":")
            label = label or chat_id
            try:
                body, n_sessions, n_msgs = archive(expanded, chat_id, label, args.cap)
            except sqlite3.Error as exc:
                print("ERROR %s in %s: %s" % (chat_id, expanded, exc))
                continue
            path = os.path.join(out_dir, safe_name(label, chat_id))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            print("%-24s db=%-40s sessions=%3d messages=%5d bytes=%8d %s"
                  % (label, expanded, n_sessions, n_msgs, os.path.getsize(path), path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
