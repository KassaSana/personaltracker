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

## Phase 3 — automatic ingestion (only after Phases 0–2 prove what's worth it)

One new command, `t sync`, run manually (later, optionally, by Windows Task Scheduler —
still no daemon, no server):

- **Git/GitHub**: commits and PR events via `gh` CLI / local `git log` across your
  repos. Network allowed here — `sync` is not the write path in spirit; it's batch
  import, and a failure just means "run it again later".
- **Idempotency rule** (the thing that makes sync safe): every ingested event carries
  an `id::` field (e.g. commit hash). Before appending, `sync` scans the target day's
  note for that id and skips duplicates. State stays in the Markdown; re-running is
  always safe.
- **Canvas** (assignments/due dates) and **LeetCode** (accepted submissions) follow the
  same pattern only if two weeks of manual logging showed you actually track them.
- Ingested vs hand-logged stays distinguishable (`src:: sync`), so you can always
  audit where a number came from.

## Phase 4 — close the loop (~ongoing)

Numbers only change behavior if you look at them on a schedule.

- **`t review`**: generates `reviews/YYYY-Www.md` — last week's numbers pre-filled,
  plus three prompts (what worked / what slipped / one change next week). Five minutes
  every Sunday; this is where "see patterns" becomes "act on patterns".
- `label` grows only if used: batch mode over a date range, topics learned from what
  you actually study.

## Definition of "solid" (the quality bar per phase)

1. **Data outlives the tool**: everything remains grep-able Markdown a human can read
   in 10 years with no software. Any feature that breaks this is rejected.
2. **Append-only forever**: the only mutations are appends and the explicit `undo`.
3. **Tested invariants**: parser and inserter covered by `unittest`; run before each
   commit.
4. **One file, stdlib only** stays true through Phase 4. If `tracker.py` passes ~1500
   lines, split by command — not before.
5. **Anything can fail without losing data**: sync can crash mid-run, stats can hit a
   corrupt line — worst case is a warning, never a corrupted note.

## What deliberately stays out

Web UI, mobile app, database, cloud sync (the vault's own sync handles that), auth,
notifications/nagging, time-tracking timers (log completions, not clock time — timers
are the highest-friction feature in existence), and any ML beyond the existing `label`.
Each of these is where personal tools go to die.
