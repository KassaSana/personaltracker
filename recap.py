#!/usr/bin/env python3
"""`t recap`: import facts, confirm uncertain evidence, and summarize one day."""

import hashlib
import os
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime

import suggest
import sync as git_sync
import tracker
import watch


def day_start(day):
    return datetime(day.year, day.month, day.day, 4, 0)


def sync_day(vault, day, dry_run=False):
    """Import local Git facts for one working day; absence is non-fatal to recap."""
    if not shutil.which("git"):
        return 0, 0, "git is not installed; exact Git import skipped"
    repos = git_sync.resolve_repos(None, None)
    if not repos:
        return 0, 0, "TRACKER_REPOS is empty; exact Git import skipped"
    by_day, scanned = git_sync.collect_commit_lines(repos, day, None)
    selected = {day: by_day.get(day, [])} if by_day.get(day) else {}
    if not scanned:
        return 0, 0, "no configured Git repository could be read"
    added, skipped = tracker.append_commit_lines(vault, selected, dry_run)
    return added, skipped, ""


def proposals_for_day(vault, day, databases=None):
    start = day_start(day)
    found = suggest.gather(start, databases)
    return suggest.already_logged(vault, [p for p in found if p["day"] == day])


def events_for_day(vault, day):
    path = tracker.daily_path(vault, day)
    if not os.path.isfile(path):
        return []
    events, _skipped, _warnings = tracker.parse_log_file(path, day)
    for fields in events:
        fields["_date"] = day
    return events


def summary_lines(events):
    counts = Counter(f["type"] for f in events if f["type"] != tracker.TIME_TYPE)
    lines = ["accomplishments"]
    if counts:
        lines += ["  %-14s %d" % pair for pair in counts.most_common()]
    else:
        lines.append("  (none yet)")
    report = watch.time_report(events)
    lines += ["", "measured time"]
    if report:
        lines += ["  " + line for line in tracker.render_table(*report)]
    else:
        lines.append("  (none)")
    return lines


def learning_record(day, detail, when=None):
    detail = tracker.sanitize(detail)
    if not detail:
        return None
    when = when or tracker.now_local()
    digest = hashlib.sha1((day.isoformat() + "\0" + detail.lower()).encode("utf-8")).hexdigest()[:16]
    ident = "learning-%s-%s" % (day.isoformat(), digest)
    line = tracker.format_log_line(
        "learning", when, detail, None, None, [("id", ident), ("src", "recap")]
    )
    return ident, line


def write_learning(vault, day, detail, dry_run=False):
    record = learning_record(day, detail)
    if record is None:
        return 0, 0
    ident, line = record
    by_day = defaultdict(list)
    by_day[day].append((tracker.now_local(), ident, line))
    return tracker.append_commit_lines(vault, by_day, dry_run)


def apply_proposals(vault, proposals, dry_run=False):
    return tracker.append_commit_lines(vault, suggest.to_log_lines(proposals), dry_run)


def cmd_recap(args):
    vault = tracker.vault_path()
    day = tracker.parse_iso_date(args.date) if args.date else tracker.working_date()
    print("recap %s" % day.isoformat())

    git_added, git_skipped, warning = sync_day(vault, day, args.dry_run)
    if warning:
        print("warning: %s" % warning, file=sys.stderr)
    else:
        verb = "would import" if args.dry_run else "imported"
        print("%s %d Git event(s); %d already present" % (verb, git_added, git_skipped))

    proposals = proposals_for_day(vault, day)
    tracker.print_lines(summary_lines(events_for_day(vault, day)))
    if proposals:
        print("")
        print("confirmable evidence")
        tracker.print_lines("  " + line for line in suggest.render(proposals))
        print("  Opening a page is evidence, not proof. Pick only completed work.")

    if args.dry_run:
        return
    if not sys.stdin.isatty():
        if proposals:
            print("not a terminal; proposals were not written", file=sys.stderr)
        if git_added:
            tracker.write_generated_notes(vault)
        return

    picked = []
    if proposals:
        try:
            reply = input("Apply which? [a]ll, [n]one, or numbers like 1,3-4: ")
        except EOFError:
            reply = ""
        picked = [proposals[i] for i in suggest.parse_selection(reply, len(proposals))]
        suggest.ask_difficulty(picked)

    try:
        learned = input("What did you learn? [optional] ")
    except EOFError:
        learned = ""
    proposal_added, _ = apply_proposals(vault, picked)
    learning_added, _ = write_learning(vault, day, learned)
    total = git_added + proposal_added + learning_added
    if total:
        tracker.write_generated_notes(vault)
    print("recap complete: %d new event(s)" % total)
