#!/usr/bin/env python3
"""Propose events from evidence already on this machine, and write only what you confirm.

The point is capture without typing. The rule that keeps it honest: browser history
proves a problem was *opened*, never that it was solved, so nothing here writes
without a `y` -- same shape as `label`. Exact signals that need no judgement (git
commits) stay in `sync`.

No network, ever. Everything read here is a local file some other program already
wrote: Chromium's History, Firefox's places.sqlite.
"""

import hashlib
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import OrderedDict
from datetime import datetime, timedelta

import tracker

DEFAULT_DAYS = 3
SOURCE = "suggest"

# Chromium stores visit times as microseconds since 1601-01-01; Firefox uses
# microseconds since the Unix epoch.
CHROMIUM_EPOCH = datetime(1601, 1, 1)
UNIX_EPOCH = datetime(1970, 1, 1)

CHROMIUM_QUERY = (
    "SELECT urls.url, urls.title, visits.visit_time "
    "FROM urls JOIN visits ON visits.url = urls.id "
    "WHERE visits.visit_time > ? ORDER BY visits.visit_time"
)
FIREFOX_QUERY = (
    "SELECT p.url, p.title, v.visit_date "
    "FROM moz_places p JOIN moz_historyvisits v ON v.place_id = p.id "
    "WHERE v.visit_date > ? ORDER BY v.visit_date"
)

# Browser profile directories, relative to a Windows app-data root. A missing one
# is simply a browser you do not use.
CHROMIUM_ROOTS = (
    ("LOCALAPPDATA", os.path.join("Google", "Chrome", "User Data")),
    ("LOCALAPPDATA", os.path.join("Microsoft", "Edge", "User Data")),
    ("LOCALAPPDATA", os.path.join("BraveSoftware", "Brave-Browser", "User Data")),
    ("LOCALAPPDATA", os.path.join("Vivaldi", "User Data")),
    ("APPDATA", os.path.join("Opera Software", "Opera Stable")),
)
FIREFOX_ROOTS = (("APPDATA", os.path.join("Mozilla", "Firefox", "Profiles")),)

# Detail longer than this is a page title, not a detail.
MAX_DETAIL = 70

# Profiles Chrome keeps for itself; nobody browses in them.
SKIP_PROFILES = ("System Profile", "Guest Profile")

# Titles a job page shows when it is not showing the job: a login wall, an error,
# the careers landing page. The URL is still a real posting, so the row stays --
# only its label falls back to the company and the job id.
DEAD_TITLES = (
    "sign in", "log in", "login", "create account", "sign up", "careers",
    "candidate home", "my account", "unavailable", "job search", "error",
    "loading", "workday", "jobs",
)

DIFFICULTY_KEYS = {"e": "easy", "m": "medium", "h": "hard"}


# ---- URL rules -------------------------------------------------------------
#
# Deliberately narrow: an allowlist of a few job boards and one problem site, so a
# scan of your history can only ever see the pages this tool knows how to log.

LEETCODE_RE = re.compile(
    r"^https?://(?:www\.)?leetcode\.com/problems/([a-zA-Z0-9-]+)", re.I
)
CODESIGNAL_RE = re.compile(
    r"^https?://(?:app\.)?codesignal\.com/[^?#]*(?:assessment|test|interview)[^?#]*", re.I
)
CANVAS_RE = re.compile(
    r"^https?://([a-z0-9.-]+\.instructure\.com)/courses/(\d+)/assignments/(\d+)", re.I
)
ATS_RULES = (
    # (regex, id prefix, company group, job group)
    (re.compile(r"^https?://(?:boards|job-boards)\.greenhouse\.io/([^/?#]+)/jobs/(\d+)", re.I), "gh", 1, 2),
    (re.compile(r"^https?://jobs\.lever\.co/([^/?#]+)/([0-9a-f-]{8,})", re.I), "lever", 1, 2),
    (re.compile(r"^https?://jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{8,})", re.I), "ashby", 1, 2),
    (re.compile(r"^https?://jobs\.smartrecruiters\.com/([^/?#]+)/(\d+)", re.I), "sr", 1, 2),
    (re.compile(r"^https?://([^./]+)\.wd\d+\.myworkdayjobs\.com/[^?#]*?/job/[^/]+/([^/?#]+)", re.I), "wd", 1, 2),
)


