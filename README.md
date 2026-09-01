# Personal Activity Tracker

CLI that logs completed work into an Obsidian vault as plain Markdown. One file, Python stdlib only, no server or database.

## Setup

Point `VAULT_PATH` at your vault (never hardcoded):

```powershell
$env:VAULT_PATH = "D:\path\to\vault"
```

Put a topic list at `<VAULT_PATH>/topics.txt` (one label per line; `#` comments and blank lines ignored). Needed only for `label`.

### The `t` alias

Typing `python tracker.py track` is already too much friction. Add to your PowerShell `$PROFILE`:

```powershell
$env:VAULT_PATH = "D:\path\to\vault"
function t { & "D:\Personal Projects\personaltracker\t.ps1" @args }
```

Then `t commit "fixed onnx flag"` works from any directory. A bare event type implies `track`, so `t <type> ...` and `t stats` / `t today` / `t undo` / `t label` all work.

## Commands

```
t <type> [detail...] [--date YYYY-MM-DD] [--topic T] [--duration MIN] [--x K=V ...]
t today [--date YYYY-MM-DD]
t undo  [--date YYYY-MM-DD] [--yes]
t stats [7|30] [--weeks N] [--pipeline] [--csv]
t label
```

Types: `commit`, `pull_request`, `assignment`, `lecture`, `slides`, `application`, `resume`, `study`, `leetcode`, `design`, `interview`.

`--topic` and `--duration` (integer minutes) are only valid with `study`.

`--x key=value` is repeatable and adds arbitrary Dataview inline fields to the same line — typed events without a schema migration. Keys must be word characters and may not shadow `type`/`when`/`detail`/`topic`/`duration`.

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

## 04:00 rollover

The working day ends at 04:00, not midnight. A `track` at 01:30 is filed on the previous date's daily note. `when::` still records the true wall-clock time. `--date YYYY-MM-DD` overrides the filing date when you need it.

Because the filename is the working-day assignment, `stats` counts by filename and warns (stderr) only when a `when::` inside the reported window differs from its filename by more than one day.

## Notes

- Events go in `<VAULT_PATH>/daily/YYYY-MM-DD.md` under `## Log`. Writes are append-only; existing bytes are never rewritten or reordered.
- `stats` overwrites two generated notes in the vault root: `Stats.md` (Dataview queries) and `Dashboard.md` (weekly table, difficulty mix, streaks, pipeline). Both are excluded from `label`.
- `label` sends note titles and headings only to the `claude` CLI, shows a proposal table, and writes `topic::` only after you type `y`.
- Tests: `python -m unittest test_tracker` — run before every commit.
