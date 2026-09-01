# Personal Activity Tracker

CLI that logs completed work into an Obsidian vault as plain Markdown. One file, Python stdlib only, no server or database.

## Setup

Point `VAULT_PATH` at your vault (never hardcoded):

```powershell
$env:VAULT_PATH = "D:\path\to\vault"
```

Put a topic list at `<VAULT_PATH>/topics.txt` (one label per line; `#` comments and blank lines ignored). Needed only for `label`.

Optionally point `TRACKER_REPOS` at the repos `sync` should import from — a `;`-separated list on Windows (`:` elsewhere), so `t sync` needs no arguments:

```powershell
$env:TRACKER_REPOS = "D:\Personal Projects\personaltracker;D:\Personal Projects\onnx-thing"
```

### The `t` alias

Typing `python tracker.py track` is already too much friction. Add to your PowerShell `$PROFILE`:

```powershell
$env:VAULT_PATH = "D:\path\to\vault"
function t { & "D:\Personal Projects\personaltracker\t.ps1" @args }
```

Then `t commit "fixed onnx flag"` works from any directory. A bare event type implies `track`, so `t <type> ...` and `t stats` / `t today` / `t undo` / `t label` all work.

## Commands

A bare `t` prints today's log followed by a six-line cheatsheet — the answer to both "did I log that already?" and "what was the flag again?".

```
t <type> [detail...] [--date YYYY-MM-DD] [--topic T] [--duration MIN] [--x K=V ...]
t today [--date YYYY-MM-DD]
t undo  [--date YYYY-MM-DD] [--yes]
t stats [7|30] [--weeks N] [--pipeline] [--csv]
t dash  [--weeks N]
t sync   [--repo PATH ...] [--root DIR ...] [--days N] [--author EMAIL] [--dry-run]
t review [--week YYYY-MM-DD] [--print]
t label
```

Types: `commit`, `pull_request`, `assignment`, `lecture`, `slides`, `application`, `resume`, `study`, `leetcode`, `design`, `interview`.

`--topic` and `--duration` (integer minutes) are only valid with `study`.

`--x key=value` is repeatable and adds arbitrary Dataview inline fields to the same line — typed events without a schema migration. Keys must be word characters and may not shadow the fields the tool owns: `type`, `when`, `detail`, `topic`, `duration`, `id`, `src`.

```
t leetcode two-sum --x diff=easy --x result=solved
t application "NVIDIA swe intern" --x company=nvidia --x stage=applied
t interview "Jane St OA" --x company=janestreet --x stage=oa --x result=pending
t study --topic algo --duration 30
```

`t undo` removes the last line **this tool** wrote in that day's note — the only permitted deletion. Hand-written lines are never touched, and it asks before writing unless you pass `--yes`.

## Reading the numbers

- `t stats 7` / `t stats 30` — counts by type, study minutes by topic, logging consistency (`logging: N of 30 days had an event`), and streaks.
- `t stats --weeks 8` — weekly buckets per type with study minutes and a trend column comparing each week against the average of the four before it.
- `t stats --pipeline` — application funnel by `stage::` (applied → oa → phone → onsite → offer) with conversion between stages.
- `t stats --csv` — every event to stdout as CSV, for the day you want a spreadsheet.

**Honesty rule:** a week with fewer than 3 logged days reads as `low data`, never as a decline. A drop in the chart should mean a drop in you, not in your logging — watch the `days` column first.

`stats` only prints; it never touches the vault.

## Reading them in Obsidian — `t dash`

```
t dash              # write Stats.md and Dashboard.md, 8 weeks of history
t dash --weeks 12
```

`dash` is the only command that overwrites files in the vault root: `Stats.md` (Dataview queries) and `Dashboard.md` (weekly table, difficulty mix, streaks, pipeline, study minutes by topic). Both carry a generated-file header and are rewritten in full each run — put nothing of your own in them.

The weekly table and the study-minutes table carry ASCII bars scaled to their own largest row, so the shape of a month is readable at a glance instead of column-by-column.

## Importing commits — `t sync`

```
t sync --dry-run          # see what would be added, write nothing
t sync                    # import the last 14 days from TRACKER_REPOS
t sync --root "D:\Personal Projects" --days 30
t sync --repo . --author me@example.com
```

Reads local `git log` only — no network, no GitHub, no auth. Repos come from `--repo` / `--root` (a root contributes itself plus its immediate subdirectories that hold a `.git`), falling back to `TRACKER_REPOS`. Each repo's own `git config user.email` decides whose commits count, unless `--author` overrides it.

Imported lines carry two extra fields:

```
- [x] type:: commit | when:: 2026-08-31T14:22 | detail:: fixed onnx flag | repo:: onnx-thing | id:: a1b2c3d4 | src:: sync
```

- `id::` — the short SHA. Before appending, `sync` reads the ids already in that day's note and skips the ones it finds, so **re-running is always safe**. The state lives in the Markdown; there is nothing to drift.
- `src:: sync` — ingested, not hand-logged, so you can always audit where a number came from.

Commits file by the same 04:00 rollover as everything else: a 01:30 commit lands on the previous day's note. A missing `git`, a bad path, or a repo that errors is a warning on stderr — the other repos still import.

## Closing the loop — `t review`

```
t review                       # writes reviews/YYYY-Www.md for the week that just ended
t review --week 2026-08-27     # any date inside the week you want
t review --print               # dump it to the terminal, write nothing
```

Pre-fills last week's numbers (the weekly table with four weeks of context, logging consistency, streaks, difficulty mix, pipeline) and leaves three prompts to answer: what worked, what slipped, one change next week. Five minutes on a Sunday.

Unlike `Stats.md` and `Dashboard.md`, **a review is written once and never regenerated** — it holds your handwriting. If the file exists, `t review` says so and leaves it alone.

## 04:00 rollover

The working day ends at 04:00, not midnight. A `track` at 01:30 is filed on the previous date's daily note. `when::` still records the true wall-clock time. `--date YYYY-MM-DD` overrides the filing date when you need it.

Because the filename is the working-day assignment, `stats` counts by filename and warns (stderr) only when a `when::` inside the reported window differs from its filename by more than one day.

## Notes

- Events go in `<VAULT_PATH>/daily/YYYY-MM-DD.md` under `## Log`. Writes are append-only; existing bytes are never rewritten or reordered — that holds for `sync` too.
- `dash` overwrites two generated notes in the vault root: `Stats.md` and `Dashboard.md`. Both are excluded from `label`. No other read command writes anything.
- `review` writes `<VAULT_PATH>/reviews/YYYY-Www.md`, once, and never touches it again.
- `label` sends note titles and headings only to the `claude` CLI, shows a proposal table, and writes `topic::` only after you type `y`.
- Tests: `python -m unittest test_tracker` — run before every commit.