def clean_company(raw):
    """'NVIDIACorporation' stays as written; only separators and case are ours."""
    return tracker.sanitize(raw).strip("-_ ").lower()


def is_dead_title(text):
    """True when the page title describes the site, not the job."""
    lowered = tracker.sanitize(text or "").lower().strip(" .-")
    if not lowered:
        return True
    return any(
        lowered == dead or lowered.startswith(dead + " ") or dead in lowered.split(" - ")
        for dead in DEAD_TITLES
    ) or lowered.startswith("workday is")


def humanize_job(raw):
    """'Software-Engineer_JR123' -> 'Software Engineer JR123'.

    Workday puts the job title in the URL, so a page that never showed its title
    can still be labelled properly. A slug that is just an id humanizes to noise,
    so the caller falls back when this returns nothing useful.
    """
    text = re.sub(r"[\s_-]+", " ", tracker.sanitize(raw)).strip()
    words = [w for w in text.split(" ") if any(c.isalpha() for c in w)]
    if len(words) < 2 or len(text) < 6:
        return ""
    # A uuid splits into word-shaped pieces made of hex digits. That is an id, not
    # a title, and Lever and Ashby URLs are full of them.
    if all(re.fullmatch(r"[0-9a-f]+", word.lower()) for word in words):
        return ""
    return text


def clean_detail(text, fallback=""):
    # Trim the site name before sanitizing, not after: sanitize turns the pipe that
    # separates "Job Title | Company" into a space. A plain hyphen is never a
    # separator here -- "SWE Intern - Summer 2027" is one title, not two.
    text = text or ""
    for sep in (" | ", " – ", " — "):
        if sep in text:
            head = text.split(sep)[0].strip()
            if len(head) >= 8:
                text = head
                break
    text = tracker.sanitize(text)
    if len(text) > MAX_DETAIL:
        text = text[:MAX_DETAIL].rstrip() + "..."
    return text or fallback


def classify(url, title):
    """One visit -> a proposal dict, or None when the URL is not one we log."""
    m = LEETCODE_RE.match(url)
    if m:
        slug = m.group(1).lower()
        return {
            "type": "leetcode",
            "detail": slug,
            "extras": [],
            "ident": "lc-%s" % slug,
            "source": "leetcode",
        }

    m = CODESIGNAL_RE.match(url)
    if m:
        ident = hashlib.sha1(url.split("?", 1)[0].split("#", 1)[0].lower().encode("utf-8")).hexdigest()[:16]
        return {
            "type": "assessment",
            "detail": clean_detail(title, "CodeSignal assessment"),
            "extras": [("platform", "codesignal")],
            "ident": "cs-%s" % ident,
            "source": "codesignal",
        }

    m = CANVAS_RE.match(url)
    if m:
        host, course, assignment = m.groups()
        return {
            "type": "assignment",
            "detail": clean_detail(title, "assignment %s" % assignment),
            "extras": [("platform", "canvas")],
            "ident": "canvas-%s-%s-%s" % (host.lower(), course, assignment),
            "source": "canvas",
        }

    for pattern, prefix, company_group, job_group in ATS_RULES:
        m = pattern.match(url)
        if not m:
            continue
        company = clean_company(m.group(company_group))
        job = tracker.sanitize(m.group(job_group))
        # A login wall or an outage page is still a real posting; label it by the
        # job the URL points at rather than by whatever the tab happened to say.
        fallback = humanize_job(job) or "%s posting" % company
        return {
            "type": "application",
            "detail": fallback if is_dead_title(title) else clean_detail(title, fallback),
            "extras": [("company", company), ("stage", "applied")],
            "ident": "%s-%s" % (prefix, job[:16]),
            "source": prefix,
        }
    return None


# ---- reading history -------------------------------------------------------


