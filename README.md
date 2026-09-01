# Personal Activity Tracker

CLI that logs completed work into an Obsidian vault as plain Markdown. One file, Python stdlib only, no server or database.

## Setup

One command:

```powershell
python tracker.py setup "D:\path\to\vault"
```

It creates the vault layout (`daily/`, `reviews/`, `templates/Daily.md`, `topics.txt`), never overwriting anything you already have, then prints the PowerShell block with your real paths filled in — `VAULT_PATH`, a `TRACKER_REPOS` list discovered from the repos next to this project, the `t` function and tab completion. Add `--profile` to append it to your profile for you (once; your profile is otherwise left alone).

Everything below is what that block sets up, if you'd rather do it by hand.

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

For tab completion of commands, types and flags, dot-source the completer after that function:

```powershell
. "D:\Personal Projects\personaltracker\completion.ps1"
```

Its word list comes from `t complete`, which reads the argument parser itself — a new flag is completable the day it's added, with no second list to maintain.

Then `t commit "fixed onnx flag"` works from any directory. A bare event type implies `track`, so `t <type> ...` and `t stats` / `t today` / `t undo` / `t label` all work.

## Commands

A bare `t` prints today's log followed by a six-line cheatsheet — the answer to both "did I log that already?" and "what was the flag again?".

```
t <type> [detail...] [--date YYYY-MM-DD] [--topic T] [--duration MIN] [--x K=V ...]
t today [--date YYYY-MM-DD]
t undo  [--date YYYY-MM-DD] [--yes]
t stats [7|30] [--weeks N] [--pipeline] [--csv]
t week   # = t stats 7
t month  # = t stats 30
t dash  [--weeks N]
t sync   [--repo PATH ...] [--root DIR ...] [--days N] [--author EMAIL] [--dry-run] [--no-dash]
t review [--week YYYY-MM-DD] [--print]
t suggest [--days N] [--yes] [--dry-run]
t watch  [--interval SEC] [--idle SEC] [--status]
t label
t gui
t complete [command]   # completion words, for the shell
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

## Logging without a terminal

Copy `templates/Daily.md` into your vault at `<VAULT_PATH>/templates/Daily.md`. Two things then change:

- **New daily notes are seeded from it.** When `track` or `sync` has to create a note, it uses the template and substitutes `{{date}}` — Obsidian's own placeholder, so the same file works with Obsidian's Templates plugin. Without a template the tool writes its usual two-line skeleton.
- **Ticking a box is logging.** The template's `## Log` section holds unticked lines like `- [ ] type:: leetcode | diff:: easy`. The parser only counts `- [x]`, so an unticked box is nothing and a ticked one is an event — no terminal, and it works from Obsidian mobile. Edit the boxes to match the week you actually have.

### The quick-add window — `t gui`

```
t gui                      # from a terminal
pythonw quickadd.py        # no console window at all
```

Three tabs, Ctrl+Tab between them:

- **Log** — type, detail, extras (and topic/duration, enabled only for `study`), the last eight events of the day, and an Undo button. Enter logs, Esc closes.
- **Numbers** — the last six weeks with bars and the trend column, study minutes by topic, the application pipeline, and streaks. Same engine as `t stats --weeks N`, so the window and the terminal can never disagree. It recomputes when you open the tab and after anything you log, not on every keystroke. A button there writes `Dashboard.md` without a terminal.
- **Suggest** — `t suggest` with checkboxes instead of a prompt. Scan N days, select the rows you actually finished, optionally set a difficulty for the picked leetcode rows, and log them. The scan runs off the main thread so the window stays responsive while it reads your history.

Tkinter, so it needs nothing that isn't already in the standard library.

It owns no format and touches no file — every write goes through the same `track` and `undo` the CLI uses, so it cannot invent a line shape the parser won't read back.

For the case this exists for — logging at 1am without opening a terminal — bind it to a key: make a Windows shortcut to `pythonw.exe "D:\Personal Projects\personaltracker\quickadd.py"`, put it on the desktop or Start menu, and set a Shortcut key in its Properties.

A ticked box carries no `when::`, which is honest: the tool doesn't know the time, and the filename is what decides the day anyway. `t undo` never touches those lines — it only removes what the CLI itself wrote.

## Reading the numbers

- `t week` / `t month` — the two windows you actually ask for, aliases of `t stats 7` / `t stats 30`.
- `t stats 7` / `t stats 30` — counts by type, study minutes by topic, logging consistency (`logging: N of 30 days had an event`), and streaks.
- `t stats --weeks 8` — weekly buckets per type with study minutes and a trend column comparing each week against the average of the four before it.
- `t stats --pipeline` — application funnel by `stage::` (applied → oa → phone → onsite → offer) with conversion between stages.
- `t stats --csv` — every event to stdout as CSV, for the day you want a spreadsheet.

