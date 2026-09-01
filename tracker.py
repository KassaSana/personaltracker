#!/usr/bin/env python3
"""Log work events into an Obsidian vault as Markdown."""

import argparse
import os
import re
import sys
from datetime import datetime, timedelta

VALID_TYPES = (
    "commit",
    "pull_request",
    "assignment",
    "lecture",
    "slides",
    "application",
    "resume",
    "study",
)

LOG_HEADING_RE = re.compile(r"^## Log[ \t]*\r?$", re.MULTILINE)
NEXT_H2_RE = re.compile(r"^## (?!#)", re.MULTILINE)


def die(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def vault_path():
    raw = os.environ.get("VAULT_PATH")
    if not raw:
        die("VAULT_PATH is not set.")
    if not os.path.isdir(raw):
        die("VAULT_PATH does not exist: %s" % raw)
    return os.path.abspath(raw)


def now_local():
    return datetime.now()


def working_date(now=None):
    # Working day ends at 04:00, so subtract 4h before taking the date.
    if now is None:
        now = now_local()
    return (now - timedelta(hours=4)).date()


def parse_iso_date(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        die("date must be YYYY-MM-DD, got %s" % text)


def newline_of(content):
    if "\r\n" in content:
        return "\r\n"
    return "\n"


def sanitize(text):
    return text.replace("\r", " ").replace("\n", " ").replace("|", " ").strip()


def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write_text(path, content):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)


def format_log_line(event_type, when, detail, topic, duration):
    parts = [
        "type:: %s" % event_type,
        "when:: %s" % when.strftime("%Y-%m-%dT%H:%M"),
    ]
    if detail:
        parts.append("detail:: %s" % detail)
    if topic:
        parts.append("topic:: %s" % sanitize(topic))
    if duration is not None:
        parts.append("duration:: %s" % duration)
    return "- [x] " + " | ".join(parts)


def end_of_last_nonempty_line(content, start, end):
    insert_at = start
    pos = start
    while pos < end:
        nl_pos = content.find("\n", pos, end)
        if nl_pos == -1:
            line = content[pos:end].rstrip("\r")
            if line.strip():
                insert_at = end
            break
        line = content[pos:nl_pos].rstrip("\r")
        if line.strip():
            insert_at = nl_pos + 1
        pos = nl_pos + 1
    return insert_at


def insert_under_log(content, log_line):
    """Insert log_line under ## Log. Bytes before and after the insert point stay identical."""
    nl = newline_of(content) if content else "\n"
    addition = log_line + nl

    m = LOG_HEADING_RE.search(content)
    if not m:
        # Spec: append \n## Log\n at end, then the line.
        return content + "\n## Log\n" + log_line + "\n"

    after = m.end()
    if after < len(content) and content[after] == "\n":
        after += 1

    next_h2 = NEXT_H2_RE.search(content, after)
    body_end = next_h2.start() if next_h2 else len(content)
    insert_at = end_of_last_nonempty_line(content, after, body_end)

    if insert_at > 0 and content[insert_at - 1] != "\n":
        addition = nl + addition
    return content[:insert_at] + addition + content[insert_at:]


def cmd_track(args):
    event_type = args.event_type
    if event_type not in VALID_TYPES:
        die("unknown type %s; expected one of: %s" % (event_type, ", ".join(VALID_TYPES)))
    if (args.topic is not None or args.duration is not None) and event_type != "study":
        die("--topic and --duration are only valid with type study")

    vault = vault_path()
    when = now_local()
    if args.date:
        day = parse_iso_date(args.date)
    else:
        day = working_date(when)

    detail = sanitize(" ".join(args.detail)) if args.detail else ""
    log_line = format_log_line(event_type, when, detail, args.topic, args.duration)

    daily_dir = os.path.join(vault, "daily")
    path = os.path.join(daily_dir, "%s.md" % day.isoformat())

    if not os.path.exists(path):
        os.makedirs(daily_dir, exist_ok=True)
        content = "# %s\n\n## Log\n%s\n" % (day.isoformat(), log_line)
        write_text(path, content)
        return

    content = read_text(path)
    write_text(path, insert_under_log(content, log_line))


def build_parser():
    parser = argparse.ArgumentParser(prog="tracker.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    track_p = sub.add_parser("track", help="Append an event to the daily note")
    track_p.add_argument("event_type", metavar="type")
    track_p.add_argument("detail", nargs="*")
    track_p.add_argument("--date", metavar="D", help="Override working date (YYYY-MM-DD)")
    track_p.add_argument("--topic", metavar="T")
    track_p.add_argument("--duration", metavar="MIN", type=int)
    track_p.set_defaults(func=cmd_track)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
