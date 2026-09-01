#!/usr/bin/env python3
"""`t watch`: measure where the hours go, by watching the foreground window.

The one write it produces is a `type:: time` line per work session -- category and
minutes only. Window titles and exe names are used in memory to classify a sample
and then discarded: **nothing but the category name ever reaches disk**, which is
what makes a watcher acceptable in a vault that syncs.

Time is attention, not accomplishment, so `time` events are excluded from every
count, streak and trend in tracker.py -- they feed the time tables only. A decline
in the chart must still mean a decline in you.

Windows-only by nature (ctypes on user32/kernel32); still stdlib, still no network.
"""

import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import tracker

# Sampling cadence and the idle cutoff live on the parser (t watch --interval/--idle).
MERGE_GAP_MIN = 2         # same category resuming within this stays one session
MIN_SESSION_MIN = 3       # anything shorter is an alt-tab, not work
CHUNK_MIN = 30            # an open session is flushed at this length, so a crash
                          # or power-off can lose at most one chunk
MUTEX_NAME = "personaltracker-watch"
RULES_NAME = "watch-rules.txt"

# Built-in classification, substring-matched (case-insensitive) against
# "exe|title", first match wins. watch-rules.txt in the vault is consulted first,
# so a user line can reroute anything here.
DEFAULT_RULES = (
    ("codesignal", "interview-prep"),
    ("leetcode", "leetcode"),
    ("powerpnt.exe", "reading"),
    ("powerpoint", "reading"),
    ("canvas", "coursework"),
    ("leetcode.com", "leetcode"),
    ("greenhouse.io", "applications"),
    ("lever.co", "applications"),
    ("ashbyhq.com", "applications"),
    ("myworkday", "applications"),
    ("smartrecruiters", "applications"),
    ("linkedin.com/jobs", "applications"),
    ("indeed.com", "applications"),
    ("instructure", "assignment"),   # Canvas
    ("gradescope", "assignment"),
    ("winword", "assignment"),
    ("acrobat", "assignment"),
    ("onenote", "assignment"),
    ("code.exe", "project"),
    ("cursor.exe", "project"),
    ("pycharm", "project"),
    ("idea64", "project"),
    ("windowsterminal", "project"),
    ("powershell", "project"),
    ("cmd.exe", "project"),
    ("git", "project"),
    ("obsidian", "review"),
)

OTHER_CATEGORY = "other"

# Pair a watched category with the completion count that gives the hours meaning.
TIME_DONE_TYPES = {
    "project": "commit",
    "applications": "application",
    "leetcode": "leetcode",
    "assignment": "assignment",
    "study": "study",
}


# ---- time reports ----------------------------------------------------------
#
# The tables `t stats`, Dashboard.md and the window show for `time` events. They
# live here rather than in tracker.py only because of the line ceiling; tracker
# calls them lazily the way it loads every sibling command.


def fmt_minutes(minutes):
    hours, mins = divmod(int(minutes), 60)
    return "%dh%02dm" % (hours, mins) if hours else "%dm" % mins


def time_by_category(events):
    """Watched minutes per category (`time` events only, category in detail::)."""
    minutes = Counter()
    for fields in events:
        if fields["type"] != tracker.TIME_TYPE:
            continue
        mins = tracker.event_minutes(fields)
        if mins:
            minutes[fields.get("detail") or "(uncategorized)"] += mins
    return minutes


def time_report(events):
    """Watched time per category, largest first, with the completion count that
    gives the hours meaning ('6h on project' next to '12 commits')."""
    minutes = time_by_category(events)
    if not minutes:
        return None
    counts, _minutes, _missing = tracker.summarize(events)
    peak = max(minutes.values())
    rows = []
    for category, mins in minutes.most_common():
        done_type = TIME_DONE_TYPES.get(category)
        done = str(counts[done_type]) if done_type and counts.get(done_type) else ""
        rows.append([category, fmt_minutes(mins), tracker.bar(mins, peak), done])
    return ["category", "time", "chart", "done"], rows


def time_weekly_report(events, weeks, today):
    """Watched time per category per week, newest first. None when nothing watched."""
    time_events = [f for f in events if f["type"] == tracker.TIME_TYPE]
    if not time_events:
        return None
    categories = [c for c, _ in time_by_category(time_events).most_common()]
    current = tracker.week_start(today)
    rows = []
    for i in range(weeks):
        start = current - timedelta(weeks=i)
        by_cat = time_by_category(
            [f for f in time_events if tracker.week_start(f["_date"]) == start]
        )
        cells = [fmt_minutes(by_cat[c]) if by_cat.get(c) else "" for c in categories]
        total = sum(by_cat.values())
        rows.append([start.isoformat()] + cells + [fmt_minutes(total) if total else ""])
    return ["week"] + categories + ["total"], rows


