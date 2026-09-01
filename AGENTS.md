# AGENTS.md — instructions for the coding agent

Read `PLAN.md` first. It is the spec; this file is how to work on it.

## What this is

A personal CLI tool that logs work events into an Obsidian vault as plain Markdown. Not a product. The single quality bar: **it must still work in a year with zero maintenance.**

## Hard constraints — never violate

- Python **standard library only**. No pip installs, no requirements.txt, no third-party imports.
- No web server, no database, no auth. No network calls anywhere in `track` or `stats` (the write/read paths). Only `label` may reach a model, and only by shelling out to the `claude` CLI via `subprocess`.
- Vault location comes from the `VAULT_PATH` environment variable. Never hardcode a path. Exit with a clear one-line error if it's unset or missing.
- All state lives in the Markdown files. No index, no cache, no sidecar JSON, no dotfile that can drift out of sync with the notes.
- **Append-only writes to daily notes**: never rewrite, reflow, or reorder existing content. When inserting under `## Log`, every existing byte before and after the insertion point must survive unchanged.
- `label` must show its proposed changes and wait for explicit `y` confirmation before writing anything. It sends note **title and headings only** to the model, never the body.
- GitHub and Canvas ingestion are **out of scope**. Do not build, stub, or scaffold for them.

## Structure

- `tracker.py` — everything. One file, argparse subcommands `track` / `stats` / `label`. Resist the urge to split into a package; a single file is the maintenance-free shape here.
- `README.md` — short usage doc (setup `VAULT_PATH`, the three commands, the 04:00 rollover rule).
- `.gitignore` — minimal (`__pycache__/`, `.venv/`).

## Style

- Plain, boring Python. Functions, not classes, unless a class genuinely earns it.
- Tolerant reader, strict writer: parse existing notes with forgiving regexes and skip what doesn't match; write only the exact line format from PLAN.md.
- Errors are one clear sentence to stderr + nonzero exit. No tracebacks for expected failures (bad type, missing VAULT_PATH, missing topics.txt, `claude` not installed).
- No cleverness, no premature abstraction, no config files. If a behavior needs explaining, put a short comment at the decision point.

## Git

- Repo is not yet initialized: start with `git init`.
- Small, sensible commits in build order (see PLAN.md "Git" section for the intended sequence). Each commit only when its piece is verified working.
- No branches needed, **no pull requests**, no remote.

## Verification before each commit

Follow the "Verification" section of PLAN.md. Use a scratch directory as `VAULT_PATH` for all testing — never test against a real vault. The append-only property is the one thing to prove carefully: write a daily note with content after `## Log`, run `track`, and check the surrounding bytes are untouched.
