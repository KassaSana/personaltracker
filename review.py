#!/usr/bin/env python3
"""`t review`: last week's numbers, pre-filled, with three prompts you answer by hand.

Numbers only change behavior if you read them on a schedule. Unlike Stats.md and
Dashboard.md, a review is written once and never regenerated: it holds your
handwriting, so an existing file is reported and left alone.

Owns no numbers of its own. Every figure here comes from tracker's report
functions, so a review cannot disagree with `t stats`.
"""

import os
from datetime import timedelta

import tracker

# The reviewed week plus this many weeks of context in the table.
CONTEXT_WEEKS = 4
PROMPTS = ("What worked", "What slipped", "One change next week")


def review_week_start(today, week=None):
    """Monday of the week under review -- last week by default, since you review on Sunday."""
    if week is not None:
        return tracker.week_start(week)
    return tracker.week_start(today) - timedelta(weeks=1)


def review_path(vault, start):
    year, week_no, _weekday = start.isocalendar()
    return os.path.join(vault, "reviews", "%04d-W%02d.md" % (year, week_no))


def review_markdown(events, start, today):
    """The week's numbers, pre-filled, followed by the three prompts."""
    end = start + timedelta(days=6)
    history = [f for f in events if f["_date"] <= end]
    window = [f for f in history if f["_date"] >= start - timedelta(weeks=CONTEXT_WEEKS)]
    buckets = tracker.weekly_buckets(window, CONTEXT_WEEKS + 1, end)

    year, week_no, _weekday = start.isocalendar()
    lines = [
        "# Review %04d-W%02d" % (year, week_no),
        "",
        # ASCII only: this string is printed to consoles whose codepage is not UTF-8.
        "%s to %s. Numbers generated %s; the prompts below are yours to answer."
        % (start.isoformat(), end.isoformat(), today.isoformat()),
        "",
        "## Numbers",
        "",
    ]
    headers, rows = tracker.weekly_report(buckets)
    lines += tracker.markdown_table(headers, rows)
    lines += ["", "Logged %d of 7 days." % buckets[0]["days"]]
    if buckets[0]["days"] < tracker.MIN_LOGGED_DAYS:
        lines.append(
            "Fewer than %d logged days: read this week as insufficient data, not decline."
            % tracker.MIN_LOGGED_DAYS
        )
    lines.append("")

    diff = tracker.difficulty_report(buckets)
    if diff:
        lines += ["## Leetcode difficulty mix", ""] + tracker.markdown_table(*diff) + [""]

    lines += ["## Streaks", ""]
    lines += ["- " + ln.strip() for ln in tracker.streak_lines(history, end)]
    lines.append("")

    pipeline = tracker.pipeline_report(history)
    if pipeline:
        lines += ["## Application pipeline", ""] + tracker.markdown_table(*pipeline) + [""]

    for prompt in PROMPTS:
        lines += ["## %s" % prompt, "", "- ", ""]
    return "\n".join(lines)


def cmd_review(args):
    vault = tracker.vault_path()
    today = tracker.working_date()
    start = review_week_start(today, tracker.parse_iso_date(args.week) if args.week else None)

    events, _unparseable = tracker.load_events(vault)
    body = review_markdown(events, start, today)

    if args.print_only:
        print(body)
        return

    path = review_path(vault, start)
    if os.path.exists(path):
        print("review already exists, leaving it alone: %s" % path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tracker.write_text(path, body + "\n")
    print("wrote %s" % path)
