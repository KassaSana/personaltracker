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
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from argparse import Namespace

import tracker

WINDOW_TITLE = "log"
TODAY_LINES = 8
# Study is the only type with a topic and a duration; the fields follow the type.
STUDY_ONLY = ("topic", "duration")


# ---- pure logic (no Tk; this is the part worth testing) ---------------------


def split_extras(text):
    """'diff=easy result=solved' -> ['diff=easy', 'result=solved']."""
    return [word for word in (text or "").split() if word]


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


# ---- the window ------------------------------------------------------------


class QuickAdd(ttk.Frame):
    def __init__(self, master, vault):
        super().__init__(master, padding=10)
        self.vault = vault
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(3, weight=1)

        self.type_var = tk.StringVar(value=tracker.VALID_TYPES[0])
        self.fields = {}

        ttk.Label(self, text="type").grid(row=0, column=0, sticky="w")
        combo = ttk.Combobox(
            self,
            textvariable=self.type_var,
            values=list(tracker.VALID_TYPES),
            state="readonly",
            width=14,
        )
        combo.grid(row=0, column=1, sticky="w", padx=(4, 12))
        combo.bind("<<ComboboxSelected>>", lambda _e: self.sync_study_fields())

        ttk.Label(self, text="detail").grid(row=0, column=2, sticky="w")
        self.fields["detail"] = self.entry(row=0, column=3, columnspan=3)

        for i, (name, width) in enumerate(
            (("topic", 14), ("duration", 8), ("extras", 24))
        ):
            ttk.Label(self, text=name).grid(row=1, column=i * 2, sticky="w", pady=(8, 0))
            self.fields[name] = self.entry(row=1, column=i * 2 + 1, width=width)

        self.status = ttk.Label(self, text="", foreground="grey")
        self.status.grid(row=2, column=0, columnspan=6, sticky="w", pady=(8, 4))

        self.today = tk.Listbox(self, height=TODAY_LINES, activestyle="none")
        self.today.grid(row=3, column=0, columnspan=6, sticky="nsew")
        self.rowconfigure(3, weight=1)

        buttons = ttk.Frame(self)
        buttons.grid(row=4, column=0, columnspan=6, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Undo last", command=self.on_undo).grid(row=0, column=0)
        ttk.Button(buttons, text="Log  (Enter)", command=self.on_log).grid(
            row=0, column=1, padx=(6, 0)
        )

        master.bind("<Return>", lambda _e: self.on_log())
        master.bind("<KP_Enter>", lambda _e: self.on_log())
        master.bind("<Escape>", lambda _e: master.destroy())

        self.sync_study_fields()
        self.refresh()
        self.fields["detail"].focus_set()

    def entry(self, row, column, width=None, columnspan=1):
        widget = ttk.Entry(self, width=width) if width else ttk.Entry(self)
        widget.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="ew",
            padx=(4, 12),
            pady=(8, 0) if row else 0,
        )
        return widget

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
