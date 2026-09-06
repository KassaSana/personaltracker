# Personal Activity Tracker

A private, offline-first tracker for completed work and focused time. It writes
plain Markdown into an Obsidian vault, so the data remains useful even if this
code disappears.

## Setup

```powershell
python tracker.py setup "D:\path\to\vault" --profile
```

This creates the vault layout without overwriting existing files and adds the
`t` command to your PowerShell profile. Open a new terminal afterward.

If you prefer to configure it manually:

```powershell
$env:VAULT_PATH = "D:\path\to\vault"
$env:TRACKER_REPOS = "D:\repo-one;D:\repo-two"
function t { & "D:\Personal Projects\personaltracker\t.ps1" @args }
. "D:\Personal Projects\personaltracker\completion.ps1"
```

`VAULT_PATH` is required. `TRACKER_REPOS` is optional and tells recap/sync which
local Git repositories belong to you.

## The four actions

```powershell
t recap                         # collect today's evidence
t leetcode two-sum              # log something recap could not see
t week                          # read counts, time and streaks
t review                        # choose one change for next week
```

A bare `t` shows today's events and repeats these four actions. That is the
whole everyday workflow.

### Recap

`t recap` imports exact commits from local Git, asks you to confirm supported
browser evidence, and offers one optional learning note. Opening a page is not
treated as completion: LeetCode, job-board, CodeSignal, and Canvas visits are
only proposals until you select them.

```powershell
t recap
t recap --date 2026-09-01
t recap --dry-run
```

### Manual logging

```text
t <type> [detail...] [--date D] [--topic T] [--duration MIN] [--x K=V]
```

Flags can appear before or after the detail:

```powershell
t study "graph review" --topic algorithms --duration 25
t study --topic algorithms --duration 25 "graph review"
t application "NVIDIA internship" --x company=nvidia --x stage=applied
```

Types are `commit`, `pull_request`, `assignment`, `lecture`, `slides`,
`application`, `resume`, `study`, `leetcode`, `design`, `interview`, `merge`,
`assessment`, and `learning`. Use `t undo` to remove the last line written by
the tool; it never removes a hand-written or Obsidian-created line.

### Week and review

`t week` shows the last seven days. `t month` shows 30 days, and
`t stats --weeks 8` shows weekly trends. Weeks with fewer than three logged days
are marked `low data` instead of pretending that incomplete logging is decline.

`t review` creates last week's `reviews/YYYY-Www.md` once, with the numbers and
three short prompts. It never regenerates the note after you write in it.

## Window

```powershell
t gui
```

The small Tkinter window has four tabs:

- **Recap** collects evidence and learning.
- **Log** exposes common manual types; generic `key=value` fields are hidden
  behind **Advanced fields**.
- **Numbers** shows six weeks, study minutes, focused time, the application
  pipeline, and streaks.
- **Live** shows the foreground app, its classified category, idle time, and
  whether `t watch` is running. It refreshes every two seconds; raw window
  titles and URLs are never written to the vault.
  It also shows a safe matched signal, such as `leetcode` or `canvas`, to make
  active Chrome activity easy to distinguish without displaying the full title.

Steam and PAL World are classified as `gaming` by default. Add custom rules to
the vault's `watch-rules.txt` when an app needs a different category.
Recognized browser pages are tracked from the active tab; generic Chrome,
Edge, Firefox, Brave, and Opera windows are ignored so idle tabs do not count.

Use the **Dark mode** button in the upper-right corner to switch the window
between light and dark mode.

The window uses the same writers and numbers engine as the CLI. Run it with
`pythonw quickadd.py` or bind that command to a Windows shortcut to avoid a
console window. The CLI works without Tkinter; only `t gui` needs optional Tk
support.

### One-click Windows shortcut

After Python is installed, open PowerShell in this folder and run:

```powershell
.\install_shortcut.ps1
```

The script asks for your Obsidian vault path, creates the vault layout if needed,
saves `VAULT_PATH` for your Windows user, and creates **Personal Tracker** on
your desktop. After that, double-clicking the desktop icon opens the window
without a terminal. Run the script again if the vault location changes.

## Optional automation

- `t sync` imports local Git commits idempotently.
- `t suggest` proposes supported events from local browser history.
- `t watch` measures foreground time by category; only category names reach the
  vault, never raw window titles or URLs.
- `t setup --watch-task` starts the watcher at login through Task Scheduler.
- `t dash` writes generated `Stats.md` and `Dashboard.md` notes.
- `t stats --csv` exports all parsed events to standard output.
- `t label` labels recent notes through the optional `claude` CLI after explicit
  confirmation.

Run `t --help` or `t <command> --help` for every flag.

## Markdown record

Events live under `## Log` in `daily/YYYY-MM-DD.md`:

```markdown
- [x] type:: study | when:: 2026-09-01T14:54 | detail:: graph review | topic:: algorithms | duration:: 25
```

Daily-note writes preserve every existing byte around the inserted line.
Imported events carry `id::` and `src::` fields, making reruns safe and their
origin auditable. `Stats.md` and `Dashboard.md` are the only overwritable notes.

The template at `templates/Daily.md` contains unticked examples. Ticking one in
Obsidian counts as logging, including on mobile.

## Working-day rollover

The working day changes at 04:00. An event logged at 01:30 is filed in the
previous daily note, while `when::` still records its actual time. Use
`--date YYYY-MM-DD` to override the filing date.

## Project layout

- `tracker.py` contains the CLI, Markdown I/O, and reports.
- `sync.py`, `suggest.py`, `watch.py`, and `recap.py` collect optional evidence.
- `quickadd.py` provides the Tkinter window.
- `bootstrap.py`, `review.py`, and `label.py` implement their matching commands.
- `test_tracker.py` is the standard-library test suite.

## Verify

```powershell
python -m unittest test_tracker
```
