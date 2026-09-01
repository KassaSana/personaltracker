#!/usr/bin/env python3
"""Import commits from local Git repositories into the Markdown log."""

import os
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import tracker

GIT_FIELD_SEP = "\x1f"
GIT_LOG_FORMAT = GIT_FIELD_SEP.join(("%H", "%aI", "%s", "%P"))


def run_git(repo, argv):
    """Run a Git command in repo. Return stdout, or None on failure."""
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "-C", repo] + argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def git_author_email(repo):
    out = run_git(repo, ["config", "user.email"])
    return out.strip() if out else ""


def parse_git_date(text):
    try:
        when = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    return when


def parse_git_log(text):
    """Parse Git records, skipping incomplete or malformed ones."""
    commits = []
    for raw in (text or "").splitlines():
        parts = raw.rstrip("\r").split(GIT_FIELD_SEP)
        if len(parts) not in (3, 4):
            continue
        sha, when_raw, subject = parts[:3]
        parents = parts[3].split() if len(parts) == 4 else []
        when = parse_git_date(when_raw)
        if not sha.strip() or when is None:
            continue
        commits.append({
            "sha": sha.strip(),
            "when": when,
            "subject": tracker.sanitize(subject),
            "parents": parents,
        })
    return commits


def git_commits(repo, since, author):
    argv = ["log", "--since", since.isoformat(), "--pretty=format:" + GIT_LOG_FORMAT]
    if author:
        argv += ["--author", author]
    out = run_git(repo, argv)
    return None if out is None else parse_git_log(out)


def is_git_repo(path):
    return os.path.isdir(os.path.join(path, ".git"))


def discover_repos(root):
    """Return Git repositories at root and one directory below it."""
    found = [root] if is_git_repo(root) else []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        print("warning: cannot read --root %s" % root, file=sys.stderr)
        return found
    for name in names:
        path = os.path.join(root, name)
        if is_git_repo(path):
            found.append(path)
    return found


def resolve_repos(repos, roots):
    """Resolve explicit repositories, roots, or the TRACKER_REPOS default."""
    paths = list(repos or ())
    for root in roots or ():
        paths += discover_repos(root)
    if not paths:
        paths = [p for p in os.environ.get("TRACKER_REPOS", "").split(os.pathsep) if p.strip()]

    resolved, seen = [], set()
    for path in paths:
        full = os.path.abspath(os.path.expanduser(path.strip()))
        if full not in seen:
            seen.add(full)
            resolved.append(full)
    return resolved


def collect_commit_lines(repos, since, author):
    """Map working date to commit log lines ready for the shared writer."""
    by_day = defaultdict(list)
    scanned = 0
    for repo in repos:
        if not is_git_repo(repo):
            print("warning: not a git repository: %s" % repo, file=sys.stderr)
            continue
        who = author or git_author_email(repo)
        if not who:
            print("warning: %s has no git user.email; pass --author" % repo, file=sys.stderr)
            continue
        commits = git_commits(repo, since, who)
        if commits is None:
            print("warning: could not read git log in %s" % repo, file=sys.stderr)
            continue
        scanned += 1
        name = tracker.sanitize(os.path.basename(repo)) or "repo"
        repo_identity = tracker.sanitize(os.path.realpath(repo)) or name
        for commit in commits:
            # Include both repository identity and the full SHA: short hashes can
            # collide, and the same commit can legitimately exist in two repos.
            ident = "%s:%s" % (repo_identity, commit["sha"])
            extras = [("repo", name), ("id", ident), ("src", "sync")]
            event_type = "merge" if len(commit.get("parents", ())) >= 2 else "commit"
            line = tracker.format_log_line(
                event_type, commit["when"], commit["subject"], None, None, extras
            )
            day = tracker.working_date(commit["when"])
            by_day[day].append((commit["when"], ident, line))
    return by_day, scanned


def cmd_sync(args):
    if args.days < 1:
        tracker.die("--days must be at least 1")
    if not shutil.which("git"):
        tracker.die("git is not installed or not on PATH.")

    vault = tracker.vault_path()
    repos = resolve_repos(args.repo, args.root)
    if not repos:
        tracker.die("no repositories to sync; pass --repo/--root or set TRACKER_REPOS.")

    since = tracker.working_date() - timedelta(days=args.days)
    by_day, scanned = collect_commit_lines(repos, since, args.author)
    if not scanned:
        tracker.die("no repository could be read; nothing was written.")

    added, skipped = tracker.append_commit_lines(vault, by_day, args.dry_run)
    verb = "would add" if args.dry_run else "added"
    print("%s %d event(s) from %d repo(s); %d already logged" %
          (verb, added, scanned, skipped))
    if added and not args.dry_run and not args.no_dash:
        tracker.write_generated_notes(vault)
