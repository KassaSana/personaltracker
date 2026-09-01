#!/usr/bin/env python3
"""`t setup`: make a vault and print the two lines that turn this on.

Everything else in the project is unusable until VAULT_PATH points somewhere real,
so this exists to remove the only remaining setup step. It creates directories and
seeds two optional files -- and never overwrites anything you already have.

Your PowerShell profile is yours; setup prints the block and only appends it when
you pass --profile.
"""

import os
import shutil
import sys

import tracker

VAULT_DIRS = ("daily", "reviews", "templates")

STARTER_TOPICS = """# One topic per line. Used by `t label` and by --topic on study events.
# Edit freely: these are a starting point, not a schema.
algorithms
data-structures
systems-design
operating-systems
networks
databases
machine-learning
quant
interview-prep
coursework
"""

PROFILE_MARKER = "# --- personaltracker ---"

PROFILE_BLOCK = """%s
$env:VAULT_PATH = "%s"
$env:TRACKER_REPOS = "%s"
function t { & "%s" @args }
. "%s"
# --- end personaltracker ---
"""


def repo_dir():
    return os.path.dirname(os.path.abspath(__file__))


def resolve_target(raw):
    """Where the vault goes: the argument, else VAULT_PATH, else nothing doing."""
    if raw:
        return os.path.abspath(os.path.expanduser(raw))
    existing = os.environ.get("VAULT_PATH")
    if existing:
        return os.path.abspath(os.path.expanduser(existing))
    tracker.die("give setup a path: t setup \"D:\\path\\to\\vault\"")


def seed_file(path, content, created, kept):
    """Write a starter file, or leave yours exactly as it is."""
    if os.path.exists(path):
        kept.append(path)
        return
    tracker.write_text(path, content)
    created.append(path)


def build_vault(target):
    """Create the vault layout. Returns (created, kept) paths, for reporting."""
    created, kept = [], []
    for name in ("",) + VAULT_DIRS:
        path = os.path.join(target, name) if name else target
        if os.path.isdir(path):
            kept.append(path)
        else:
            os.makedirs(path, exist_ok=True)
            created.append(path)

    template_source = os.path.join(repo_dir(), tracker.DAILY_TEMPLATE)
    template_target = os.path.join(target, tracker.DAILY_TEMPLATE)
    if os.path.isfile(template_source):
        body = tracker.read_text(template_source)
    else:
        body = "# {{date}}\n\n## Log\n\n## Notes\n\n"
    seed_file(template_target, body, created, kept)
    seed_file(os.path.join(target, "topics.txt"), STARTER_TOPICS, created, kept)
    return created, kept


def profile_path():
    """The PowerShell profile, whether or not it exists yet."""
    documents = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(documents, "WindowsPowerShell", "Microsoft.PowerShell_profile.ps1")


def guess_repos():
    """A working TRACKER_REPOS default.

    It has to be a list of repositories, not the folder they sit in -- sync treats
    each entry as a repo and warns about anything that is not one. So discover the
    real ones next to this project, and fall back to this project alone.
    """
    found = tracker.discover_repos(os.path.dirname(repo_dir()))
    return os.pathsep.join(found or [repo_dir()])


def profile_block(target, repos):
    return PROFILE_BLOCK % (
        PROFILE_MARKER,
        target,
        repos,
        os.path.join(repo_dir(), "t.ps1"),
        os.path.join(repo_dir(), "completion.ps1"),
    )


def append_to_profile(block):
    """Append the block once. Returns a message; never writes it twice."""
    path = profile_path()
    existing = ""
    if os.path.isfile(path):
        try:
            existing = tracker.read_text(path)
        except OSError:
            return "could not read %s; paste the block above by hand" % path
    if PROFILE_MARKER in existing:
        return "profile already has a personaltracker block; left it alone"

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        separator = "" if not existing or existing.endswith("\n") else "\n"
        tracker.write_text(path, existing + separator + "\n" + block)
    except OSError as exc:
        return "could not write %s: %s" % (path, exc)
    return "appended to %s -- open a new terminal for it to take effect" % path


def cmd_setup(args):
    target = resolve_target(args.path)
    created, _kept = build_vault(target)

    print("vault: %s" % target)
    # The root is already named above; listing it again as "." helps nobody.
    inside = [os.path.relpath(p, target).replace(os.sep, "/") for p in created]
    for name in [n for n in inside if n != "."]:
        print("  created %s" % name)
    if not created:
        print("  everything was already there; nothing changed")

    repos = os.environ.get("TRACKER_REPOS") or guess_repos()
    block = profile_block(target, repos)

    print("")
    print("Add this to your PowerShell profile (%s):" % profile_path())
    print("")
    for line in block.rstrip("\n").splitlines():
        print("  %s" % line)
    print("")

    if args.profile:
        print(append_to_profile(block))
    else:
        print("Run `t setup --profile` to append it for you.")

    print("")
    print("Then, in a new terminal:")
    print("  t commit \"first thing I did\"     log something by hand")
    print("  t sync --dry-run                 see the commits it would import")
    print("  t suggest --dry-run              see what your history suggests")
    print("  t gui                            the window, if a terminal is the problem")
    return 0
