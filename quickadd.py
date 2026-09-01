#!/usr/bin/env python3
"""A one-window capture surface for the 1am case: log without opening a terminal.

Deliberately thin. It owns no format and no file handling -- every write goes
through tracker's own `track` and `undo`, so the GUI can never invent a line
shape the parser does not read back.

Run it with pythonw so no console flashes:  pythonw quickadd.py
"""

import contextlib
import io
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from argparse import Namespace
from datetime import datetime, timedelta

import recap
import suggest
import tracker
import watch

WINDOW_TITLE = "Personal Tracker"
TODAY_LINES = 8
# Study is the only type with a topic and a duration; the fields follow the type.
STUDY_ONLY = ("topic", "duration")
TAB_NAMES = ("Recap", "Log", "Numbers")
# Keep generated and rare types available in the CLI without making the quick-add
# dropdown ask about them every time.
MANUAL_TYPES = (
    "leetcode", "study", "application", "assignment", "interview",
    "design", "pull_request", "lecture", "slides", "resume",
)

# Numbers pane: enough weeks to see a trend, few enough to read at a glance.
NUMBERS_WEEKS = 6
NUMBERS_TOPIC_DAYS = 30


# ---- pure logic (no Tk; this is the part worth testing) ---------------------


def split_extras(text):
    """'diff=easy result=solved' -> ['diff=easy', 'result=solved']."""
    return [word for word in (text or "").split() if word]


def is_numbers_tab(name):
    return name == "Numbers"


def format_event(fields):
    """One event as a line for the window: time, type, then whatever it carries."""
    when = (fields.get("when") or "").partition("T")[2] or "--:--"
    rest = [fields.get("detail") or ""]
    for key, value in sorted(fields.items()):
        if key.startswith("_") or key in ("type", "when", "detail"):
            continue
        rest.append("%s=%s" % (key, value))
    tail = "  ".join(part for part in rest if part)
    return "%s  %-12s %s" % (when, fields["type"], tail)


def today_lines(vault, day):
    """Today's events, oldest first, already formatted. Never raises."""
    path = tracker.daily_path(vault, day)
    if not os.path.isfile(path):
        return []
    try:
        events, _skipped, _warnings = tracker.parse_log_file(path, day)
    except OSError:
        return []
    return [format_event(fields) for fields in events]


def numbers_lines(vault, weeks=NUMBERS_WEEKS, today=None):
    """The numbers pane, as plain monospace lines.

    Same engine as `t stats --weeks N`, so the window and the terminal can never
    disagree; the pane only chooses the window. Warnings are swallowed: under
    pythonw there is no stderr to write them to.
    """
    if today is None:
        today = tracker.working_date()
    with contextlib.redirect_stderr(io.StringIO()):
        events, _unparseable = tracker.load_events(vault)

    window = tracker.week_start(today) - timedelta(weeks=weeks - 1)
    buckets = tracker.weekly_buckets(
        [f for f in events if f["_date"] >= window], weeks, today
    )
    headers, rows = tracker.weekly_report(buckets)
    lines = tracker.render_table(*tracker.bar_column(headers, rows, 2))

    lines += ["", "days = days with at least one event. Under %d, read the week as"
              % tracker.MIN_LOGGED_DAYS, "insufficient data, not decline."]

    topics = tracker.study_topic_report(
        [f for f in events if f["_date"] > today - timedelta(days=NUMBERS_TOPIC_DAYS)]
    )
    if topics:
        lines += ["", "study minutes by topic (%d days)" % NUMBERS_TOPIC_DAYS]
        lines += tracker.render_table(*topics)

    times = watch.time_report(
        [f for f in events if f["_date"] > today - timedelta(days=NUMBERS_TOPIC_DAYS)]
    )
    if times:
        lines += ["", "time by category (%d days)" % NUMBERS_TOPIC_DAYS]
        lines += tracker.render_table(*times)

    pipeline = tracker.pipeline_report(events)
    if pipeline:
        lines += ["", "application pipeline (all time)"]
        lines += tracker.render_table(*pipeline)

    lines += ["", "streaks"] + tracker.streak_lines(events, today)
    return lines


