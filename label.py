#!/usr/bin/env python3
"""`t label`: ask a model for one topic per recent note, show the answers, write on `y`.

The only command in the project that reaches a model, and it does so by shelling
out to the `claude` CLI -- no SDK, no key, no network code here. What it sends is
the note's title and headings, never the body, and the reply is constrained to
topics.txt so a hallucinated label lands on `other` instead of in your vault.

Nothing is written without an explicit `y`, and the write is an insertion: every
existing byte of the note survives.
"""

import os
import re
import shutil
import subprocess
import sys

import tracker

HEADING_LINE_RE = re.compile(r"^#{1,6} ")


def load_topics(vault):
    path = os.path.join(vault, "topics.txt")
    if not os.path.isfile(path):
        tracker.die("topics.txt not found in VAULT_PATH; create it with one topic per line.")
    topics = []
    for line in tracker.read_text(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        topics.append(line)
    if not topics:
        tracker.die("topics.txt has no topics.")
    return topics


def iter_recent_notes(vault, since):
    since_ts = since.timestamp()
    for root, _dirs, files in os.walk(vault):
        for name in files:
            if not name.endswith(".md") or name in tracker.GENERATED_NOTES:
                continue
            path = os.path.join(root, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime < since_ts:
                continue
            yield path


def note_headings(content):
    if content.startswith("﻿"):
        content = content[1:]
    headings = []
    for raw in content.splitlines():
        line = raw.rstrip("\r")
        if HEADING_LINE_RE.match(line):
            headings.append(line)
    return headings


def build_label_prompt(title, headings, topics):
    # Single line: cmd.exe / claude.cmd drop everything after an embedded newline.
    heading_text = " | ".join(headings) if headings else "(no headings)"
    labels = ", ".join(topics)
    return (
        "Note title: %s. Headings: %s. Allowed labels: %s. "
        "Reply with exactly one label from this list, or the word other, and nothing else."
        % (title, heading_text, labels)
    )


def call_claude(prompt):
    exe = shutil.which("claude")
    if not exe:
        tracker.die("claude CLI is not installed or not on PATH.")
    argv = [exe, "-p", prompt]
    run_kw = {"capture_output": True, "text": True}
    # npm's claude.cmd is not a Win32 exe.
    if sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat")):
        run_kw["shell"] = True
        argv = subprocess.list2cmdline(argv)
    try:
        proc = subprocess.run(argv, **run_kw)
    except OSError:
        tracker.die("claude CLI is not installed or not on PATH.")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "claude CLI failed").strip()
        tracker.die(err.splitlines()[0] if err else "claude CLI failed.")
    return proc.stdout.strip()


def normalize_label(raw, topics):
    token = ""
    if raw.strip():
        token = raw.strip().splitlines()[0].strip()
    if token in topics or token == "other":
        return token, False
    return "other", True


def insert_topic_field(content, label):
    """Insert topic:: after the first heading (or at the top). Existing lines stay intact."""
    nl = tracker.newline_of(content) if content else "\n"
    field = "topic:: %s" % label
    bom = 1 if content.startswith("﻿") else 0
    body = content[bom:]
    m = re.search(r"^#{1,6} .*\r?$", body, re.MULTILINE)
    if not m:
        return content[:bom] + field + nl + content[bom:]
    after = bom + m.end()
    if after < len(content) and content[after] == "\n":
        after += 1
    addition = field + nl
    if after > 0 and content[after - 1] != "\n":
        addition = nl + addition
    return content[:after] + addition + content[after:]


def cmd_label(_args):
    vault = tracker.vault_path()
    topics = load_topics(vault)
    candidates = []
    for path in iter_recent_notes(vault, tracker.working_day_start()):
        content = tracker.read_text(path)
        if "topic::" in content:
            continue
        candidates.append((path, content))

    if not candidates:
        print("No notes to label.")
        return

    proposals = []
    for path, content in candidates:
        title = os.path.splitext(os.path.basename(path))[0]
        headings = note_headings(content)
        raw = call_claude(build_label_prompt(title, headings, topics))
        label, fallback = normalize_label(raw, topics)
        rel = os.path.relpath(path, vault)
        if fallback:
            shown = raw.strip().splitlines()[0].strip() if raw.strip() else ""
            print("warning: unexpected label %r for %s; using other" % (shown, rel), file=sys.stderr)
        proposals.append((path, content, label, rel))

    for _path, _content, label, rel in proposals:
        print("%s  %s" % (rel, label))

    if not sys.stdin.isatty():
        return
    try:
        reply = input("Apply? [y/N] ")
    except EOFError:
        return
    if reply.strip() != "y":
        return

    for path, content, label, _rel in proposals:
        tracker.write_text(path, insert_topic_field(content, label))
