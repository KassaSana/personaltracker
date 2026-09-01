# AGENTS.md — instructions for the coding agent

Read `PLAN.md` first — it is the spec for the original three commands. `ROADMAP.md` is the
product plan on top of it and **supersedes PLAN.md where they disagree**; this file is how
to work on both.

## What this is

A personal CLI tool that logs work events into an Obsidian vault as plain Markdown. Not a product. The single quality bar: **it must still work in a year with zero maintenance.**

## Hard constraints — never violate

- Python **standard library only**. No pip installs, no requirements.txt, no third-party imports.
- No web server, no database, no auth. **No network calls anywhere**, including `sync` (local `git` only) and `suggest` (local browser history files only). LeetCode's GraphQL API would give exact solved-counts with difficulty and was explicitly declined in favour of this rule; do not reintroduce it. Only `label` may reach a model, and only by shelling out to the `claude` CLI via `subprocess`.
- Vault location comes from the `VAULT_PATH` environment variable, and `sync`'s repo list from `TRACKER_REPOS`. Never hardcode a path. Exit with a clear one-line error if `VAULT_PATH` is unset or missing.
- All state lives in the Markdown files. No index, no cache, no sidecar JSON, no dotfile that can drift out of sync with the notes.
- **Append-only writes to daily notes**: never rewrite, reflow, or reorder existing content. When inserting under `## Log`, every existing byte before and after the insertion point must survive unchanged.
- `label` must show its proposed changes and wait for explicit `y` confirmation before writing anything. It sends note **title and headings only** to the model, never the body.
- `sync` is the only importer, and it reads **local `git log` only**. Its dedupe key `id::` lives in the Markdown like everything else; re-running must always be safe. The **GitHub API, `gh`, Canvas and LeetCode ingestion stay out of scope** — do not build, stub, or scaffold for them until `FRICTION.md` shows they were missed.
- A review note (`reviews/YYYY-Www.md`) is written once and never regenerated; it holds the user's handwriting. Only `Stats.md` and `Dashboard.md` are overwritable, and only `t dash` may overwrite them — a command that reads numbers must never write to the vault as a side effect.

## Structure

- `tracker.py` — the CLI, the parser, the daily-note I/O and the numbers engine, and every write path the other files reuse. Resist the urge to split into a package; a flat set of modules with one CLI is the maintenance-free shape here. Navigate it by the `# ---- section ----` banners, and add a new command as a new banner section plus one `sub.add_parser` block. It must stay under the roadmap's ~1500-line ceiling: anything sizeable goes in its own file with a thin `sibling_module(...)` subcommand here, the way `gui`, `suggest`, `setup`, `review` and `label` do. A sibling imports `tracker`, never the reverse at module scope — that is what keeps the lazy import free of cycles.
- `review.py` — `t review`: writes `reviews/YYYY-Www.md`, once, and never regenerates it. It owns the note's shape only; every figure comes back through `weekly_buckets` / `weekly_report` / `difficulty_report` / `streak_lines` / `pipeline_report`, so a review cannot disagree with `t stats`.
- `label.py` — `t label`: the only code in the project that reaches a model, and only by shelling out to the `claude` CLI. Title and headings go out, never the body; the reply is normalized against `topics.txt` so an unexpected label becomes `other`; and `insert_topic_field` inserts rather than rewrites. Keep it the one place a model appears.
- `suggest.py` — `t suggest`: reads local browser history (Chromium `History`, Firefox `places.sqlite`) via stdlib `sqlite3` and proposes leetcode and application events. **No network, ever** — it only reads files another program already wrote. Two rules that must not be relaxed: the URL allowlist is the privacy boundary (it can only see pages it knows how to log), and nothing is written without an explicit pick, because history proves a page was opened, never that the work was finished. Writes reuse `tracker.append_commit_lines`, so `id::` dedupe and append-only behaviour are inherited rather than reimplemented.
- `watch.py` — `t watch`: the foreground-window watcher (ctypes on user32/kernel32; Windows-only by nature, still stdlib, still no network). Two rules that must not be relaxed: **window titles and exe names never reach disk** — they are classified in memory and discarded, and only the category name is written; and **`time` events never count as completions** — tracker.py excludes `TIME_TYPE` from every count, streak, trend and logged-day figure, and `t time` by hand is rejected in `main()`. Writes go through `tracker.append_commit_lines` (id-deduped, append-only), so a re-flush is a no-op. The session state machine (`Sessions`) and `classify` are pure and tested; the ctypes layer is not in the suite, same rule as the GUI. The time report tables live here (called lazily from tracker) only because of the line ceiling.
- `bootstrap.py` — `t setup`: creates the vault layout and prints (or, with `--profile`, appends once) the PowerShell block. It must stay non-destructive — an existing `topics.txt`, template or profile block is kept, never rewritten.
- `quickadd.py` — the tkinter window behind `t gui` (Log / Numbers / Suggest tabs). It owns no line format, no engine and no file handling: writes go through `tracker.cmd_track` / `tracker.cmd_undo` / `tracker.append_commit_lines`, numbers come from `weekly_report` / `streak_lines` / `pipeline_report`, and proposals from `suggest.gather`, with output and `SystemExit` trapped so `die()` reports in the window instead of killing it. Keep it that way. The history scan runs on a worker thread that only puts its result on a `queue.Queue`: Tk is not thread-safe, and calling even `after()` from another thread reaches into the Tcl interpreter from the wrong one.
- `completion.ps1` — PowerShell argument completer for `t`. Its words come from `t complete`, which walks the parser; never hardcode a second list.
- `templates/Daily.md` — example vault template. A copy at `<VAULT_PATH>/templates/Daily.md` seeds notes the tool creates (`{{date}}` substituted) and carries unticked `- [ ] type:: ...` boxes; ticking one in Obsidian is a logged event, because the parser has always counted only `- [x]`.
- `test_tracker.py` — stdlib `unittest`. `sync` is tested against a fake `run_git` plus one real-git integration test that skips when `git` is absent. The GUI is tested through its pure functions only — no Tk in the test suite.
- `README.md` — short usage doc (setup `VAULT_PATH`, the commands, the 04:00 rollover rule).
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