def run_tracker(func, **kwargs):
    """Call a tracker command, trapping its exit and output.

    Returns (ok, message). die() writes to stderr and exits; under pythonw there
    is no stderr at all, so both streams are captured either way.
    """
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            func(Namespace(**kwargs))
    except SystemExit:
        message = (err.getvalue() or out.getvalue()).strip()
        return False, message.splitlines()[0] if message else "failed"
    except OSError as exc:
        return False, str(exc)
    return True, (out.getvalue().strip() or "")


def log_event(event_type, detail, topic, duration, extras):
    """Append one event through tracker.cmd_track. Returns (ok, message)."""
    if duration:
        try:
            duration = int(duration)
        except ValueError:
            return False, "duration must be whole minutes"
    else:
        duration = None
    return run_tracker(
        tracker.cmd_track,
        event_type=event_type,
        detail=[detail] if detail else [],
        date=None,
        topic=topic or None,
        duration=duration,
        extra=split_extras(extras),
    )


def undo_last():
    return run_tracker(tracker.cmd_undo, date=None, yes=True)


def scan_suggestions(vault, days):
    """Proposals not already in the vault. Safe to call off the main thread: it
    reads copies of history files and touches no widget."""
    since = datetime.now() - timedelta(days=days)
    with contextlib.redirect_stderr(io.StringIO()):
        found = suggest.gather(since)
        return suggest.already_logged(vault, found)


def apply_suggestions(vault, picked, difficulty=""):
    """Write picked proposals through the normal writer. Returns (ok, message)."""
    if not picked:
        return False, "nothing selected"
    if difficulty:
        for proposal in picked:
            if proposal["type"] == "leetcode":
                proposal["extras"] = [
                    pair for pair in proposal["extras"] if pair[0] != "diff"
                ] + [("diff", difficulty)]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            added, skipped = tracker.append_commit_lines(
                vault, suggest.to_log_lines(picked), False
            )
    except OSError as exc:
        return False, str(exc)
    return True, "logged %d event(s); %d already there" % (added, skipped)


# ---- the window ------------------------------------------------------------


