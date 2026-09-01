#!/usr/bin/env python3
"""Log work events into an Obsidian vault as Markdown."""

import argparse
import os
import re
import sys
from collections import Counter
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
COMPLETED_TASK_RE = re.compile(r"^- \[x\]\s+(.*)$")
FIELD_RE = re.compile(r"(\w+)::\s*([^|]*)")


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


def log_section(content):
    m = LOG_HEADING_RE.search(content)
    if not m:
        return ""
    after = m.end()
    if after < len(content) and content[after] == "\n":
        after += 1
    next_h2 = NEXT_H2_RE.search(content, after)
    end = next_h2.start() if next_h2 else len(content)
    return content[after:end]


def parse_fields(rest):
    fields = {}
    for key, val in FIELD_RE.findall(rest):
        fields[key] = val.strip()
    return fields


def parse_when_field(value):
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_log_file(path, file_date):
    """Return (events, unparseable_count, mismatch_warnings). Counts go under file_date."""
    content = read_text(path)
    events = []
    unparseable = 0
    warnings = []
    for raw in log_section(content).splitlines():
        line = raw.rstrip("\r")
        m = COMPLETED_TASK_RE.match(line)
        if not m:
            continue
        fields = parse_fields(m.group(1))
        event_type = fields.get("type")
        if not event_type:
            unparseable += 1
            continue
        when_raw = fields.get("when")
        if when_raw:
            when_dt = parse_when_field(when_raw)
            if when_dt is not None:
                delta = abs((when_dt.date() - file_date).days)
                if delta > 1:
                    warnings.append(
                        "warning: %s: when:: %s differs from filename by more than one day"
                        % (os.path.basename(path), when_raw)
                    )
        events.append(fields)
    return events, unparseable, warnings


def stats_markdown():
    return (
        "<!-- Generated by tracker.py. This file is overwritten on every stats run; do not edit. -->\n"
        "\n"
        "# Stats\n"
        "\n"
        "## Event counts (last 30 days)\n"
        "\n"
        "```dataview\n"
        "TABLE length(rows) AS Count\n"
        'FROM "daily"\n'
        "WHERE file.day >= date(today) - dur(30 days)\n"
        "FLATTEN file.tasks AS t\n"
        "WHERE t.completed\n"
        "GROUP BY t.type\n"
        "SORT Count DESC\n"
        "```\n"
        "\n"
        "## Study minutes by topic\n"
        "\n"
        "```dataview\n"
        "TABLE sum(rows.t.duration) AS Minutes\n"
        'FROM "daily"\n'
        "WHERE file.day >= date(today) - dur(30 days)\n"
        "FLATTEN file.tasks AS t\n"
        'WHERE t.completed AND t.type = "study"\n'
        "GROUP BY t.topic\n"
        "SORT Minutes DESC\n"
        "```\n"
    )


def cmd_stats(args):
    if args.days not in ("7", "30"):
        die("days must be 7 or 30")
    n = int(args.days)
    vault = vault_path()
    today = working_date()
    type_counts = Counter()
    study_minutes = Counter()
    sessions_without_duration = 0
    unparseable = 0

    for i in range(n):
        day = today - timedelta(days=i)
        path = os.path.join(vault, "daily", "%s.md" % day.isoformat())
        if not os.path.isfile(path):
            continue
        events, skipped, warnings = parse_log_file(path, day)
        unparseable += skipped
        for msg in warnings:
            print(msg, file=sys.stderr)
        for fields in events:
            type_counts[fields["type"]] += 1
            if fields["type"] != "study":
                continue
            topic = fields.get("topic") or ""
            dur_raw = fields.get("duration") or ""
            try:
                minutes = int(dur_raw)
            except ValueError:
                minutes = None
            if minutes is None:
                sessions_without_duration += 1
            elif topic:
                study_minutes[topic] += minutes
            else:
                study_minutes["(untagged)"] += minutes

    print("events (%s days)" % n)
    if type_counts:
        for name, count in type_counts.most_common():
            print("  %s  %s" % (name, count))
    else:
        print("  (none)")

    print("study minutes")
    if study_minutes:
        for name, mins in study_minutes.most_common():
            print("  %s  %s" % (name, mins))
    else:
        print("  (none)")
    if sessions_without_duration:
        print("  sessions without duration: %s" % sessions_without_duration)

    if unparseable:
        print("skipped %s unparseable lines" % unparseable, file=sys.stderr)

    write_text(os.path.join(vault, "Stats.md"), stats_markdown())


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

    stats_p = sub.add_parser("stats", help="Print event counts and write Stats.md")
    stats_p.add_argument("days", nargs="?", default="7")
    stats_p.set_defaults(func=cmd_stats)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