# ---- classification --------------------------------------------------------


def parse_rules(text):
    """watch-rules.txt lines: `pattern -> category`. Tolerant like topics.txt:
    comments, blanks and lines without an arrow are skipped, never fatal."""
    rules = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pattern, sep, category = line.partition("->")
        pattern = pattern.strip().lower()
        category = tracker.sanitize(category.strip().lower())
        if sep and pattern and category:
            rules.append((pattern, category))
    return rules


def load_rules(vault):
    path = os.path.join(vault, RULES_NAME)
    if not os.path.isfile(path):
        return []
    try:
        return parse_rules(tracker.read_text(path))
    except OSError:
        print("warning: could not read %s" % path, file=sys.stderr)
        return []


def add_rule(vault, pattern, category):
    """Append one explicit custom rule without rewriting the user's rules file."""
    pattern = pattern.strip().lower()
    category = tracker.sanitize(category.strip().lower())
    if not pattern or not category or "->" in pattern or "\n" in pattern or "\r" in pattern:
        tracker.die("watch rule expects a non-empty PATTERN and CATEGORY")
    path = os.path.join(vault, RULES_NAME)
    existing = tracker.read_text(path) if os.path.isfile(path) else ""
    if any(old_pattern == pattern for old_pattern, _old_category in parse_rules(existing)):
        tracker.die("watch rule pattern already exists; edit %s to change it" % path)
    separator = "" if not existing or existing.endswith(("\n", "\r")) else "\n"
    tracker.write_text(path, existing + separator + "%s -> %s\n" % (pattern, category))
    return path


def rule_lines(vault):
    user = load_rules(vault)
    lines = ["user rules"] + (["  %s -> %s" % rule for rule in user] or ["  (none)"])
    lines += ["built-in rules"] + ["  %s -> %s" % rule for rule in DEFAULT_RULES]
    return lines


def classify(exe, title, user_rules=()):
    """Category for one sample. User rules first, then defaults, else `other`."""
    haystack = ("%s|%s" % (exe, title)).lower()
    for pattern, category in tuple(user_rules) + DEFAULT_RULES:
        if pattern in haystack:
            return category
    return OTHER_CATEGORY


# ---- session accumulation --------------------------------------------------
#
# Pure state machine fed (timestamp, category) samples; category None means idle.
# Contiguous same-category samples form a session. A switch away (or idle) does
# not end it immediately: only when the interruption outlasts the merge gap does
# the session close -- retroactively at the last matching sample, so a 30-second
# alt-tab neither splits a session nor pads it. This is the part the tests
# exercise; no OS calls in here.


class Sessions:
    def __init__(self, merge_gap_min=MERGE_GAP_MIN, min_session_min=MIN_SESSION_MIN,
                 chunk_min=CHUNK_MIN):
        self.merge_gap = timedelta(minutes=merge_gap_min)
        self.min_session = timedelta(minutes=min_session_min)
        self.chunk = timedelta(minutes=chunk_min)
        self.category = None
        self.start = None
        self.last = None       # last sample that matched self.category
        self.pending = None    # (category-or-None, since) of the current interruption

    def _open(self, category, since):
        self.category, self.start, self.last = category, since, since
        self.pending = None

    def _close(self, flushed):
        if self.category is not None and self.last - self.start >= self.min_session:
            minutes = int(round((self.last - self.start).total_seconds() / 60))
            flushed.append((self.start, minutes, self.category))
        self.category = self.start = self.last = None
        self.pending = None

    def feed(self, now, category):
        """Advance the clock. Returns finished (start, minutes, category) tuples."""
        flushed = []
        if self.category is None:
            if category is not None:
                self._open(category, now)
            return flushed

        if category == self.category:
            self.pending = None
            self.last = now
            if self.last - self.start >= self.chunk:
                self._close(flushed)
                self._open(category, now)
            return flushed

        if self.pending is None or self.pending[0] != category:
            self.pending = (category, now)
        if now - self.last > self.merge_gap:
            pending_category, since = self.pending
            self._close(flushed)
            if pending_category is not None:
                # The interloper turned out to be the new work; its clock started
                # when it first appeared, not when we gave up on the old session.
                self._open(pending_category, since)
                self.last = now
        return flushed

    def finish(self):
        """Shutdown: flush whatever is open."""
        flushed = []
        self._close(flushed)
        return flushed


