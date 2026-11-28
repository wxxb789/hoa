#!/usr/bin/env python3
"""Count Hermes session messages by platform source / role / day.

Answers questions like "how many messages came in via Feishu today?" by reading
the local session DB directly. Hermes does NOT expose a per-platform inbox feed
to the running agent session, but every processed message is persisted in
~/.hermes/state.db tagged with sessions.source ('feishu','discord','telegram',
'cli','cron'). This script aggregates that.

Why Python, not the sqlite3 CLI: the `sqlite3` binary is frequently NOT installed
on the host, while Python's stdlib `sqlite3` module always works. Do not reach for
`sqlite3 file.db "..."` — it will silently print nothing / "command not found".

The DB is opened read-only (mode=ro) so this is always a Green action.

Usage:
  python3 session-source-stats.py                  # today (CST), all profiles' state.db
  python3 session-source-stats.py --source feishu  # filter one platform, list incoming user msgs
  python3 session-source-stats.py --days 7         # last 7 days
  python3 session-source-stats.py --db ~/.hermes/state.db   # one specific DB

Key schema facts (state.db):
  sessions(id, source, user_id, started_at, title, ...)
  messages(id, session_id->sessions.id, role, content, timestamp REAL epoch, ...)
  roles seen: 'user' (incoming from owner), 'assistant' (agent reply),
              'tool' (tool calls), 'session_meta' (system markers)
  => "messages sent IN by the user" == role='user'. The raw session message
     count is much higher because it includes assistant+tool+meta rows.
  Feishu/all-platform rows live in the DEFAULT profile's ~/.hermes/state.db, even
  though per-platform profiles exist; the per-profile state.db files are usually empty.
"""
import argparse, datetime, glob, os, sqlite3, sys

CST = datetime.timezone(datetime.timedelta(hours=8))  # Asia/Shanghai, owner TZ


def discover_dbs():
    root = os.path.expanduser(os.environ.get("HERMES_ROOT", os.environ.get("HERMES_HOME", "~/.hermes")))
    dbs = [os.path.join(root, "state.db")]
    dbs += sorted(glob.glob(os.path.join(root, "profiles/*/state.db")))
    return [d for d in dbs if os.path.exists(d)]


def window(days):
    now = datetime.datetime.now(CST)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start -= datetime.timedelta(days=days - 1)
    return start.timestamp(), now.timestamp(), start, now


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="filter one platform, e.g. feishu/discord/telegram")
    ap.add_argument("--days", type=int, default=1, help="window size in days (default 1 = today)")
    ap.add_argument("--db", help="query one specific DB path instead of auto-discovering")
    args = ap.parse_args()

    start_ts, end_ts, start_dt, now_dt = window(args.days)
    print(f"Window CST: {start_dt:%Y-%m-%d %H:%M} -> {now_dt:%Y-%m-%d %H:%M}\n")

    dbs = [os.path.expanduser(args.db)] if args.db else discover_dbs()
    for db in dbs:
        label = db.replace(os.path.expanduser("~"), "~")
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            cur = con.cursor()
        except Exception as e:
            print(f"### {label}  OPEN ERROR: {e}\n")
            continue

        # source x role breakdown in window
        q = """
            SELECT s.source, m.role, COUNT(*)
            FROM messages m JOIN sessions s ON m.session_id = s.id
            WHERE m.timestamp >= ? AND m.timestamp < ?
            {src}
            GROUP BY s.source, m.role
            ORDER BY s.source, COUNT(*) DESC
        """.format(src="AND s.source = ?" if args.source else "")
        params = [start_ts, end_ts] + ([args.source] if args.source else [])
        cur.execute(q, params)
        rows = cur.fetchall()
        if not rows:
            con.close()
            continue

        print(f"### {label}")
        cur_src = None
        for src, role, n in rows:
            if src != cur_src:
                print(f"  [{src}]")
                cur_src = src
            print(f"      {role:14s} {n}")

        # incoming (user) total per source — the number people usually mean
        cur.execute(
            "SELECT s.source, COUNT(*) FROM messages m JOIN sessions s ON m.session_id=s.id "
            "WHERE m.role='user' AND m.timestamp>=? AND m.timestamp<? {src} GROUP BY s.source".format(
                src="AND s.source = ?" if args.source else ""),
            params,
        )
        print("  -- incoming (role=user) per source --")
        for src, n in cur.fetchall():
            print(f"      {src:14s} {n}")

        # if a single source was requested, list each incoming message
        if args.source:
            cur.execute(
                "SELECT m.timestamp, m.content FROM messages m JOIN sessions s ON m.session_id=s.id "
                "WHERE s.source=? AND m.role='user' AND m.timestamp>=? AND m.timestamp<? ORDER BY m.timestamp",
                [args.source, start_ts, end_ts],
            )
            print(f"  -- incoming {args.source} messages --")
            for ts, content in cur.fetchall():
                t = datetime.datetime.fromtimestamp(ts, CST).strftime("%m-%d %H:%M")
                c = (content or "").strip().replace("\n", " ")
                if len(c) > 90:
                    c = c[:90] + "…"
                print(f"      [{t}] {c}")
        con.close()
        print()


if __name__ == "__main__":
    main()