def profile_databases():
    """Every browser history file on this machine, newest browsers first.

    TRACKER_BROWSERS overrides discovery with an explicit pathsep-separated list,
    for a portable install or a profile in an unusual place.
    """
    override = os.environ.get("TRACKER_BROWSERS", "")
    if override.strip():
        found = []
        for raw in override.split(os.pathsep):
            path = os.path.abspath(os.path.expanduser(raw.strip()))
            if not raw.strip() or not os.path.isfile(path):
                continue
            kind = "firefox" if path.endswith("places.sqlite") else "chromium"
            found.append((kind, path))
        return found

    found = []
    for env_name, relative in CHROMIUM_ROOTS:
        root = os.environ.get(env_name)
        if not root:
            continue
        user_data = os.path.join(root, relative)
        if not os.path.isdir(user_data):
            continue
        # Default, Profile 1, Profile 2 ... plus Opera, which has no profile level.
        candidates = [user_data] + [
            os.path.join(user_data, name)
            for name in sorted(os.listdir(user_data))
            if name not in SKIP_PROFILES
        ]
        for candidate in candidates:
            path = os.path.join(candidate, "History")
            if os.path.isfile(path):
                found.append(("chromium", path))

    for env_name, relative in FIREFOX_ROOTS:
        root = os.environ.get(env_name)
        if not root or not os.path.isdir(os.path.join(root, relative)):
            continue
        profiles = os.path.join(root, relative)
        for name in sorted(os.listdir(profiles)):
            path = os.path.join(profiles, name, "places.sqlite")
            if os.path.isfile(path):
                found.append(("firefox", path))
    return found


def read_visits(kind, path, since):
    """Visits after `since` from one history database, as [(when, url, title)].

    The file is locked while the browser runs, so it is copied first -- along with
    any -wal/-shm sidecars, which is where the most recent visits live. A database
    that cannot be read is skipped: this is a suggestion engine, not a write path.
    """
    tmpdir = tempfile.mkdtemp(prefix="tracker-history-")
    try:
        copy = os.path.join(tmpdir, os.path.basename(path))
        try:
            shutil.copyfile(path, copy)
            for suffix in ("-wal", "-shm"):
                if os.path.isfile(path + suffix):
                    shutil.copyfile(path + suffix, copy + suffix)
        except OSError:
            return []

        if kind == "firefox":
            query, cutoff = FIREFOX_QUERY, int((since - UNIX_EPOCH).total_seconds() * 1e6)
        else:
            query, cutoff = CHROMIUM_QUERY, int((since - CHROMIUM_EPOCH).total_seconds() * 1e6)

        try:
            conn = sqlite3.connect(copy)
            try:
                rows = conn.execute(query, (cutoff,)).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return []

        visits = []
        for url, title, stamp in rows:
            when = visit_time(kind, stamp)
            if when is not None and url:
                visits.append((when, url, title or ""))
        return visits
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def visit_time(kind, stamp):
    """Browser timestamp -> local naive datetime, or None if it is nonsense."""
    try:
        micros = int(stamp)
    except (TypeError, ValueError):
        return None
    epoch = UNIX_EPOCH if kind == "firefox" else CHROMIUM_EPOCH
    try:
        # Both browsers store UTC; the rest of the tool works in local wall-clock.
        utc = epoch + timedelta(microseconds=micros)
        offset = datetime.now() - datetime.utcnow()
        return utc + offset
    except (OverflowError, OSError, ValueError):
        return None


# ---- proposals -------------------------------------------------------------


def gather(since, databases=None):
    """Proposals from every browser, one per (event, working day), oldest first.

    Opening the same problem six times in an evening is one problem, so the first
    visit of the day wins and the rest collapse into it.
    """
    if databases is None:
        databases = profile_databases()

    by_key = OrderedDict()
    for kind, path in databases:
        for when, url, title in read_visits(kind, path, since):
            proposal = classify(url, title)
            if proposal is None:
                continue
            day = tracker.working_date(when)
            key = (day, proposal["ident"])
            existing = by_key.get(key)
            if existing is None or when < existing["when"]:
                proposal = dict(proposal, when=when, day=day)
                by_key[key] = proposal
    # One posting reached by two URLs is still one posting: collapse anything that
    # describes the same thing on the same day, keeping the earliest visit.
    by_description = OrderedDict()
    for proposal in by_key.values():
        key = (proposal["day"], proposal["type"], proposal["detail"], tuple(proposal["extras"]))
        existing = by_description.get(key)
        if existing is None or proposal["when"] < existing["when"]:
            by_description[key] = proposal

    # By working day first, then by clock: a 00:30 visit belongs to the night before,
    # and grouping it under that day is what makes the table read in order.
    return sorted(by_description.values(), key=lambda p: (p["day"], p["when"]))


