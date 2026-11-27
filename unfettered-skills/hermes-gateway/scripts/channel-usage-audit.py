#!/usr/bin/env python3
"""Channel usage audit - live Discord metadata + last message + local session usage.

Usage:
    python3 channel-usage-audit.py <channel_id> [<channel_id> ...]
    python3 channel-usage-audit.py --all      # every channel in every guild of this bot

Answers the four questions a channel-retirement decision needs (see
references/channel-usage-audit.md): last message time/author per channel, local sessions per
profile, plus the ids/names needed to grep cron and config for references.

The bot token is read from $HERMES_HOME/.env inside this process and NEVER printed.
Stdlib only - run with the system python3. state.db is opened read-only (the gateway may hold it).
"""
import glob
import json
import os
import sqlite3
import sys
import urllib.request

HOME = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
API = "https://discord.com/api/v10"


def load_token():
    path = os.path.join(HOME, ".env")
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line.startswith(("DISCORD_BOT_TOKEN=", "DISCORD_TOKEN=")):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no DISCORD_BOT_TOKEN in %s" % path)


def api(token, path):
    req = urllib.request.Request(
        API + path,
        headers={"Authorization": "Bot " + token, "User-Agent": "hermes-channel-audit"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def session_dbs():
    out = [(os.path.join(HOME, "state.db"), "default")]
    for path in sorted(glob.glob(os.path.join(HOME, "profiles", "*", "state.db"))):
        out.append((path, path.split(os.sep + "profiles" + os.sep)[1].split(os.sep)[0]))
    return out


def local_usage(ids):
    if not ids:
        return
    print("== local sessions (state.db, read-only) ==")
    seen = False
    for db, who in session_dbs():
        if not os.path.exists(db):
            continue
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        try:
            for cid in ids:
                # thread sessions carry the parent id as a prefix
                row = con.execute(
                    "select count(*), coalesce(sum(message_count),0), max(started_at)"
                    " from sessions where chat_id like ?",
                    (cid + "%",),
                ).fetchone()
                if row and row[0]:
                    seen = True
                    print("  %-14s %s sessions=%d msgs=%d last_start=%s" % (who, cid, row[0], row[1], row[2]))
        finally:
            con.close()
    if not seen:
        print("  (no sessions for these chat ids in any profile)")


def last_message(token, cid, label):
    try:
        msgs = api(token, "/channels/%s/messages?limit=1" % cid)
    except Exception as exc:  # noqa: BLE001 - report and keep auditing the rest
        print("  %-24s ERROR %s: %s" % (label, type(exc).__name__, exc))
        return
    if not msgs:
        print("  %-24s (empty)" % label)
        return
    msg = msgs[0]
    print("  %-24s %s by %s" % (label, msg["timestamp"], (msg.get("author") or {}).get("username")))


def main(argv):
    ids = [a for a in argv if not a.startswith("-")]
    want_all = "--all" in argv
    reported = []
    if not ids and not want_all:
        raise SystemExit(__doc__)

    token = load_token()
    print("== bot ==", api(token, "/users/@me").get("username"))
    for guild in api(token, "/users/@me/guilds"):
        chans = api(token, "/guilds/%s/channels" % guild["id"])
        print("\n== guild %s (%s) ==" % (guild["name"], guild["id"]))
        for chan in sorted(chans, key=lambda c: (c.get("parent_id") or "", c.get("position", 0))):
            if not want_all and chan["id"] not in ids:
                continue
            if chan["type"] == 0:
                reported.append(chan["id"])
            print(
                "  %s type=%s parent=%s pos=%s name=%r topic=%r"
                % (
                    chan["id"],
                    chan["type"],
                    chan.get("parent_id"),
                    chan.get("position"),
                    chan["name"],
                    (chan.get("topic") or "")[:60],
                )
            )

    if reported or ids:
        print("\n== last message per channel ==")
        for cid in dict.fromkeys(reported + ids):
            last_message(token, cid, cid)
    if ids:
        print()
        local_usage(ids)
        print(
            "\nnext: grep the same ids in cron + config\n"
            "  grep -rn '<channel_id>' $HERMES_HOME/cron/jobs.json $HERMES_HOME/profiles/*/cron/jobs.json\n"
            "  grep -n '<channel_id>' $HERMES_HOME/config.yaml $HERMES_HOME/.env $HERMES_HOME/profiles/*/config.yaml $HERMES_HOME/profiles/*/.env"
        )


if __name__ == "__main__":
    main(sys.argv[1:])
