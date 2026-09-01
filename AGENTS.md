# AGENTS.md — instructions for the coding agent

Read `PLAN.md` first — it is the spec for the original three commands. `ROADMAP.md` is the
product plan on top of it and **supersedes PLAN.md where they disagree**; this file is how
to work on both.

## What this is

A personal CLI tool that logs work events into an Obsidian vault as plain Markdown. Not a product. The single quality bar: **it must still work in a year with zero maintenance.**

## Hard constraints — never violate

- Prefer Python and the standard library for the core, but dependencies, authenticated APIs,
  MCP services, browser extensions and companion collectors are allowed when they materially
  improve capture accuracy or reduce maintenance. Keep every integration optional: the local
  CLI and existing Markdown data must remain usable when it is offline or removed.
- A required web server or authoritative database is still the wrong default for this personal
  tool. Disposable local indexes/cursors are allowed, but they must be rebuildable from the
  durable Markdown record or their upstream source.
- Vault location comes from the `VAULT_PATH` environment variable, and `sync`'s repo list from `TRACKER_REPOS`. Never hardcode a path. Exit with a clear one-line error if `VAULT_PATH` is unset or missing.
- Accomplishments and summarized time live in Markdown. Caches and sync cursors may exist only
  as disposable implementation state; losing them must not lose the human-readable record.
- **Append-only writes to daily notes**: never rewrite, reflow, or reorder existing content. When inserting under `## Log`, every existing byte before and after the insertion point must survive unchanged.
- `label` must show its proposed changes and wait for explicit `y` confirmation before writing anything. It sends note **title and headings only** to the model, never the body.
- Importers and integrations must be idempotent. Their durable dedupe key `id::` lives in the
  Markdown. Local Git remains the zero-setup source; authenticated GitHub, Canvas, coding-site
  and browser integrations are allowed as optional sources.
- A review note (`reviews/YYYY-Www.md`) is written once and never regenerated; it holds the user's handwriting. Only `Stats.md` and `Dashboard.md` are overwritable. `dash` writes them explicitly; capture/import workflows may refresh them only after they actually add events. A command that only reads numbers must never write as a side effect.

## Structure

- `tracker.py` — the CLI, the parser, the daily-note I/O and the numbers engine, and every write path the other files reuse. Resist the urge to split into a package; a flat set of modules with one CLI is the maintenance-free shape here. Navigate it by the `# ---- section ----` banners, and add a new command as a new banner section plus one `sub.add_parser` block. It must stay under the roadmap's ~1500-line ceiling: anything sizeable goes in its own file with a thin `sibling_module(...)` subcommand here, the way `gui`, `suggest`, `setup`, `review` and `label` do. A sibling imports `tracker`, never the reverse at module scope — that is what keeps the lazy import free of cycles.
- `review.py` — `t review`: writes `reviews/YYYY-Www.md`, once, and never regenerates it. It owns the note's shape only; every figure comes back through `weekly_buckets` / `weekly_report` / `difficulty_report` / `streak_lines` / `pipeline_report`, so a review cannot disagree with `t stats`.
- `recap.py` — `t recap`: imports exact local Git facts, presents browser evidence for
  confirmation, offers one optional learning line, and keeps accomplishments separate from
  measured attention. It owns no Markdown format or parser.
- `label.py` — `t label`: the only code in the project that reaches a model, and only by shelling out to the `claude` CLI. Title and headings go out, never the body; the reply is normalized against `topics.txt` so an unexpected label becomes `other`; and `insert_topic_field` inserts rather than rewrites. Keep it the one place a model appears.
- `suggest.py` — `t suggest`: reads browser evidence and proposes events. The URL allowlist is
  the privacy boundary, and ambiguous evidence is never written without an explicit pick.
  Optional authenticated connectors may provide stronger completion evidence. Writes reuse
  `tracker.append_commit_lines`, so `id::` dedupe and append-only behaviour stay shared.
- `watch.py` — `t watch`: the foreground-window watcher. Raw titles/URLs may be retained only
  in an explicitly enabled private local collector; the default watcher persists category names
  only. **`time` events never count as completions.** Writes go through
  `tracker.append_commit_lines`, and the pure session/classification logic remains tested.
- `bootstrap.py` — `t setup`: creates the vault layout and prints (or, with `--profile`, appends once) the PowerShell block. It must stay non-destructive — an existing `topics.txt`, template or profile block is kept, never rewritten.
- `quickadd.py` — the tkinter window behind `t gui` (Recap / Log / Numbers tabs). It owns no
  line format, engine or file handling. Recap/history discovery runs on a worker thread that
  only puts its result on a `queue.Queue`: Tk is not thread-safe, and calling even `after()`
  from another thread reaches into the Tcl interpreter from the wrong one.
- `completion.ps1` — PowerShell argument completer for `t`. Its words come from `t complete`, which walks the parser; never hardcode a second list.
- `templates/Daily.md` — example vault template. A copy at `<VAULT_PATH>/templates/Daily.md` seeds notes the tool creates (`{{date}}` substituted) and carries unticked `- [ ] type:: ...` boxes; ticking one in Obsidian is a logged event, because the parser has always counted only `- [x]`.
- `test_tracker.py` — stdlib `unittest`. `sync` is tested against a fake `run_git` plus one real-git integration test that skips when `git` is absent. The GUI is tested through its pure functions only — no Tk in the test suite.
- `README.md` — short usage doc (setup `VAULT_PATH`, the commands, the 04:00 rollover rule).
- `.gitignore` — keep generated caches, environments, credentials and disposable integration
  state out of Git.

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