def already_logged(vault, proposals):
    """Drop anything whose id is already in that day's note. Same dedupe key as sync,
    and the state lives in the Markdown, so re-running is safe forever."""
    seen = {}
    fresh = []
    for proposal in proposals:
        day = proposal["day"]
        if day not in seen:
            path = tracker.daily_path(vault, day)
            content = tracker.read_text(path) if os.path.isfile(path) else ""
            seen[day] = tracker.existing_ids(content)
        if proposal["ident"] in seen[day]:
            continue
        fresh.append(proposal)
    return fresh


def proposal_row(index, proposal):
    return [
        str(index),
        proposal["day"].isoformat(),
        proposal["when"].strftime("%H:%M"),
        proposal["type"],
        proposal["detail"],
        proposal["source"],
    ]


def render(proposals):
    headers = ["#", "day", "at", "type", "detail", "from"]
    rows = [proposal_row(i, p) for i, p in enumerate(proposals, start=1)]
    return tracker.render_table(headers, rows)


def parse_selection(reply, count):
    """'a' -> all, 'n'/'' -> none, '1,3-4' -> those. Unknown input selects nothing."""
    reply = (reply or "").strip().lower()
    if reply in ("a", "all", "y", "yes"):
        return list(range(count))
    if reply in ("", "n", "no", "none"):
        return []
    chosen = []
    for part in reply.replace(" ", ",").split(","):
        if not part:
            continue
        start, _dash, end = part.partition("-")
        try:
            first, last = int(start), int(end or start)
        except ValueError:
            return []
        for number in range(first, last + 1):
            if 1 <= number <= count and number - 1 not in chosen:
                chosen.append(number - 1)
    return sorted(chosen)


def to_log_lines(proposals):
    """Proposals -> the by_day shape sync's writer already takes."""
    by_day = {}
    for proposal in proposals:
        extras = list(proposal["extras"])
        extras += [("id", proposal["ident"]), ("src", SOURCE)]
        line = tracker.format_log_line(
            proposal["type"], proposal["when"], proposal["detail"], None, None, extras
        )
        by_day.setdefault(proposal["day"], []).append(
            (proposal["when"], proposal["ident"], line)
        )
    return by_day


def ask_difficulty(proposals):
    """Difficulty is the one thing history cannot know, and the difficulty mix is a
    metric that matters. One keystroke each, and blank is a fine answer."""
    for proposal in proposals:
        if proposal["type"] != "leetcode":
            continue
        try:
            reply = input("  difficulty for %s [e/m/h, enter to skip]: " % proposal["detail"])
        except EOFError:
            return
        key = reply.strip().lower()[:1]
        if key in DIFFICULTY_KEYS:
            proposal["extras"] = list(proposal["extras"]) + [("diff", DIFFICULTY_KEYS[key])]


def cmd_suggest(args):
    if args.days < 1:
        tracker.die("--days must be at least 1")
    vault = tracker.vault_path()

    since = datetime.now() - timedelta(days=args.days)
    databases = profile_databases()
    if not databases:
        tracker.die(
            "no browser history found; set TRACKER_BROWSERS to a History or "
            "places.sqlite file."
        )

    proposals = already_logged(vault, gather(since, databases))
    if not proposals:
        print("nothing new to propose from %d browser profile(s)." % len(databases))
        return

    tracker.print_lines(render(proposals))
    print("")
    # The whole reason this asks instead of writing. A posting you read and a
    # posting you submitted look identical in browser history.
    print("A page you opened is not a problem you solved or a job you applied to.")
    print("Pick only what you actually finished.")

    if args.dry_run:
        return
    if args.yes:
        chosen = list(range(len(proposals)))
    elif not sys.stdin.isatty():
        print("not a terminal; pass --yes to write these", file=sys.stderr)
        return
    else:
        try:
            reply = input("Apply which? [a]ll, [n]one, or numbers like 1,3-4: ")
        except EOFError:
            return
        chosen = parse_selection(reply, len(proposals))

    picked = [proposals[i] for i in chosen]
    if not picked:
        print("wrote nothing.")
        return
    if not args.yes and sys.stdin.isatty():
        ask_difficulty(picked)

    added, skipped = tracker.append_commit_lines(vault, to_log_lines(picked), False)
    print("added %d event(s); %d already logged" % (added, skipped))
    if added:
        tracker.write_generated_notes(vault)