Every table carries the same ASCII bars as `Dashboard.md`, scaled to its own largest row — one set of numbers should look like itself wherever you read it.

**Honesty rule:** a week with fewer than 3 logged days reads as `low data`, never as a decline. A drop in the chart should mean a drop in you, not in your logging — watch the `days` column first.

`stats` only prints; it never touches the vault.

## Reading them in Obsidian — `t dash`

```
t dash              # write Stats.md and Dashboard.md, 8 weeks of history
t dash --weeks 12
```

`t sync` runs this for you when it actually imported something, so the numbers you read in Obsidian are never older than your last import. `t sync --no-dash` opts out.

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

## Logging without logging — `t suggest`

```
t suggest                  # propose from the last 3 days, pick what to keep
t suggest --days 7
t suggest --dry-run        # look, write nothing
t suggest --yes            # apply everything, no prompt
```

Reads evidence already sitting on this machine and proposes events. **Nothing is written until you pick.**

```
#   day         at     type         detail                                        from
1   2026-08-17  04:13  leetcode     longest-palindromic-substring                 leetcode
2   2026-08-17  06:23  leetcode     meeting-rooms-ii                              leetcode
3   2026-08-19  21:59  application  Software Engineer, Agents & Automations       ashby

A page you opened is not a problem you solved or a job you applied to.
Pick only what you actually finished.
Apply which? [a]ll, [n]one, or numbers like 1,3-4:
```

Picked leetcode rows then ask for a difficulty (`e`/`m`/`h`, Enter to skip), because the difficulty mix is the one number history can't know and the one that catches an easy-only grind.

**Where it looks.** Chromium history (Chrome, Edge, Brave, Vivaldi, Opera) and Firefox's `places.sqlite`, via stdlib `sqlite3`. The file is copied before reading, so it works while the browser is open and never touches your original. `TRACKER_BROWSERS` overrides discovery with an explicit `;`-separated list of history files.

**What it can see** is an allowlist, and that's the privacy story: `leetcode.com/problems/...`, plus Greenhouse, Lever, Ashby, SmartRecruiters and Workday job URLs. Every other page in your history is invisible to it — it cannot log what it cannot match, so it never reads your mail, your bank or anything else into the vault.

**What it can't know.** History proves a page was *opened*, never that a problem was solved or an application submitted. That's exactly why it proposes instead of writing, and why `--yes` is for when you've already looked. Application *stages* (OA, phone, onsite, offer) arrive by email, which is out of reach under the no-network rule — those stay manual, and they're the ones you remember anyway.

Proposals carry `id::` and `src:: suggest`, so re-running is safe and you can always audit where a number came from. Commits don't appear here: `t sync` imports them exactly, and a commit needs no confirmation because it's already a completion.

## Measuring time — `t watch`

```
t watch                    # watch in this terminal, print sessions as they close
t watch --status           # is a watcher running? which rules file?
t setup --watch-task       # start it invisibly at every login (Task Scheduler)
t setup --watch-task --remove
```

Counts say what you finished; this says where the hours went. Every 5 seconds the
watcher reads the foreground window and whether you are idle (3 minutes without
input stops the clock), classifies the window into a category — `project`,
`assignment`, `applications`, `leetcode`, `review`, or `other` — and appends one
line per work session:

```
- [x] type:: time | when:: 2026-09-01T14:05 | detail:: assignment | duration:: 47 | id:: w20260901T1405-assignment | src:: watch
```

**The privacy boundary: only the category name is ever written.** Window titles and
program names are matched in memory and discarded — nothing else reaches a vault
that syncs. Classification comes from `<VAULT_PATH>/watch-rules.txt`
(`pattern -> category`, first match wins, seeded by setup with the defaults as
comments) layered over built-in rules for the usual suspects (IDEs and terminals →
`project`, leetcode.com → `leetcode`, job boards → `applications`, Canvas/Word/PDF →
`assignment`, Obsidian → `review`). Anything unmatched is `other` — counted, so the
totals stay honest.

Session rules, all tested: a sub-2-minute alt-tab neither splits a session nor
counts against it; sessions under 3 minutes are noise and dropped; a session still
open at 30 minutes is written as a chunk, so a crash or power-off loses at most
half an hour. Two watchers cannot run at once.

**Time is attention, not accomplishment**, so `time` events are excluded from every
count, streak and trend — they feed only the time tables (`t stats`, `Dashboard.md`,
the window's Numbers tab), where each category's hours sit next to the completions
that justify them. `t time ...` by hand is rejected: a typed hour is a guess, and
the chart only carries measurements.

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
