# ROADMAP — from tool to product

Who this is for: a computer engineering student applying to jobs, grinding leetcode and
design problems, taking classes — who wants to see behavioral patterns and
improvement/decline **in numbers** over months.

The product is still *for one person*. "Product-quality" here means: capture never gets
skipped, numbers never lie, and the data outlives the code. It does NOT mean web app,
accounts, or dashboards-as-a-service — those add maintenance, and maintenance kills
personal tools.

## The one principle everything hangs on

**A decline in your chart must mean a decline in you, not a decline in your logging.**

Self-tracking dies from friction, not missing features. If logging an event takes more
than ~5 seconds, the habit collapses around week 3 and every trend after that is noise.
So the build order is: (1) make capture near-zero cost, (2) build the numbers engine,
(3) automate capture for what proved valuable, (4) close the loop with weekly review.
Features that don't serve one of those four don't get built.

---

## Phase 0 — now → 2 weeks: use it, don't build it

Track daily with the current tool exactly as-is. Keep a `FRICTION.md` note: every time
you skip logging something, or wish a command existed, write one line. That file *is*
the Phase 1 spec — build only what shows up in it. (This was already the plan for
GitHub/Canvas; it applies to everything.)

Meta-metric to watch: **days-with-at-least-one-event**. If that drops, fix friction
before adding anything.

## Phase 1 — capture at near-zero cost (~a weekend)

- **Shell alias `t`** so `t commit "fixed onnx flag"` works from any directory
  (PowerShell profile function; document in README). Typing `python tracker.py track`
  is already too much friction.
- **Extend the type list** to match the actual life being tracked:
  `leetcode`, `design` (system-design problems), `interview` (OA / phone / onsite),
  keeping the existing eight. Still a fixed, rejected-with-message list.
- **Optional structured extras per event**: accept `--x key=value` (repeatable),
  serialized as more Dataview inline fields on the same line. This gives typed events
  without schema migrations:
  - `t leetcode two-sum --x diff=easy --x result=solved`
  - `t application "NVIDIA swe intern" --x company=nvidia --x stage=applied`
  - `t interview "Jane St OA" --x company=janestreet --x stage=oa --x result=pending`
  Parser already reads arbitrary `key:: value` fields, so `stats` keeps working.
- **`t today`** — print today's log lines (did I already log that?).
- **`t undo`** — remove the last line *this tool* appended today (the only permitted
  deletion; still never touches other content).
- Small quality floor: a real test file (`test_tracker.py`, stdlib `unittest`) locking
  the two invariants that matter — append-only insertion and line parsing round-trip.

## Phase 2 — the numbers engine (~a week, the actual point of the product)

All computed from the Markdown at read time. No cache, no index — same rule as before.

- **`t stats --weeks N`** (default 8): weekly buckets per type, with week-over-week
  delta and a 4-week rolling average. This is the improvement/decline view:

  ```
  week        lc  study(min)  apps  commits
  2026-08-31   9      340       5      12     ▲ vs 4wk avg
  2026-08-24   6      280       2      15     ▼
  ```
- **Streaks**: current + longest streak of days-with-any-event, and per-type for the
  habits that matter (leetcode, study).
- **Pipeline view for job apps**: `t stats --pipeline` — count by `stage::`
  (applied → oa → phone → onsite → offer/reject) and conversion between stages. This
  is where patterns show up ("50 apps, 2 OAs" vs "10 apps, 4 OAs" are different
  problems).
- **Leetcode difficulty mix**: solved counts by `diff::` per week — catches the
  "grinding easies to feel productive" pattern.
- **`t stats --csv`** — dump events as CSV to stdout for the day you want a real
  spreadsheet/plot; costs nothing to maintain.
- **`Dashboard.md`** in the vault (generated, like Stats.md): the weekly table +
  streaks + pipeline as Dataview blocks, so the numbers live inside Obsidian too.
- **Honesty features**: logging-consistency shown alongside every trend (events/day of
  logging), so a dip in numbers on a low-logging week renders as "insufficient data",
  not "decline". Beware Goodhart: pick 3–4 metrics you actually believe in — apps/week,
  problems/week by difficulty, study min/topic, streak — and resist adding more.

## Phase 3 — automatic ingestion — **shipped (git only)**

One new command, `t sync`, run manually (later, optionally, by Windows Task Scheduler —
still no daemon, no server):

- **Git**: commits across your repos via local `git log`. Repos come from `--repo` /
  `--root` or the `TRACKER_REPOS` env var. `sync` is not the write path in spirit; it's
  batch import, and a failure just means "run it again later".
  - **Deferred: PR events via `gh`.** It needs auth and a network round-trip, and no
    line in `FRICTION.md` asks for it yet. Build it when one does.
- **Idempotency rule** (the thing that makes sync safe): every ingested event carries
  an `id::` field (e.g. commit hash). Before appending, `sync` scans the target day's
  note for that id and skips duplicates. State stays in the Markdown; re-running is
  always safe.
- **LeetCode** arrived in Phase 6 by a different route — browser history rather than
  the site's API, proposed rather than imported. **Canvas** follows the same pattern
  only if two weeks of manual logging show you actually track it.
- Ingested vs hand-logged stays distinguishable (`src:: sync`), so you can always
  audit where a number came from.

## Phase 4 — close the loop — **`t review` shipped**

Numbers only change behavior if you look at them on a schedule.

- **`t review`**: generates `reviews/YYYY-Www.md` — last week's numbers pre-filled,
  plus three prompts (what worked / what slipped / one change next week). Five minutes
  every Sunday; this is where "see patterns" becomes "act on patterns". Written once and
  never regenerated: it holds your handwriting.