class QuickAdd(ttk.Frame):
    """Recap first, with manual logging and the shared numbers engine beside it."""

    def __init__(self, master, vault):
        super().__init__(master, padding=8)
        self.vault = vault
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # One status line under both tabs: every action reports in the same place.
        self.status = ttk.Label(self, text="", foreground="grey")
        self.status.grid(row=1, column=0, sticky="w", pady=(6, 0))

        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        tab_frames = [ttk.Frame(self.tabs, padding=8) for _ in TAB_NAMES]
        for frame, label in zip(tab_frames, TAB_NAMES):
            self.tabs.add(frame, text=label)
        self.tabs.bind("<<NotebookTabChanged>>", lambda _e: self.refresh_numbers())

        self.build_suggest_tab(tab_frames[0])
        self.build_log_tab(tab_frames[1])
        self.build_numbers_tab(tab_frames[2])

        master.bind("<Return>", self.on_enter)
        master.bind("<KP_Enter>", self.on_enter)
        master.bind("<Escape>", lambda _e: master.destroy())
        master.bind("<Control-Tab>", lambda _e: self.next_tab())

        self.sync_study_fields()
        self.refresh()
        self.on_scan()

    # -- layout --

    def on_enter(self, _event=None):
        if self.tabs.index("current") == 1:
            self.on_log()

    def build_log_tab(self, parent):
        parent.columnconfigure(3, weight=1)
        parent.rowconfigure(3, weight=1)
        self.type_var = tk.StringVar(value=MANUAL_TYPES[0])
        self.fields = {}

        ttk.Label(parent, text="type").grid(row=0, column=0, sticky="w")
        combo = ttk.Combobox(
            parent,
            textvariable=self.type_var,
            values=list(MANUAL_TYPES),
            state="readonly",
            width=14,
        )
        combo.grid(row=0, column=1, sticky="w", padx=(4, 12))
        combo.bind("<<ComboboxSelected>>", lambda _e: self.sync_study_fields())

        ttk.Label(parent, text="detail").grid(row=0, column=2, sticky="w")
        self.fields["detail"] = self.entry(parent, row=0, column=3, columnspan=3)

        for i, (name, width) in enumerate((("topic", 14), ("duration", 8))):
            ttk.Label(parent, text=name).grid(row=1, column=i * 2, sticky="w", pady=(8, 0))
            self.fields[name] = self.entry(parent, row=1, column=i * 2 + 1, width=width)

        self.advanced_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            parent, text="Advanced fields", variable=self.advanced_var,
            command=self.toggle_advanced_fields,
        ).grid(row=1, column=4, columnspan=2, sticky="e", pady=(8, 0))
        self.extras_label = ttk.Label(parent, text="extra fields")
        self.extras_label.grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.fields["extras"] = self.entry(parent, row=2, column=1, columnspan=5)
        self.toggle_advanced_fields()

        self.today = tk.Listbox(parent, height=TODAY_LINES, activestyle="none")
        self.today.grid(row=3, column=0, columnspan=6, sticky="nsew", pady=(10, 0))

        buttons = ttk.Frame(parent)
        buttons.grid(row=4, column=0, columnspan=6, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Undo last", command=self.on_undo).grid(row=0, column=0)
        ttk.Button(buttons, text="Log  (Enter)", command=self.on_log).grid(
            row=0, column=1, padx=(6, 0)
        )

    def build_numbers_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        # Read-only and monospace: the tables are column-aligned text, and the bars
        # only line up in a fixed-width font.
        self.numbers = tk.Text(
            parent,
            height=16,
            width=72,
            font=tkfont.nametofont("TkFixedFont"),
            wrap="none",
            state="disabled",
            borderwidth=0,
            background=parent.winfo_toplevel().cget("background"),
        )
        self.numbers.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(parent, orient="vertical", command=self.numbers.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.numbers.configure(yscrollcommand=bar.set)

        ttk.Button(parent, text="Write Dashboard.md", command=self.on_dash).grid(
            row=1, column=0, columnspan=2, sticky="e", pady=(8, 0)
        )

    def build_suggest_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)
        self.proposals = []

        controls = ttk.Frame(parent)
        controls.grid(row=0, column=0, sticky="ew")
        ttk.Label(controls, text="recap evidence from the last").grid(row=0, column=0)
        self.days_var = tk.StringVar(value=str(suggest.DEFAULT_DAYS))
        ttk.Spinbox(controls, from_=1, to=90, width=4, textvariable=self.days_var).grid(
            row=0, column=1, padx=4
        )
        ttk.Label(controls, text="days of browser history").grid(row=0, column=2)
        self.scan_button = ttk.Button(controls, text="Refresh", command=self.on_scan)
        self.scan_button.grid(row=0, column=3, padx=(12, 0))

        ttk.Label(
            parent,
            # The same warning the CLI prints, for the same reason.
            text="Git facts import automatically. Select browser evidence only when completed.",
            foreground="grey",
        ).grid(row=1, column=0, sticky="w", pady=(8, 4))

        self.recap_summary = tk.Text(
            parent, height=7, font=tkfont.nametofont("TkFixedFont"), wrap="none",
            state="disabled", borderwidth=0,
            background=parent.winfo_toplevel().cget("background"),
        )
        self.recap_summary.grid(row=2, column=0, sticky="ew", pady=(4, 8))

        self.suggest_list = tk.Listbox(
            parent, selectmode="extended", height=10,
            font=tkfont.nametofont("TkFixedFont"), activestyle="none",
        )
        self.suggest_list.grid(row=3, column=0, sticky="nsew")

        actions = ttk.Frame(parent)
        actions.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        actions.columnconfigure(3, weight=1)
        ttk.Label(actions, text="difficulty for picked leetcode").grid(row=0, column=0)
        self.diff_var = tk.StringVar(value="")
        ttk.Combobox(
            actions, textvariable=self.diff_var, width=8, state="readonly",
            values=["", "easy", "medium", "hard"],
        ).grid(row=0, column=1, padx=(4, 0))
        ttk.Label(actions, text="what did you learn? (optional)").grid(row=1, column=0, pady=(8, 0))
        self.learning_var = tk.StringVar(value="")
        ttk.Entry(actions, textvariable=self.learning_var, width=36).grid(
            row=1, column=1, columnspan=3, sticky="ew", padx=(4, 8), pady=(8, 0)
        )
        ttk.Button(actions, text="Finish recap", command=self.on_apply).grid(row=0, column=4, rowspan=2)

    def entry(self, parent, row, column, width=None, columnspan=1):
        widget = ttk.Entry(parent, width=width) if width else ttk.Entry(parent)
        widget.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="ew",
            padx=(4, 12),
            pady=(8, 0) if row else 0,
        )
        return widget

    def next_tab(self):
        order = self.tabs.tabs()
        self.tabs.select(order[(order.index(self.tabs.select()) + 1) % len(order)])
        return "break"

    def sync_study_fields(self):
        """topic and duration exist only for study; grey them out otherwise.

        Extras clear on a type change too: `diff=easy` repeating across five
        leetcode entries is the point, silently riding along to an application
        is not.
        """
        self.fields["extras"].delete(0, "end")
        state = "normal" if self.type_var.get() == "study" else "disabled"
        for name in STUDY_ONLY:
            widget = self.fields[name]
            if state == "disabled":
                widget.delete(0, "end")
            widget.configure(state=state)

    def toggle_advanced_fields(self):
        action = "grid" if self.advanced_var.get() else "grid_remove"
        getattr(self.extras_label, action)()
        getattr(self.fields["extras"], action)()

    def value(self, name):
        return self.fields[name].get().strip()

    def say(self, text, ok=True):
        self.status.configure(text=text, foreground="grey" if ok else "firebrick")

    def refresh(self):
        self.today.delete(0, "end")
        lines = today_lines(self.vault, tracker.working_date())
        for line in lines[-TODAY_LINES:]:
            self.today.insert("end", line)
        if not lines:
            self.today.insert("end", "(nothing logged today)")
        self.numbers_stale = True
        if self.showing_numbers():
            self.refresh_numbers()

    def showing_numbers(self):
        return is_numbers_tab(str(self.tabs.tab(self.tabs.select(), "text")))

    def refresh_numbers(self):
        """Recompute on demand only: reading every note is too much work to do on
        each keystroke, and the pane is invisible most of the time."""
        if not self.showing_numbers() or not getattr(self, "numbers_stale", True):
            return
        self.numbers.configure(state="normal")
        self.numbers.delete("1.0", "end")
        self.numbers.insert("1.0", "\n".join(numbers_lines(self.vault)))
        self.numbers.configure(state="disabled")
        self.numbers_stale = False

    def on_log(self):
        ok, message = log_event(
            self.type_var.get(),
            self.value("detail"),
            self.value("topic") if self.type_var.get() == "study" else "",
            self.value("duration") if self.type_var.get() == "study" else "",
            self.value("extras"),
        )
        if not ok:
            self.say(message, ok=False)
            return
        for name in ("detail",) + STUDY_ONLY:
            if str(self.fields[name].cget("state")) != "disabled":
                self.fields[name].delete(0, "end")
        self.say("logged %s" % self.type_var.get())
        self.refresh()
        self.fields["detail"].focus_set()

    def on_undo(self):
        if not messagebox.askyesno("Undo", "Remove the last line t wrote today?"):
            return
        ok, message = undo_last()
        self.say(message or ("removed" if ok else "nothing to undo"), ok=ok)
        self.refresh()

    def on_scan(self):
        """Reading 20-odd history files takes seconds, so it happens off the main
        thread. The worker only puts its result on a queue -- Tk is not thread-safe,
        and even scheduling with after() from another thread reaches into the Tcl
        interpreter from the wrong one. Every widget call stays on the main thread,
        which polls."""
        try:
            days = max(1, int(self.days_var.get()))
        except ValueError:
            self.say("days must be a whole number", ok=False)
            return

        self.scan_button.configure(state="disabled")
        self.say("scanning %d days of history..." % days)
        self.suggest_list.delete(0, "end")

        results = queue.Queue()

        def work():
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    added, _skipped, warning = recap.sync_day(
                        self.vault, tracker.working_date(), dry_run=False
                    )
                    if added:
                        tracker.write_generated_notes(self.vault)
                results.put((scan_suggestions(self.vault, days), None, added, warning))
            except Exception as exc:  # a scan must never take the window down
                results.put(([], str(exc), 0, ""))

        threading.Thread(target=work, daemon=True).start()
        self.poll_scan(results)

    def poll_scan(self, results):
        try:
            found, error, imported, warning = results.get_nowait()
        except queue.Empty:
            self.after(100, lambda: self.poll_scan(results))
            return
        self.scan_done(found, error, imported, warning)

    def scan_done(self, found, error, imported=0, warning=""):
        self.scan_button.configure(state="normal")
        self.proposals = found
        self.recap_summary.configure(state="normal")
        self.recap_summary.delete("1.0", "end")
        self.recap_summary.insert(
            "1.0", "\n".join(recap.summary_lines(
                recap.events_for_day(self.vault, tracker.working_date())
            ))
        )
        self.recap_summary.configure(state="disabled")
        if error:
            self.say(error, ok=False)
            return
        if not found:
            self.say("imported %d Git event(s); nothing to confirm%s" % (
                imported, ("; " + warning) if warning else ""
            ))
            self.suggest_list.insert("end", "(nothing new)")
            return
        for line in suggest.render(found)[1:]:  # drop the header row
            self.suggest_list.insert("end", line)
        self.say("imported %d Git event(s); %d proposal(s) to confirm" % (imported, len(found)))

    def on_apply(self):
        picked = [
            self.proposals[i]
            for i in self.suggest_list.curselection()
            if i < len(self.proposals)
        ]
        learning = self.learning_var.get()
        ok, message = apply_suggestions(self.vault, picked, self.diff_var.get()) if picked else (True, "logged 0 event(s)")
        try:
            learned, _skipped = recap.write_learning(
                self.vault, tracker.working_date(), learning
            )
        except OSError as exc:
            self.say(str(exc), ok=False)
            return
        if not picked and not learned:
            self.say("nothing selected and no learning note", ok=False)
            return
        with contextlib.redirect_stdout(io.StringIO()):
            tracker.write_generated_notes(self.vault)
        self.learning_var.set("")
        self.say("%s; logged %d learning note(s)" % (message, learned), ok=ok)
        # Applied rows are logged now, so drop them rather than offering them twice.
        for index in sorted(self.suggest_list.curselection(), reverse=True):
            self.suggest_list.delete(index)
            if index < len(self.proposals):
                self.proposals.pop(index)
        self.refresh()

    def on_dash(self):
        ok, message = run_tracker(tracker.cmd_dash, weeks=tracker.DASH_WEEKS)
        self.say(message.splitlines()[-1] if message else "wrote the notes", ok=ok)


def main():
    try:
        vault = tracker.vault_path()
    except SystemExit:
        # No console under pythonw: say it in a dialog instead of dying silently.
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(WINDOW_TITLE, "VAULT_PATH is not set to an existing directory.")
        return 1

    root = tk.Tk()
    root.title(WINDOW_TITLE)
    root.attributes("-topmost", True)
    QuickAdd(root, vault)
    root.update_idletasks()
    root.minsize(root.winfo_reqwidth(), root.winfo_reqheight())
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
