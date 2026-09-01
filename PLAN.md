# Personal Activity Tracker — Implementation Plan

## Context

Small CLI that logs completed work as events into an Obsidian vault as plain Markdown (Dataview inline fields). Personal tool, optimized for zero maintenance in a year: Python stdlib only, no server/DB/network in the write path, all state in the Markdown files themselves. Directory is empty greenfield. Python 3.10 available. GitHub/Canvas ingestion explicitly out of scope — do not build it, do not stub it.

## Shape

One file: `tracker.py` (argparse subcommands: `track`, `stats`, `label`). Plus `README.md` and `.gitignore`. No packaging, no dependencies — `python tracker.py track commit "fixed thing"` just works forever. `topics.txt` lives in the vault (`<VAULT_PATH>/topics.txt`) so the fixed topic list travels with the notes, not the code.

`VAULT_PATH` read from environment at startup; exit with a clear message if unset or the directory doesn't exist. Never hardcoded.

## Design decisions (decided, not guessed silently)

### 1. Post-midnight tracking → 04:00 day rollover + explicit override
The "working day" ends at **04:00**, not midnight. A `track` at 01:30 appends to the *previous* date's daily note. The `when::` field always records the true wall-clock timestamp — no information is lost, the event is just *filed* under the day it belongs to. For rare exceptions there's an explicit `--date YYYY-MM-DD` flag that overrides the computed date entirely.

Why: a `--yesterday` flag alone relies on remembering to pass it at 1am, exactly when you won't. A fixed cutoff is one line of code (subtract 4h before taking the date), has no state, and matches how people actually work. 04:00 is late enough to cover real late nights, early enough to never misfile a genuine morning event.

### 2. Stats date source → filename is authoritative; `when::` is metadata
`stats` groups by **filename date**. The filename *is* the working-day assignment (that's what decision 1 produces), and it's also what Dataview sees when querying the `daily/` folder — so terminal stats and the Stats.md Dataview views agree by construction. Using different sources for the two views would let them drift, violating the "no state that drifts" principle.

Disagreement between `when::` and filename is *expected by design* for post-midnight entries (off by one day). `stats` stays silent about those, but prints a warning to stderr for any entry whose `when::` differs from the filename by **more than one day** — that indicates a manual edit or misfiled line worth looking at. Counts still go under the filename either way.

### 3. `label` model call → shell out to `claude -p` (Claude Code CLI)
`label` needs an LLM but must stay zero-maintenance: no API key management, no SDK dependency, no HTTP code. It runs `claude -p "<prompt>"` via `subprocess` (stdlib). If the CLI isn't installed, fail with a clear message. Network happens only in `label`, never in the write path — `track` and `stats` make no calls of any kind.

## Command details

### `track <type> [detail...] [--date D] [--topic T] [--duration MIN]`
- Types (fixed, closed list): `commit, pull_request, assignment, lecture, slides, application, resume, study`. Anything else → error listing valid types, exit 1.
- `--topic` / `--duration` only valid with `study` (error otherwise). `--duration` is integer minutes.
- Appends to `<VAULT_PATH>/daily/YYYY-MM-DD.md` under `## Log`:
  - File missing → create (with parent `daily/` dir) as `# YYYY-MM-DD\n\n## Log\n` + line.
  - File exists, `## Log` heading missing → append `\n## Log\n` at end of file, then the line.
  - File exists with `## Log` → insert the line after the last existing log entry under that heading (i.e., before the next `## ` heading, or at end of file). **Append-only: existing bytes are never rewritten or reordered** — read the file, find the insertion offset, write original content with only the new line inserted; everything before and after must be byte-identical.
- Line format: `- [x] type:: commit | when:: 2026-08-31T14:22 | detail:: snapback onnx flag`
  - `when::` is local time, minute precision, true wall-clock (see decision 1).
  - `detail::` omitted when no detail given; study adds `| topic:: X | duration:: 45` when provided.
  - Sanitize detail/topic: strip newlines and `|` (replace with space) so one event is always exactly one parseable line.

### `stats [7|30]` (default 7)
- Walks `<VAULT_PATH>/daily/YYYY-MM-DD.md` for the last N working days (today per the 04:00 rule, inclusive). Missing files skipped silently.
- Parses only `- [x] ... type:: ...` lines under `## Log`; tolerant regex on the inline fields; malformed lines ignored, with a one-line "skipped N unparseable lines" notice if any.
- Prints: counts by type (sorted desc), then study minutes by topic (no topic → grouped as `(untagged)`; topic but no duration → counted as "sessions without duration").
- Also (re)writes `<VAULT_PATH>/Stats.md` — fully generated file, safe to overwrite, header comment says so — containing Dataview DQL blocks producing the same two views inside Obsidian:
  1. event counts grouped by `type` over `"daily"`, last 30 days,
  2. study `duration` summed by `topic`.
  Use relative date expressions (`date(today) - dur(30 days)`), never baked-in dates, so the file never goes stale. Query task lines via `file.tasks` and their inline fields.

### `label`
- Reads topic list from `<VAULT_PATH>/topics.txt` (one label per line; `#` comment lines and blanks ignored). Missing file → clear error telling the user to create it.
- Finds `.md` files in the vault modified today (mtime, same 04:00 working-day window), excluding `Stats.md` and files that already contain a `topic::` field.
- For each: sends **title + headings only** (filename stem + lines matching `^#{1,6} `) — never the body — to `claude -p` with a strict prompt: "Reply with exactly one label from this list, or the word other, and nothing else." Validate the response against the list; anything else → treat as `other` with a warning.
- Print the proposed table (note → label), ask `Apply? [y/N]` on stdin, only write on `y`. Write appends `topic:: <label>` as a new line after the first heading (or at the top if none) — without touching existing lines. Non-interactive stdin → print proposals and exit without writing.

## Git

`git init` in the project dir, then commits that track the build order (no PRs, no remote):
1. `chore: init repo with plan, agents doc, README`
2. `feat: track command — append events to daily notes`
3. `feat: stats command — terminal summary and Stats.md dataview note`
4. `feat: label command — topic labeling via claude CLI with confirmation`

Each commit lands only when its piece actually works.

## Verification

- Set `VAULT_PATH` to a scratch dir; run `track commit "test"`, `track study --topic algo --duration 30`, `track badtype` (expect rejection listing valid types), a `--date` override, and a second `track` into a file that has content *after* `## Log` to prove insert-in-place doesn't reorder anything.
- Byte-compare: original file content must be intact around the insertion point (only the new line added).
- `stats 7` against hand-made daily notes including one malformed line and one `when::`/filename mismatch > 1 day (expect stderr warning, counts still by filename).
- `label`: run against 2 scratch notes; decline at the prompt (files must be untouched); then accept and verify `topic::` line placement. Also test with `claude` absent from PATH (expect clean error).
