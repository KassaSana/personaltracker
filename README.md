# Personal Activity Tracker

CLI that logs completed work into an Obsidian vault as plain Markdown. One file, Python stdlib only, no server or database.

## Setup

Point `VAULT_PATH` at your vault (never hardcoded):

```powershell
$env:VAULT_PATH = "D:\path\to\vault"
```

Put a topic list at `<VAULT_PATH>/topics.txt` (one label per line; `#` comments and blank lines ignored). Needed only for `label`.

## Commands

```
python tracker.py track <type> [detail...] [--date YYYY-MM-DD] [--topic T] [--duration MIN]
python tracker.py stats [7|30]
python tracker.py label
```

Types: `commit`, `pull_request`, `assignment`, `lecture`, `slides`, `application`, `resume`, `study`.

`--topic` and `--duration` (integer minutes) are only valid with `study`.

Examples:

```
python tracker.py track commit "fixed thing"
python tracker.py track study --topic algo --duration 30
python tracker.py stats 7
python tracker.py label
```

## 04:00 rollover

The working day ends at 04:00, not midnight. A `track` at 01:30 is filed on the previous date's daily note. `when::` still records the true wall-clock time. `--date YYYY-MM-DD` overrides the filing date when you need it.

## Notes

- Events go in `<VAULT_PATH>/daily/YYYY-MM-DD.md` under `## Log`.
- `stats` prints a terminal summary and overwrites `<VAULT_PATH>/Stats.md` with Dataview queries.
- `label` sends note titles and headings only to the `claude` CLI, shows a proposal table, and writes `topic::` only after you type `y`.