- `label` grows only if used: batch mode over a date range, topics learned from what
  you actually study.
  - **Deferred, on purpose.** "Only if used" is the gate, and `FRICTION.md` is empty.
    Building it now would break the rule the whole roadmap hangs on.

## Phase 5 — ease of use — **shipped**

Not new numbers; the same numbers with less friction between you and them.

- **Bars in `Dashboard.md`** — the weekly table and study-minutes table carry ASCII
  bars scaled to their own largest row. A shape reads in no time; a column of
  integers doesn't.
- **`t dash` split out of `t stats`** — `stats` printed numbers *and* overwrote two
  vault notes, inconsistently (`--csv` skipped the write, `--pipeline` didn't).
  Writing is now one command that names what it wrote. Reads never write.
- **Bare `t`** prints today's log plus a short cheatsheet instead of argparse's
  usage blob, and **typos get a suggestion** (`t leetcod` → "Did you mean leetcode?").
- **`t week` / `t month`** — the two windows actually asked for, by name.
- **Daily-note template** at `<VAULT_PATH>/templates/Daily.md`, with unticked
  `- [ ] type:: ...` boxes. Ticking one in Obsidian *is* logging: no terminal,
  works on mobile, no new code path (the parser only ever counted `- [x]`).
- **PowerShell tab completion**, sourced from `t complete`, which walks the parser.
- **`t gui`** — a tkinter window (`quickadd.py`) with two tabs: **Log**, for the 1am
  case where opening a terminal is the reason the event never gets logged, and
  **Numbers**, the last six weeks with bars, study minutes by topic and streaks.
  It owns no format and no engine: writes go through `track` / `undo`, numbers come
  from `weekly_report` / `streak_lines`, so the window cannot disagree with the CLI.
- **Bars everywhere, not just in the notes** — `t stats` renders the same tables the
  dashboard does. One set of numbers should look like itself wherever you read it.
- **`sync` refreshes the generated notes** when it actually imported something, so
  what Obsidian shows is never older than the last import. `--no-dash` opts out.

Why a window is not a violation of the exclusion list below: it adds no server, no
dependency, no account, and no state. It is capture, which is the one thing this
roadmap says is worth spending on. A *dashboard* GUI would be the violation —
Obsidian already renders that, which is why `t dash` writes notes instead.

## Phase 6 — capture without typing — **`t suggest` shipped**

The goal behind the whole project: see what you have been doing without having to log
it. `sync` did that for commits; this does it for the two things that were still
typed by hand.

- **`t suggest`** reads local browser history (Chromium + Firefox, stdlib `sqlite3`,
  file copied before reading so it works while the browser is open) and proposes
  leetcode problems and job applications. Company, job title and timestamp all come
  free from the URL; `id::` and `src:: suggest` make re-running safe and auditable.
- **The allowlist is the privacy boundary.** It matches leetcode problem URLs and five
  job boards, and is blind to every other page. It cannot log what it cannot match.
- **It proposes; you pick.** History proves a page was *opened*, never that a problem
  was solved or an application submitted. Auto-writing those would break the one
  principle above — a number would stop meaning "I did a thing". Picked leetcode rows
  ask for a difficulty, since that is what history cannot know and what catches an
  easy-only grind.
- **Deliberately not built**: a foreground-window watcher. It needs a background
  process, measures attention rather than accomplishment, and would read every window
  title on the machine into a synced vault. If full activity tracking is ever wanted,
  run ActivityWatch and read its database — do not grow one here.
- **Deliberately not built**: LeetCode's GraphQL API. It would give exact solved-counts
  with difficulty, and it was offered and declined: the no-network rule is worth more
  than the precision. Application stages (OA, phone, onsite) live in email and stay
  manual for the same reason.

## Phase 7 — make it start — **shipped**

The project was complete and unused: nothing in the repo created a vault, so
`VAULT_PATH` was unset and every command failed on a machine that had just cloned it.

- **`t setup [path]`** builds the vault, seeds the template and a starter `topics.txt`,
  and prints the PowerShell block with real paths. `--profile` appends it once.
  Non-destructive by rule: your files and your profile are never rewritten.
- **Suggest tab in the window**, so the no-typing path does not require a terminal.
- **Application pipeline in the Numbers pane** — apps → OA → phone → onsite, with
  conversion, which is the number the job hunt actually turns on.

## Definition of "solid" (the quality bar per phase)

1. **Data outlives the tool**: everything remains grep-able Markdown a human can read
   in 10 years with no software. Any feature that breaks this is rejected.
2. **Append-only forever**: the only mutations are appends and the explicit `undo`.
3. **Tested invariants**: parser and inserter covered by `unittest`; run before each
   commit.
4. **Stdlib only, and `tracker.py` under ~1500 lines.** It sits near 1500 after
   Phase 5, so the split has started: anything sizeable now gets its own file with a
   thin subcommand in `tracker.py` (`quickadd.py` behind `t gui` is the first). The
   `# ---- section ----` banners still carry navigability inside it.
5. **Anything can fail without losing data**: sync can crash mid-run, stats can hit a
   corrupt line — worst case is a warning, never a corrupted note.

## What deliberately stays out

Web UI (a local tkinter capture window is not one — see Phase 5), mobile app, database, cloud sync (the vault's own sync handles that), auth,
notifications/nagging, time-tracking timers (log completions, not clock time — timers
are the highest-friction feature in existence), and any ML beyond the existing `label`.
Each of these is where personal tools go to die.