# ---- write path ------------------------------------------------------------


def session_line(start, minutes, category):
    """One `type:: time` line. The id makes a re-flush of the same session a
    no-op, the same guarantee sync gives commits."""
    ident = "w%s-%s" % (start.strftime("%Y%m%dT%H%M"), category)
    extras = [("id", ident), ("src", "watch")]
    line = tracker.format_log_line("time", start, category, None, minutes, extras)
    return ident, line


def write_sessions(vault, sessions):
    """Append finished sessions to their daily notes via sync's own dedupe path."""
    if not sessions:
        return 0
    by_day = defaultdict(list)
    for start, minutes, category in sessions:
        ident, line = session_line(start, minutes, category)
        by_day[tracker.working_date(start)].append((start, ident, line))
    added, _skipped = tracker.append_commit_lines(vault, by_day, dry_run=False)
    return added


# ---- Windows sampling (ctypes) ---------------------------------------------
#
# Everything below talks to the OS and is deliberately excluded from the tests.


def _win():
    import ctypes
    import ctypes.wintypes
    return ctypes, ctypes.wintypes


def acquire_instance_mutex():
    """Hold the single-instance mutex, or return None if another watcher has it.
    The handle dies with the process, so a crash cannot wedge the lock."""
    ctypes, _wt = _win()
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
        return None
    return handle


def watcher_running():
    """Is some watcher holding the mutex? (Probe and release without disturbing it.)"""
    ctypes, _wt = _win()
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    exists = ctypes.GetLastError() == 183
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
    return exists


def foreground_sample():
    """(exe_basename, window_title) of the focused window; ('', '') when none."""
    ctypes, wt = _win()
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)

    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if handle:
        size = wt.DWORD(1024)
        path_buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, path_buf, ctypes.byref(size)):
            exe = os.path.basename(path_buf.value)
        kernel32.CloseHandle(handle)
    return exe, buf.value


def idle_seconds():
    """Seconds since the last keyboard/mouse input, machine-wide."""
    ctypes, wt = _win()

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    # Both are 32-bit tick counts, so the subtraction survives the 49-day wrap.
    delta = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return delta / 1000.0


# ---- the command -----------------------------------------------------------


def say(message):
    """print, except under pythonw -- where stdout is None and the scheduled task
    must keep watching rather than die on its first status line."""
    if sys.stdout is not None:
        print(message)


def run_watch(vault, interval, idle_limit):
    import time as time_mod

    rules = load_rules(vault)
    sessions = Sessions()
    say("watching (interval %ss, idle after %ss). Ctrl+C to stop." % (interval, idle_limit))
    try:
        while True:
            now = datetime.now()
            if idle_seconds() >= idle_limit:
                flushed = sessions.feed(now, None)
            else:
                exe, title = foreground_sample()
                flushed = sessions.feed(now, classify(exe, title, rules))
            report(vault, flushed)
            time_mod.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        report(vault, sessions.finish())


def report(vault, flushed):
    if not flushed:
        return
    write_sessions(vault, flushed)
    for start, minutes, category in flushed:
        say("  %s  %3d min  %s" % (start.strftime("%H:%M"), minutes, category))


def cmd_watch(args):
    rules_flag = getattr(args, "rules", False)
    add_rule_args = getattr(args, "add_rule", None)
    if rules_flag or add_rule_args:
        vault = tracker.vault_path()
        if add_rule_args:
            path = add_rule(vault, *add_rule_args)
            print("added rule to %s" % path)
        if rules_flag:
            tracker.print_lines(rule_lines(vault))
        return
    if args.status:
        print("watcher: %s" % ("running" if watcher_running() else "not running"))
        rules_path = os.path.join(tracker.vault_path(), RULES_NAME)
        print("rules:   %s" % (rules_path if os.path.isfile(rules_path) else "(defaults only)"))
        return
    if args.interval < 1 or args.idle < args.interval:
        tracker.die("--interval must be >= 1 and --idle >= --interval")
    if sys.platform != "win32":
        tracker.die("t watch reads the foreground window via the Windows API; Windows only.")

    vault = tracker.vault_path()
    mutex = acquire_instance_mutex()
    if mutex is None:
        tracker.die("another `t watch` is already running.")
    run_watch(vault, args.interval, args.idle)
