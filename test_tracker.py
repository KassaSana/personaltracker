#!/usr/bin/env python3
"""Invariant tests: append-only writes, parse round-trip, and the numbers engine."""

import contextlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import date, datetime, timedelta, timezone
from io import StringIO

import tracker


class VaultTestCase(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp(prefix="tracker-test-")
        self.addCleanup(shutil.rmtree, self.vault, True)
        os.environ["VAULT_PATH"] = self.vault
        self.addCleanup(os.environ.pop, "VAULT_PATH", None)

    def daily(self, day):
        return os.path.join(self.vault, "daily", "%s.md" % day)

    def write_daily(self, day, content):
        os.makedirs(os.path.join(self.vault, "daily"), exist_ok=True)
        tracker.write_text(self.daily(day), content)

    def read_daily(self, day):
        return tracker.read_text(self.daily(day))

    def run_cli(self, *argv):
        out, err = StringIO(), StringIO()
        old = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            tracker.main(list(argv))
        finally:
            sys.stdout, sys.stderr = old
        return out.getvalue(), err.getvalue()


class TestAppendOnly(VaultTestCase):
    """The one invariant that must never break: existing bytes survive a track."""

    def test_bytes_around_insertion_are_identical(self):
        original = (
            "# 2026-08-31\n\nsome prose\n\n## Log\n"
            "- [x] type:: commit | when:: 2026-08-31T09:00 | detail:: first\n"
            "\n## Notes\n\nkeep me\n"
        )
        self.write_daily("2026-08-31", original)
        self.run_cli("track", "commit", "second", "--date", "2026-08-31")

        after = self.read_daily("2026-08-31")
        new_lines = [ln for ln in after.splitlines() if "second" in ln]
        self.assertEqual(len(new_lines), 1)
        added = new_lines[0]
        # Removing exactly the added line must reproduce the original byte-for-byte.
        self.assertEqual(after.replace(added + "\n", "", 1), original)

    def test_insert_goes_after_last_log_entry_not_at_end(self):
        original = "## Log\n- [x] type:: commit | when:: 2026-08-31T09:00\n\n## Notes\ntail\n"
        self.write_daily("2026-08-31", original)
        self.run_cli("track", "study", "--date", "2026-08-31")
        lines = self.read_daily("2026-08-31").splitlines()
        # New entry sits under the last log line; the blank line and ## Notes shift down.
        self.assertIn("type:: study", lines[2])
        self.assertEqual(lines[3], "")
        self.assertEqual(lines[4], "## Notes")

    def test_crlf_file_keeps_crlf(self):
        original = "# 2026-08-31\r\n\r\n## Log\r\n- [x] type:: commit | when:: 2026-08-31T09:00\r\n"
        self.write_daily("2026-08-31", original)
        self.run_cli("track", "commit", "--date", "2026-08-31")
        after = self.read_daily("2026-08-31")
        self.assertTrue(after.startswith(original))
        self.assertTrue(after.endswith("\r\n"))
        # Every newline in the file is still a CRLF pair.
        self.assertEqual(after.count("\n"), after.count("\r\n"))

    def test_missing_log_heading_appends_section(self):
        self.write_daily("2026-08-31", "# 2026-08-31\n\nprose only\n")
        self.run_cli("track", "commit", "--date", "2026-08-31")
        after = self.read_daily("2026-08-31")
        self.assertTrue(after.startswith("# 2026-08-31\n\nprose only\n"))
        self.assertIn("## Log\n- [x] type:: commit", after)

    def test_missing_file_is_created(self):
        self.run_cli("track", "leetcode", "two-sum", "--date", "2026-08-31")
        after = self.read_daily("2026-08-31")
        self.assertTrue(after.startswith("# 2026-08-31\n\n## Log\n"))
        self.assertIn("detail:: two-sum", after)

    def test_unknown_type_is_rejected_and_writes_nothing(self):
        with self.assertRaises(SystemExit):
            self.run_cli("track", "nonsense")
        self.assertFalse(os.path.exists(os.path.join(self.vault, "daily")))


class TestDailyTemplate(VaultTestCase):
    """A vault template seeds new notes; ticking one of its boxes is a real event."""

    TEMPLATE = (
        "# {{date}}\n\n## Log\n- [ ] type:: leetcode | diff:: easy\n\n## Notes\n\n"
    )

    def write_template(self, body=None):
        path = os.path.join(self.vault, tracker.DAILY_TEMPLATE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tracker.write_text(path, self.TEMPLATE if body is None else body)

    def test_new_note_uses_the_template_and_fills_the_date(self):
        self.write_template()
        self.run_cli("track", "commit", "hello", "--date", "2026-08-31")
        after = self.read_daily("2026-08-31")
        self.assertTrue(after.startswith("# 2026-08-31\n"))
        self.assertNotIn("{{date}}", after)
        # The event lands under ## Log, after the template's own boxes, and the
        # rest of the template survives.
        lines = after.splitlines()
        self.assertEqual(lines[3], "- [ ] type:: leetcode | diff:: easy")
        self.assertIn("detail:: hello", lines[4])
        self.assertIn("## Notes", after)

    def test_unticked_boxes_are_not_events_and_ticked_ones_are(self):
        self.write_template()
        self.run_cli("track", "commit", "--date", "2026-08-31")
        events, _ = tracker.load_events(self.vault)
        self.assertEqual([f["type"] for f in events], ["commit"])

        content = self.read_daily("2026-08-31").replace("- [ ] type:: leetcode", "- [x] type:: leetcode", 1)
        tracker.write_text(self.daily("2026-08-31"), content)
        events, _ = tracker.load_events(self.vault)
        self.assertEqual(sorted(f["type"] for f in events), ["commit", "leetcode"])

    def test_a_ticked_box_is_never_undone_by_accident(self):
        # undo only removes lines this tool wrote; a box you ticked is yours.
        self.write_template("# {{date}}\n\n## Log\n- [x] type:: leetcode | diff:: easy\n")
        self.run_cli("track", "commit", "--date", "2026-08-31")
        self.run_cli("undo", "--date", "2026-08-31", "--yes")
        self.assertEqual(
            self.read_daily("2026-08-31"),
            "# 2026-08-31\n\n## Log\n- [x] type:: leetcode | diff:: easy\n",
        )

    def test_no_template_keeps_the_built_in_skeleton(self):
        self.run_cli("track", "commit", "--date", "2026-08-31")
        self.assertTrue(self.read_daily("2026-08-31").startswith("# 2026-08-31\n\n## Log\n- [x]"))

    def test_shipped_template_is_usable_as_is(self):
        repo_template = os.path.join(os.path.dirname(__file__), tracker.DAILY_TEMPLATE)
        self.write_template(tracker.read_text(repo_template))
        self.run_cli("track", "commit", "--date", "2026-08-31")
        after = self.read_daily("2026-08-31")
        self.assertNotIn("{{date}}", after)
        # Every example box parses as the event it claims to be once ticked.
        for raw in after.splitlines():
            if not raw.startswith("- [ ] "):
                continue
            fields = tracker.parse_fields(raw[len("- [ ] "):])
            self.assertIn(fields.get("type"), tracker.VALID_TYPES, raw)


class TestRoundTrip(VaultTestCase):
    """Anything the writer emits, the reader must read back unchanged."""

    def test_format_then_parse(self):
        when = datetime(2026, 8, 31, 14, 22)
        line = tracker.format_log_line(
            "study", when, "chapter 4", "algo", 45, [("src", "manual")]
        )
        fields = tracker.parse_fields(tracker.COMPLETED_TASK_RE.match(line).group(1))
        self.assertEqual(
            fields,
            {
                "type": "study",
                "when": "2026-08-31T14:22",
                "detail": "chapter 4",
                "topic": "algo",
                "duration": "45",
                "src": "manual",
            },
        )

    def test_pipes_and_newlines_never_split_an_event(self):
        when = datetime(2026, 8, 31, 14, 22)
        line = tracker.format_log_line("commit", when, tracker.sanitize("a|b\nc"), "", None)
        self.assertEqual(len(line.splitlines()), 1)
        fields = tracker.parse_fields(tracker.COMPLETED_TASK_RE.match(line).group(1))
        self.assertEqual(fields["detail"], "a b c")

    def test_extras_land_as_inline_fields(self):
        self.run_cli(
            "track", "interview", "Jane St OA",
            "--date", "2026-08-31",
            "--x", "company=janestreet",
            "--x", "stage=oa",
        )
        line = self.read_daily("2026-08-31").splitlines()[-1]
        fields = tracker.parse_fields(tracker.COMPLETED_TASK_RE.match(line).group(1))
        self.assertEqual(fields["company"], "janestreet")
        self.assertEqual(fields["stage"], "oa")

    def test_bad_extras_are_rejected(self):
        with contextlib.redirect_stderr(StringIO()):
            for bad in ("nokey", "=v", "ty pe=x", "type=commit", "k="):
                with self.subTest(bad=bad), self.assertRaises(SystemExit):
                    tracker.parse_extras([bad])
            with self.assertRaises(SystemExit):
                tracker.parse_extras(["k=1", "k=2"])

    def test_new_types_accepted_and_study_flags_still_restricted(self):
        for name in ("leetcode", "design", "interview"):
            self.run_cli("track", name, "--date", "2026-08-31")
        self.assertEqual(len(self.read_daily("2026-08-31").splitlines()), 6)
        with self.assertRaises(SystemExit):
            self.run_cli("track", "leetcode", "--topic", "algo", "--date", "2026-08-31")


class TestTodayAndUndo(VaultTestCase):
    def test_today_lists_log_lines_only(self):
        self.write_daily(
            "2026-08-31",
            "# 2026-08-31\n## Log\n- [x] type:: commit | when:: 2026-08-31T09:00\n"
            "\n## Notes\n- [x] type:: fake | when:: 2026-08-31T10:00\n",
        )
        out, _ = self.run_cli("today", "--date", "2026-08-31")
        self.assertIn("type:: commit", out)
        self.assertNotIn("type:: fake", out)

    def test_undo_removes_only_the_last_tool_line(self):
        original = (
            "# 2026-08-31\n\n## Log\n"
            "- [x] type:: commit | when:: 2026-08-31T09:00 | detail:: keep\n"
            "- [x] hand written note\n"
            "- [x] type:: study | when:: 2026-08-31T10:00 | detail:: drop\n"
            "\n## Notes\ntail\n"
        )
        self.write_daily("2026-08-31", original)
        self.run_cli("undo", "--date", "2026-08-31", "--yes")
        after = self.read_daily("2026-08-31")
        self.assertEqual(
            after,
            original.replace(
                "- [x] type:: study | when:: 2026-08-31T10:00 | detail:: drop\n", "", 1
            ),
        )

    def test_undo_ignores_hand_written_lines(self):
        original = "## Log\n- [x] hand written | when:: whenever\n"
        self.write_daily("2026-08-31", original)
        with self.assertRaises(SystemExit):
            self.run_cli("undo", "--date", "2026-08-31", "--yes")
        self.assertEqual(self.read_daily("2026-08-31"), original)

    def test_undo_without_note_exits_cleanly(self):
        with self.assertRaises(SystemExit):
            self.run_cli("undo", "--date", "2026-08-31", "--yes")

    def test_track_then_undo_is_a_no_op(self):
        original = "# 2026-08-31\n\n## Log\n- [x] type:: commit | when:: 2026-08-31T09:00\n\n## Notes\nx\n"
        self.write_daily("2026-08-31", original)
        self.run_cli("track", "design", "sharded counter", "--date", "2026-08-31")
        self.run_cli("undo", "--date", "2026-08-31", "--yes")
        self.assertEqual(self.read_daily("2026-08-31"), original)


class TestImplicitTrack(VaultTestCase):
    def test_type_as_first_arg_implies_track(self):
        self.run_cli("commit", "fixed onnx flag", "--date", "2026-08-31")
        self.assertIn("type:: commit", self.read_daily("2026-08-31"))

    def test_subcommand_names_still_win(self):
        out, _ = self.run_cli("today", "--date", "2026-08-31")
        self.assertIn("(no note)", out)

    def test_unknown_first_word_gets_the_helpful_message(self):
        err = StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            tracker.main(["nonsense", "detail"])
        self.assertIn("unknown command or type nonsense", err.getvalue())
        self.assertIn("leetcode", err.getvalue())

    def test_complete_lists_commands_and_types(self):
        out, _ = self.run_cli("complete")
        words = out.split()
        for name in tracker.SUBCOMMANDS + tracker.VALID_TYPES:
            self.assertIn(name, words)

    def test_complete_lists_the_flags_of_one_command(self):
        out, _ = self.run_cli("complete", "sync")
        words = out.split()
        self.assertIn("--dry-run", words)
        self.assertIn("--author", words)
        self.assertNotIn("--pipeline", words)

    def test_complete_falls_back_when_the_word_is_not_a_command(self):
        for word in ("", "lee", "nonsense"):
            with self.subTest(word=word):
                out, _ = self.run_cli("complete", word)
                self.assertIn("leetcode", out.split())

    def test_week_and_month_are_stats_windows(self):
        self.write_daily(
            "2026-08-31", "## Log\n- [x] type:: commit | when:: 2026-08-31T09:00\n"
        )
        for name, days, _help in tracker.STATS_ALIASES:
            with self.subTest(name=name):
                out, _ = self.run_cli(name)
                self.assertIn("events (%s days)" % days, out)
                self.assertIn("streaks", out)

    def test_a_typo_gets_a_suggestion(self):
        for typo, wanted in (("leetcod", "leetcode"), ("stat", "stats"), ("revew", "review")):
            err = StringIO()
            with self.subTest(typo=typo):
                with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
                    tracker.main([typo])
                self.assertIn("Did you mean %s?" % wanted, err.getvalue())

    def test_nonsense_gets_the_list_but_no_invented_suggestion(self):
        err = StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            tracker.main(["zzzzzz"])
        self.assertNotIn("Did you mean", err.getvalue())
        self.assertIn("leetcode", err.getvalue())

    def test_track_suggests_on_an_explicit_bad_type(self):
        err = StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            tracker.main(["track", "Leetcod"])
        self.assertIn("Did you mean leetcode?", err.getvalue())

    def test_bare_invocation_shows_today_and_the_cheatsheet(self):
        self.write_daily(
            tracker.working_date().isoformat(),
            "## Log\n- [x] type:: commit | when:: 2026-08-31T09:00 | detail:: hello\n",
        )
        out, _ = self.run_cli()
        self.assertIn("detail:: hello", out)
        for label, _usage, _note in tracker.CHEATSHEET:
            self.assertIn(label, out)
        self.assertIn("leetcode", out)
        out.encode("ascii")

    def test_bare_invocation_without_a_vault_still_helps(self):
        os.environ.pop("VAULT_PATH")
        out, _ = self.run_cli()
        self.assertIn("VAULT_PATH is not set", out)
        self.assertIn("t dash", out)

    def test_parser_exposes_every_subcommand(self):
        parser = tracker.build_parser()
        for name in tracker.SUBCOMMANDS:
            with self.subTest(name=name):
                parser.parse_args([name] if name != "track" else [name, "commit"])


class TestNumbers(VaultTestCase):
    def seed(self, day, *lines):
        body = "".join("- [x] %s\n" % ln for ln in lines)
        self.write_daily(day, "# %s\n\n## Log\n%s" % (day, body))

    def test_week_start_is_monday(self):
        self.assertEqual(tracker.week_start(date(2026, 8, 31)), date(2026, 8, 31))
        self.assertEqual(tracker.week_start(date(2026, 9, 6)), date(2026, 8, 31))

    def test_streaks(self):
        today = date(2026, 8, 31)
        days = {today, today - timedelta(days=1), today - timedelta(days=2)}
        days |= {today - timedelta(days=d) for d in (10, 11, 12, 13)}
        self.assertEqual(tracker.streak(days, today), (3, 4))
        # Yesterday still counts: today is not over yet.
        self.assertEqual(tracker.streak(days - {today}, today), (2, 4))
        # A gap at yesterday ends the current streak.
        self.assertEqual(tracker.streak(days - {today, today - timedelta(days=1)}, today), (0, 4))
        self.assertEqual(tracker.streak(set(), today), (0, 0))

    def test_weekly_buckets_and_low_data_guard(self):
        self.seed("2026-08-31", "type:: leetcode | when:: 2026-08-31T09:00 | diff:: easy")
        self.seed("2026-08-24", "type:: leetcode | when:: 2026-08-24T09:00 | diff:: hard")
        events, _ = tracker.load_events(self.vault)
        buckets = tracker.weekly_buckets(events, 4, date(2026, 8, 31))
        self.assertEqual([b["total"] for b in buckets], [1, 1, 0, 0])
        self.assertEqual(buckets[0]["days"], 1)
        # One logged day is not enough evidence to call a trend.
        self.assertEqual(tracker.trend_label(buckets, 0), "low data")

    def test_difficulty_mix(self):
        self.seed(
            "2026-08-31",
            "type:: leetcode | when:: 2026-08-31T09:00 | diff:: easy",
            "type:: leetcode | when:: 2026-08-31T10:00 | diff:: easy",
            "type:: leetcode | when:: 2026-08-31T11:00 | diff:: hard",
        )
        events, _ = tracker.load_events(self.vault)
        buckets = tracker.weekly_buckets(events, 1, date(2026, 8, 31))
        headers, rows = tracker.difficulty_report(buckets)
        self.assertEqual(headers, ["week", "easy", "hard"])
        self.assertEqual(rows[0], ["2026-08-31", "2", "1"])

    def test_pipeline_counts_and_conversion(self):
        self.seed(
            "2026-08-31",
            "type:: application | when:: 2026-08-31T09:00 | stage:: applied",
            "type:: application | when:: 2026-08-31T09:05 | stage:: applied",
            "type:: application | when:: 2026-08-31T09:10 | stage:: applied",
            "type:: application | when:: 2026-08-31T09:15 | stage:: applied",
            "type:: interview | when:: 2026-08-31T10:00 | stage:: oa",
        )
        events, _ = tracker.load_events(self.vault)
        headers, rows = tracker.pipeline_report(events)
        self.assertEqual(headers, ["stage", "count", "from prev"])
        self.assertEqual(rows, [["applied", "4", ""], ["oa", "1", "25%"]])

    def test_csv_dump(self):
        self.seed("2026-08-31", "type:: study | when:: 2026-08-31T09:00 | topic:: algo | duration:: 30")
        out, _ = self.run_cli("stats", "--csv")
        lines = out.strip().splitlines()
        self.assertEqual(lines[0], "date,type,when,detail,topic,duration")
        self.assertEqual(lines[1], "2026-08-31,study,2026-08-31T09:00,,algo,30")

    def test_malformed_line_is_skipped_not_fatal(self):
        self.seed("2026-08-31", "no fields here", "type:: commit | when:: 2026-08-31T09:00")
        events, unparseable = tracker.load_events(self.vault, warn_start=date(2026, 8, 1))
        self.assertEqual(len(events), 1)
        self.assertEqual(unparseable, 1)

    def test_filename_date_wins_over_when_field(self):
        self.seed("2026-08-31", "type:: commit | when:: 2020-01-01T09:00")
        events, _ = tracker.load_events(self.vault)
        self.assertEqual(events[0]["_date"], date(2026, 8, 31))

    def test_warnings_stay_inside_the_reported_window(self):
        # Streaks read all of history; complaints must not.
        self.seed("2026-01-01", "type:: commit | when:: 2020-01-01T09:00", "no fields here")
        err = StringIO()
        with contextlib.redirect_stderr(err):
            events, unparseable = tracker.load_events(self.vault, warn_start=date(2026, 8, 1))
        self.assertEqual(len(events), 1)
        self.assertEqual(unparseable, 0)
        self.assertEqual(err.getvalue(), "")

    def test_dash_writes_generated_notes(self):
        self.seed("2026-08-31", "type:: commit | when:: 2026-08-31T09:00")
        out, _ = self.run_cli("dash")
        for name in tracker.GENERATED_NOTES:
            path = os.path.join(self.vault, name)
            self.assertTrue(os.path.isfile(path), name)
            self.assertTrue(tracker.read_text(path).startswith("<!-- Generated by tracker.py"))
            self.assertIn(name, out)

    def test_stats_never_writes_to_the_vault(self):
        # Reading numbers must not rewrite notes as a side effect.
        self.seed("2026-08-31", "type:: commit | when:: 2026-08-31T09:00")
        for argv in (("stats", "7"), ("stats", "30"), ("stats", "--weeks", "4"),
                     ("stats", "--pipeline"), ("stats", "--csv")):
            with self.subTest(argv=argv):
                self.run_cli(*argv)
        for name in tracker.GENERATED_NOTES:
            self.assertFalse(os.path.exists(os.path.join(self.vault, name)), name)

    def test_terminal_weekly_table_carries_the_same_bars_as_the_dashboard(self):
        self.seed("2026-08-31", "type:: commit | when:: 2026-08-31T09:00")
        out, _ = self.run_cli("stats", "--weeks", "4")
        self.assertIn("chart", out.splitlines()[0])
        self.assertIn(tracker.BAR_CHAR, out)
        out.encode("ascii")

    def test_study_minutes_are_a_table_with_bars(self):
        self.seed(
            "2026-08-31",
            "type:: study | when:: 2026-08-31T09:00 | topic:: algo | duration:: 30",
            "type:: study | when:: 2026-08-31T10:00 | topic:: os | duration:: 90",
        )
        out, _ = self.run_cli("stats", "30")
        self.assertIn("topic", out)
        self.assertIn(tracker.BAR_CHAR * tracker.BAR_WIDTH, out)
        # Largest first, and the counts are still the counts.
        self.assertLess(out.index("os"), out.index("algo"))
        self.assertIn("90", out)

    def test_event_counts_are_a_table_with_bars(self):
        self.seed(
            "2026-08-31",
            "type:: commit | when:: 2026-08-31T09:00",
            "type:: commit | when:: 2026-08-31T09:30",
            "type:: leetcode | when:: 2026-08-31T10:00",
        )
        out, _ = self.run_cli("stats", "7")
        self.assertIn("type", out)
        self.assertIn(tracker.BAR_CHAR * tracker.BAR_WIDTH, out)
        self.assertLess(out.index("commit"), out.index("leetcode"))

    def test_stats_with_no_study_still_says_none(self):
        self.seed("2026-08-31", "type:: commit | when:: 2026-08-31T09:00")
        out, _ = self.run_cli("stats", "7")
        self.assertIn("study minutes", out)
        self.assertIn("(none)", out)

    def test_dash_rejects_a_bad_window(self):
        with self.assertRaises(SystemExit):
            self.run_cli("dash", "--weeks", "0")

    def test_generated_notes_are_not_label_candidates(self):
        self.seed("2026-08-31", "type:: commit | when:: 2026-08-31T09:00")
        self.run_cli("dash")
        recent = list(tracker.iter_recent_notes(self.vault, datetime(2000, 1, 1)))
        self.assertFalse([p for p in recent if os.path.basename(p) in tracker.GENERATED_NOTES])

    def test_stats_rejects_bad_windows(self):
        for argv in (("stats", "9"), ("stats", "--weeks", "0")):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.run_cli(*argv)


class TestBars(VaultTestCase):
    """Bars are decoration over numbers that already exist; they must never lie."""

    def seed(self, day, *lines):
        body = "".join("- [x] %s\n" % ln for ln in lines)
        self.write_daily(day, "# %s\n\n## Log\n%s" % (day, body))

    def test_bar_is_proportional_and_never_hides_a_nonzero_value(self):
        self.assertEqual(tracker.bar(10, 10, 10), "#" * 10)
        self.assertEqual(tracker.bar(5, 10, 10), "#" * 5)
        # One event in a hundred-event window is still one event, not nothing.
        self.assertEqual(tracker.bar(1, 100, 10), "#")
        self.assertEqual(tracker.bar(0, 10, 10), "")
        self.assertEqual(tracker.bar(3, 0, 10), "")

    def test_bar_column_scales_to_the_column_peak(self):
        headers, rows = tracker.bar_column(
            ["week", "events"], [["a", "4"], ["b", "2"], ["c", "0"]], 1
        )
        self.assertEqual(headers, ["week", "events", "chart"])
        self.assertEqual(len(rows[0][2]), tracker.BAR_WIDTH)
        self.assertEqual(len(rows[1][2]), tracker.BAR_WIDTH // 2)
        self.assertEqual(rows[2][2], "")

    def test_bar_column_survives_a_non_numeric_cell(self):
        _headers, rows = tracker.bar_column(["week", "events"], [["a", "n/a"]], 1)
        self.assertEqual(rows[0][2], "")

    def test_study_topic_report_is_sorted_largest_first(self):
        self.seed(
            "2026-08-31",
            "type:: study | when:: 2026-08-31T09:00 | topic:: algo | duration:: 30",
            "type:: study | when:: 2026-08-31T10:00 | topic:: os | duration:: 90",
            "type:: study | when:: 2026-08-31T11:00 | topic:: algo | duration:: 30",
        )
        events, _ = tracker.load_events(self.vault)
        headers, rows = tracker.study_topic_report(events)
        self.assertEqual(headers, ["topic", "minutes", "chart"])
        self.assertEqual([r[:2] for r in rows], [["os", "90"], ["algo", "60"]])
        self.assertEqual(len(rows[0][2]), tracker.BAR_WIDTH)
        self.assertIsNone(tracker.study_topic_report([]))

    def test_dashboard_carries_bars_and_stays_ascii(self):
        self.seed(
            "2026-08-31",
            "type:: commit | when:: 2026-08-31T09:00",
            "type:: study | when:: 2026-08-31T10:00 | topic:: algo | duration:: 45",
        )
        events, _ = tracker.load_events(self.vault)
        buckets = tracker.weekly_buckets(events, 4, date(2026, 8, 31))
        body = tracker.dashboard_markdown(events, buckets, date(2026, 8, 31))
        body.encode("ascii")
        self.assertIn("| chart |", body)
        self.assertIn(tracker.BAR_CHAR * tracker.BAR_WIDTH, body)
        self.assertIn("| algo | 45 |", body)


def git_log_output(*records):
    """Fake `git log --pretty=format:GIT_LOG_FORMAT` output."""
    return "\n".join(tracker.GIT_FIELD_SEP.join(r) for r in records)


class TestSync(VaultTestCase):
    """Sync is batch import: re-running it must never duplicate or disturb anything."""

    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.vault, "..", "repo")

    def fake_git(self, log_text, email="me@example.com"):
        """Stand in for the git subprocess so tests need no real repository."""
        def run_git(_repo, argv):
            if argv[:1] == ["config"]:
                return email + "\n"
            return log_text

        self.patch(tracker, "run_git", run_git)
        self.patch(tracker, "is_git_repo", lambda _path: True)
        self.patch(tracker.shutil, "which", lambda _name: "git")

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, old)

    def sync(self, *argv):
        return self.run_cli("sync", "--repo", self.repo, *argv)

    def test_parse_git_log_skips_junk_records(self):
        text = git_log_output(
            ("a" * 40, "2026-08-31T09:00:00+00:00", "real subject"),
            ("b" * 40, "not a date", "bad date"),
        )
        text += "\n\nonly-one-field\n"
        commits = tracker.parse_git_log(text)
        self.assertEqual([c["subject"] for c in commits], ["real subject"])
        self.assertEqual(commits[0]["sha"], "a" * 40)

    def test_parse_git_log_converts_offsets_to_local_time(self):
        # 09:00 UTC is a fixed instant; whatever local zone the test runs in, the
        # naive result must equal that instant rendered locally.
        commits = tracker.parse_git_log(
            git_log_output(("a" * 40, "2026-08-31T09:00:00+00:00", "s"))
        )
        expected = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        self.assertEqual(commits[0]["when"], expected)

    def test_commits_land_on_daily_notes_with_sync_provenance(self):
        self.fake_git(git_log_output((("a" * 40), "2026-08-31T14:22:00", "fixed onnx flag")))
        self.sync("--days", "3650")
        line = self.read_daily("2026-08-31").splitlines()[-1]
        fields = tracker.parse_fields(tracker.COMPLETED_TASK_RE.match(line).group(1))
        self.assertEqual(fields["type"], "commit")
        self.assertEqual(fields["detail"], "fixed onnx flag")
        self.assertEqual(fields["id"], "a" * 8)
        self.assertEqual(fields["src"], "sync")
        self.assertEqual(fields["repo"], "repo")

    def test_04h_rollover_applies_to_commits(self):
        self.fake_git(git_log_output((("a" * 40), "2026-09-01T01:30:00", "late night")))
        self.sync("--days", "3650")
        # A 01:30 commit belongs to the previous working day, same as a hand-logged one.
        self.assertTrue(os.path.isfile(self.daily("2026-08-31")))
        self.assertFalse(os.path.isfile(self.daily("2026-09-01")))

    def test_second_sync_adds_nothing(self):
        self.fake_git(
            git_log_output(
                (("a" * 40), "2026-08-31T14:22:00", "one"),
                (("b" * 40), "2026-08-31T15:00:00", "two"),
            )
        )
        self.sync("--days", "3650")
        first = self.read_daily("2026-08-31")
        out, _ = self.sync("--days", "3650")
        self.assertEqual(self.read_daily("2026-08-31"), first)
        self.assertIn("added 0 event(s)", out)
        self.assertIn("2 already logged", out)

    def test_sync_is_append_only_around_existing_content(self):
        original = (
            "# 2026-08-31\n\nprose\n\n## Log\n"
            "- [x] type:: study | when:: 2026-08-31T09:00 | duration:: 30\n"
            "\n## Notes\n\nkeep me\n"
        )
        self.write_daily("2026-08-31", original)
        self.fake_git(git_log_output((("a" * 40), "2026-08-31T14:22:00", "one")))
        self.sync("--days", "3650")

        after = self.read_daily("2026-08-31")
        added = [ln for ln in after.splitlines() if "id:: aaaaaaaa" in ln]
        self.assertEqual(len(added), 1)
        self.assertEqual(after.replace(added[0] + "\n", "", 1), original)

    def test_commits_are_ordered_oldest_first_within_a_day(self):
        # git log is newest-first; the note must still read chronologically.
        self.fake_git(
            git_log_output(
                (("b" * 40), "2026-08-31T15:00:00", "later"),
                (("a" * 40), "2026-08-31T09:00:00", "earlier"),
            )
        )
        self.sync("--days", "3650")
        lines = [ln for ln in self.read_daily("2026-08-31").splitlines() if "src:: sync" in ln]
        self.assertIn("earlier", lines[0])
        self.assertIn("later", lines[1])

    def test_dry_run_writes_nothing(self):
        self.fake_git(git_log_output((("a" * 40), "2026-08-31T14:22:00", "one")))
        out, _ = self.sync("--days", "3650", "--dry-run")
        self.assertIn("would add 1 event(s)", out)
        self.assertFalse(os.path.exists(self.daily("2026-08-31")))

    def test_sync_refreshes_the_generated_notes(self):
        self.fake_git(git_log_output((("a" * 40), "2026-08-31T14:22:00", "one")))
        out, _ = self.sync("--days", "3650")
        for name in tracker.GENERATED_NOTES:
            self.assertTrue(os.path.isfile(os.path.join(self.vault, name)), name)
            self.assertIn(name, out)
        self.assertIn("added 1 event(s)", out)
        self.assertIn("| commit |", tracker.read_text(os.path.join(self.vault, "Dashboard.md")))

    def test_sync_leaves_the_notes_alone_when_nothing_landed(self):
        # Nothing new means nothing to redraw -- and a dry run never writes at all.
        self.fake_git(git_log_output((("a" * 40), "2026-08-31T14:22:00", "one")))
        self.sync("--days", "3650", "--dry-run")
        self.assertFalse(os.path.exists(os.path.join(self.vault, "Dashboard.md")))
        self.sync("--days", "3650", "--no-dash")
        self.assertFalse(os.path.exists(os.path.join(self.vault, "Dashboard.md")))
        self.sync("--days", "3650")  # second real sync: everything already logged
        self.assertFalse(os.path.exists(os.path.join(self.vault, "Dashboard.md")))

    def test_unreadable_repo_warns_and_is_not_fatal(self):
        self.patch(tracker.shutil, "which", lambda _name: "git")
        self.patch(tracker, "is_git_repo", lambda path: path.endswith("good"))
        self.patch(
            tracker,
            "run_git",
            lambda _repo, argv: "me@example.com\n" if argv[:1] == ["config"]
            else git_log_output((("a" * 40), "2026-08-31T14:22:00", "one")),
        )
        good = os.path.join(self.vault, "good")
        bad = os.path.join(self.vault, "bad")
        out, err = self.run_cli("sync", "--repo", bad, "--repo", good, "--days", "3650")
        self.assertIn("not a git repository", err)
        self.assertIn("added 1 event(s) from 1 repo(s)", out)

    def test_sync_with_no_readable_repo_exits_without_writing(self):
        self.patch(tracker.shutil, "which", lambda _name: "git")
        self.patch(tracker, "is_git_repo", lambda _path: False)
        with contextlib.redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            self.run_cli("sync", "--repo", self.repo)
        self.assertFalse(os.path.exists(os.path.join(self.vault, "daily")))

    def test_resolve_repos_falls_back_to_tracker_repos(self):
        os.environ["TRACKER_REPOS"] = os.pathsep.join(["a", "b", ""])
        self.addCleanup(os.environ.pop, "TRACKER_REPOS", None)
        self.assertEqual(
            tracker.resolve_repos(None, None),
            [os.path.abspath("a"), os.path.abspath("b")],
        )
        # Explicit flags win over the environment, and duplicates collapse.
        self.assertEqual(tracker.resolve_repos(["x", "x"], None), [os.path.abspath("x")])

    def test_root_discovery_finds_git_subdirectories(self):
        root = os.path.join(self.vault, "projects")
        for name in ("one", "two", "not-a-repo"):
            os.makedirs(os.path.join(root, name), exist_ok=True)
        for name in ("one", "two"):
            os.makedirs(os.path.join(root, name, ".git"), exist_ok=True)
        found = [os.path.basename(p) for p in tracker.resolve_repos(None, [root])]
        self.assertEqual(found, ["one", "two"])

    def test_existing_ids_reads_only_the_log_section(self):
        content = (
            "## Log\n- [x] type:: commit | when:: 2026-08-31T09:00 | id:: abc | src:: sync\n"
            "\n## Notes\n- [x] type:: commit | when:: 2026-08-31T10:00 | id:: elsewhere\n"
        )
        self.assertEqual(tracker.existing_ids(content), {"abc"})

    def test_id_and_src_are_reserved_from_manual_extras(self):
        with contextlib.redirect_stderr(StringIO()):
            for bad in ("id=abc", "src=sync"):
                with self.subTest(bad=bad), self.assertRaises(SystemExit):
                    tracker.parse_extras([bad])

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_real_repository_end_to_end(self):
        repo = tempfile.mkdtemp(prefix="tracker-repo-")
        self.addCleanup(shutil.rmtree, repo, True)
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        def git(*argv):
            subprocess.run(
                ["git", "-C", repo] + list(argv), check=True, capture_output=True, env=env
            )

        git("init", "-q")
        git("config", "user.email", "me@example.com")
        git("config", "user.name", "Me")
        tracker.write_text(os.path.join(repo, "f.txt"), "hi\n")
        git("add", "f.txt")
        git("commit", "-q", "-m", "first real commit")

        out, _ = self.run_cli("sync", "--repo", repo, "--days", "3650")
        self.assertIn("added 1 event(s)", out)
        day = tracker.working_date().isoformat()
        self.assertIn("first real commit", self.read_daily(day))
        # And it is idempotent against a real repo too.
        out, _ = self.run_cli("sync", "--repo", repo, "--days", "3650")
        self.assertIn("added 0 event(s)", out)


class TestReview(VaultTestCase):
    """A review is written once. Regenerating it would erase what you wrote in it."""

    WEEK = "2026-08-24"  # a Monday; the week before 2026-08-31

    def seed(self, day, *lines):
        body = "".join("- [x] %s\n" % ln for ln in lines)
        self.write_daily(day, "# %s\n\n## Log\n%s" % (day, body))

    def review_file(self):
        return os.path.join(self.vault, "reviews", "2026-W35.md")

    def test_default_week_is_the_one_that_just_ended(self):
        self.assertEqual(
            tracker.review_week_start(date(2026, 9, 2)), date(2026, 8, 24)
        )
        # --week takes any date inside the target week.
        self.assertEqual(
            tracker.review_week_start(date(2026, 9, 2), date(2026, 8, 27)),
            date(2026, 8, 24),
        )

    def test_review_contains_the_weeks_numbers_and_the_prompts(self):
        for day in ("2026-08-24", "2026-08-25", "2026-08-26"):
            self.seed(day, "type:: leetcode | when:: %sT09:00 | diff:: medium" % day)
        self.run_cli("review", "--week", self.WEEK)

        body = tracker.read_text(self.review_file())
        self.assertIn("# Review 2026-W35", body)
        self.assertIn("2026-08-24 to 2026-08-30", body)
        self.assertIn("Logged 3 of 7 days.", body)
        self.assertIn("| 2026-08-24 | 3 | 3 | 3 |", body)  # week, days, events, leetcode
        self.assertIn("## Leetcode difficulty mix", body)
        for prompt in tracker.REVIEW_PROMPTS:
            self.assertIn("## %s" % prompt, body)

    def test_low_data_week_reads_as_insufficient_not_decline(self):
        self.seed("2026-08-24", "type:: commit | when:: 2026-08-24T09:00")
        self.run_cli("review", "--week", self.WEEK)
        self.assertIn("insufficient data, not decline", tracker.read_text(self.review_file()))

    def test_existing_review_is_never_overwritten(self):
        self.seed("2026-08-24", "type:: commit | when:: 2026-08-24T09:00")
        self.run_cli("review", "--week", self.WEEK)
        mine = tracker.read_text(self.review_file()) + "\n- my own handwriting\n"
        tracker.write_text(self.review_file(), mine)

        out, _ = self.run_cli("review", "--week", self.WEEK)
        self.assertIn("already exists", out)
        self.assertEqual(tracker.read_text(self.review_file()), mine)

    def test_print_writes_no_file(self):
        self.seed("2026-08-24", "type:: commit | when:: 2026-08-24T09:00")
        out, _ = self.run_cli("review", "--week", self.WEEK, "--print")
        self.assertIn("# Review 2026-W35", out)
        self.assertFalse(os.path.exists(self.review_file()))

    def test_generated_text_is_ascii_so_print_survives_any_console(self):
        # --print on a cp1252 console dies on any non-ASCII character the tool adds.
        self.seed("2026-08-24", "type:: commit | when:: 2026-08-24T09:00")
        out, _ = self.run_cli("review", "--week", self.WEEK, "--print")
        out.encode("ascii")

    def test_review_ignores_events_after_the_week(self):
        self.seed("2026-08-24", "type:: commit | when:: 2026-08-24T09:00")
        self.seed("2026-09-05", "type:: commit | when:: 2026-09-05T09:00")
        self.run_cli("review", "--week", self.WEEK)
        self.assertNotIn("2026-09-05", tracker.read_text(self.review_file()))


class TestQuickAdd(VaultTestCase):
    """The window owns no format: every write goes through tracker's own commands."""

    def setUp(self):
        super().setUp()
        self.quickadd = __import__("quickadd")

    def test_logging_goes_through_the_normal_write_path(self):
        ok, _msg = self.quickadd.log_event("leetcode", "two-sum", "", "", "diff=easy")
        self.assertTrue(ok)
        day = tracker.working_date().isoformat()
        line = self.read_daily(day).splitlines()[-1]
        self.assertTrue(tracker.TOOL_LINE_RE.match(line), line)
        fields = tracker.parse_fields(tracker.COMPLETED_TASK_RE.match(line).group(1))
        self.assertEqual(fields["type"], "leetcode")
        self.assertEqual(fields["detail"], "two-sum")
        self.assertEqual(fields["diff"], "easy")

    def test_study_topic_and_duration_reach_the_line(self):
        ok, _msg = self.quickadd.log_event("study", "chapter 4", "algo", "45", "")
        self.assertTrue(ok)
        day = tracker.working_date().isoformat()
        fields = tracker.parse_fields(
            tracker.COMPLETED_TASK_RE.match(self.read_daily(day).splitlines()[-1]).group(1)
        )
        self.assertEqual((fields["topic"], fields["duration"]), ("algo", "45"))

    def test_a_bad_field_reports_instead_of_exiting(self):
        # die() must never take the window down with it.
        for args in (
            ("study", "", "", "half an hour", ""),   # duration is not a number
            ("leetcode", "", "", "", "nokey"),       # extras must be key=value
            ("leetcode", "", "", "", "type=commit"),  # reserved field
        ):
            with self.subTest(args=args):
                ok, message = self.quickadd.log_event(*args)
                self.assertFalse(ok)
                self.assertTrue(message)
        self.assertFalse(os.path.exists(os.path.join(self.vault, "daily")))

    def test_undo_reports_when_there_is_nothing_to_undo(self):
        ok, message = self.quickadd.undo_last()
        self.assertFalse(ok)
        self.assertTrue(message)

    def test_log_then_undo_leaves_no_trace(self):
        self.quickadd.log_event("commit", "hello", "", "", "")
        day = tracker.working_date().isoformat()
        before = self.read_daily(day)
        self.quickadd.log_event("commit", "oops", "", "", "")
        ok, _msg = self.quickadd.undo_last()
        self.assertTrue(ok)
        self.assertEqual(self.read_daily(day), before)

    def test_split_extras(self):
        self.assertEqual(
            self.quickadd.split_extras("  diff=easy   result=solved "),
            ["diff=easy", "result=solved"],
        )
        self.assertEqual(self.quickadd.split_extras(""), [])

    def test_today_lines_render_events_and_tolerate_a_missing_note(self):
        self.assertEqual(self.quickadd.today_lines(self.vault, date(2026, 8, 31)), [])
        self.write_daily(
            "2026-08-31",
            "## Log\n"
            "- [x] type:: leetcode | when:: 2026-08-31T09:05 | detail:: two-sum | diff:: easy\n"
            "- [ ] type:: study | topic:: algo\n",
        )
        lines = self.quickadd.today_lines(self.vault, date(2026, 8, 31))
        self.assertEqual(len(lines), 1)  # the unticked box is not an event
        self.assertIn("09:05", lines[0])
        self.assertIn("leetcode", lines[0])
        self.assertIn("two-sum", lines[0])
        self.assertIn("diff=easy", lines[0])

    def test_numbers_pane_reports_the_same_engine_as_the_cli(self):
        for day in ("2026-08-31", "2026-08-30"):
            self.write_daily(
                day,
                "## Log\n- [x] type:: leetcode | when:: %sT09:00 | diff:: easy\n"
                "- [x] type:: study | when:: %sT10:00 | topic:: algo | duration:: 30\n"
                % (day, day),
            )
        lines = self.quickadd.numbers_lines(self.vault, weeks=4, today=date(2026, 8, 31))
        text = "\n".join(lines)
        self.assertIn("week", lines[0])
        self.assertIn("chart", lines[0])
        self.assertIn("2026-08-31", text)   # this week's bucket
        self.assertIn("streaks", text)
        self.assertIn("study minutes by topic", text)
        self.assertIn("algo", text)
        self.assertIn(tracker.BAR_CHAR, text)
        text.encode("ascii")

    def test_numbers_pane_shows_the_application_pipeline(self):
        self.write_daily(
            "2026-08-31",
            "## Log\n"
            "- [x] type:: application | when:: 2026-08-31T09:00 | stage:: applied\n"
            "- [x] type:: application | when:: 2026-08-31T09:05 | stage:: applied\n"
            "- [x] type:: interview | when:: 2026-08-31T10:00 | stage:: oa\n",
        )
        text = "\n".join(
            self.quickadd.numbers_lines(self.vault, weeks=2, today=date(2026, 8, 31))
        )
        self.assertIn("application pipeline", text)
        self.assertIn("applied", text)
        self.assertIn("50%", text)  # conversion from applied to oa

    def test_suggest_tab_scans_and_applies_through_the_normal_writer(self):
        history = os.path.join(self.vault, "History")
        conn = sqlite3.connect(history)
        when = datetime.now() - timedelta(hours=1)
        offset = datetime.now() - datetime.utcnow()
        stamp = int(((when - offset) - __import__("suggest").CHROMIUM_EPOCH).total_seconds() * 1e6)
        with conn:
            conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
            conn.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)")
            conn.execute("INSERT INTO urls VALUES (1,'https://leetcode.com/problems/two-sum/','Two Sum')")
            conn.execute("INSERT INTO visits VALUES (1,1,?)", (stamp,))
        conn.close()
        os.environ["TRACKER_BROWSERS"] = history
        self.addCleanup(os.environ.pop, "TRACKER_BROWSERS", None)

        found = self.quickadd.scan_suggestions(self.vault, 3)
        self.assertEqual([p["detail"] for p in found], ["two-sum"])

        ok, message = self.quickadd.apply_suggestions(self.vault, found, "medium")
        self.assertTrue(ok, message)
        events, _ = tracker.load_events(self.vault)
        self.assertEqual(events[0]["diff"], "medium")
        self.assertEqual(events[0]["src"], "suggest")

        # And the same scan proposes nothing the second time.
        self.assertEqual(self.quickadd.scan_suggestions(self.vault, 3), [])

    def test_applying_nothing_is_reported_not_written(self):
        ok, message = self.quickadd.apply_suggestions(self.vault, [], "")
        self.assertFalse(ok)
        self.assertIn("nothing selected", message)
        self.assertFalse(os.path.exists(os.path.join(self.vault, "daily")))

    def test_numbers_pane_on_an_empty_vault_does_not_blow_up(self):
        lines = self.quickadd.numbers_lines(self.vault, weeks=4, today=date(2026, 8, 31))
        self.assertTrue(lines)
        self.assertIn("streaks", "\n".join(lines))

    def test_numbers_pane_swallows_warnings_it_cannot_print(self):
        # Under pythonw there is no stderr; a corrupt line must not reach one.
        self.write_daily("2026-08-31", "## Log\n- [x] no fields here\n")
        err = StringIO()
        with contextlib.redirect_stderr(err):
            self.quickadd.numbers_lines(self.vault, weeks=2, today=date(2026, 8, 31))
        self.assertEqual(err.getvalue(), "")

    def test_format_event_survives_a_line_with_no_when(self):
        # A box ticked in Obsidian carries no time; the window must still show it.
        line = self.quickadd.format_event({"type": "leetcode", "_date": date(2026, 8, 31)})
        self.assertTrue(line.startswith("--:--"))
        self.assertIn("leetcode", line)


class TestSetup(VaultTestCase):
    """Setup creates what is missing and never touches what exists."""

    def setUp(self):
        super().setUp()
        self.bootstrap = __import__("bootstrap")
        self.target = os.path.join(self.vault, "new-vault")

    def args(self, path=None, profile=False):
        return Namespace(path=path or self.target, profile=profile)

    def run_setup(self, **kwargs):
        out = StringIO()
        with contextlib.redirect_stdout(out):
            self.bootstrap.cmd_setup(self.args(**kwargs))
        return out.getvalue()

    def test_creates_the_whole_layout(self):
        self.run_setup()
        for name in self.bootstrap.VAULT_DIRS:
            self.assertTrue(os.path.isdir(os.path.join(self.target, name)), name)
        self.assertTrue(os.path.isfile(os.path.join(self.target, "topics.txt")))
        self.assertTrue(os.path.isfile(os.path.join(self.target, tracker.DAILY_TEMPLATE)))

    def test_the_seeded_vault_is_immediately_usable(self):
        self.run_setup()
        os.environ["VAULT_PATH"] = self.target
        self.run_cli("track", "leetcode", "two-sum", "--date", "2026-08-31")
        note = tracker.read_text(os.path.join(self.target, "daily", "2026-08-31.md"))
        self.assertIn("detail:: two-sum", note)
        # The seeded template was used, so the note has its quick-log boxes.
        self.assertIn("- [ ] type::", note)
        # And topics.txt parses as the label command expects.
        self.assertIn("algorithms", tracker.load_topics(self.target))

    def test_it_never_overwrites_your_files(self):
        os.makedirs(os.path.join(self.target, "templates"))
        tracker.write_text(os.path.join(self.target, "topics.txt"), "just-mine\n")
        tracker.write_text(os.path.join(self.target, tracker.DAILY_TEMPLATE), "# mine\n")
        self.run_setup()
        self.assertEqual(tracker.read_text(os.path.join(self.target, "topics.txt")), "just-mine\n")
        self.assertEqual(
            tracker.read_text(os.path.join(self.target, tracker.DAILY_TEMPLATE)), "# mine\n"
        )

    def test_running_it_twice_changes_nothing(self):
        self.run_setup()
        before = sorted(os.walk(self.target))
        out = self.run_setup()
        self.assertIn("already there", out)
        self.assertEqual(sorted(os.walk(self.target)), before)

    def test_the_printed_block_carries_real_paths(self):
        out = self.run_setup()
        self.assertIn('$env:VAULT_PATH = "%s"' % self.target, out)
        self.assertIn("t.ps1", out)
        self.assertIn("completion.ps1", out)

    def test_the_repo_guess_is_a_list_of_repositories_not_their_parent(self):
        # sync treats each entry as a repo and warns about anything that is not one,
        # so guessing the containing folder would ship a broken default.
        guess = self.bootstrap.guess_repos()
        self.assertTrue(guess)
        for path in guess.split(os.pathsep):
            self.assertTrue(tracker.is_git_repo(path), path)

    def test_no_path_and_no_vault_path_is_a_clear_error(self):
        os.environ.pop("VAULT_PATH")
        err = StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            self.bootstrap.cmd_setup(Namespace(path=None, profile=False))
        self.assertIn("give setup a path", err.getvalue())

    def test_vault_path_is_the_default_target(self):
        os.environ["VAULT_PATH"] = self.target
        with contextlib.redirect_stdout(StringIO()):
            self.bootstrap.cmd_setup(Namespace(path=None, profile=False))
        self.assertTrue(os.path.isdir(os.path.join(self.target, "daily")))

    def test_profile_append_is_idempotent(self):
        profile = os.path.join(self.vault, "profile.ps1")
        self.bootstrap.profile_path = lambda: profile
        block = self.bootstrap.profile_block(self.target, "D:\\repos")
        tracker.write_text(profile, "# my own settings\n")

        self.assertIn("appended", self.bootstrap.append_to_profile(block))
        after = tracker.read_text(profile)
        self.assertIn("# my own settings", after)   # yours survives
        self.assertIn("$env:VAULT_PATH", after)

        self.assertIn("already has", self.bootstrap.append_to_profile(block))
        self.assertEqual(tracker.read_text(profile), after)


class TestSuggest(VaultTestCase):
    """Proposals come from local evidence and nothing is written without a pick."""

    def setUp(self):
        super().setUp()
        self.suggest = __import__("suggest")
        self.dbs = []

    def chromium_db(self, *rows):
        """A stand-in Chrome History file: (url, title, datetime)."""
        path = os.path.join(self.vault, "History%d" % len(self.dbs))
        conn = sqlite3.connect(path)
        with conn:
            conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
            conn.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)")
            for i, (url, title, when) in enumerate(rows, start=1):
                stamp = int((self.as_utc(when) - self.suggest.CHROMIUM_EPOCH).total_seconds() * 1e6)
                conn.execute("INSERT INTO urls VALUES (?,?,?)", (i, url, title))
                conn.execute("INSERT INTO visits VALUES (?,?,?)", (i, i, stamp))
        conn.close()
        self.dbs.append(("chromium", path))
        return path

    def firefox_db(self, *rows):
        path = os.path.join(self.vault, "places%d.sqlite" % len(self.dbs))
        conn = sqlite3.connect(path)
        with conn:
            conn.execute("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
            conn.execute("CREATE TABLE moz_historyvisits (id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER)")
            for i, (url, title, when) in enumerate(rows, start=1):
                stamp = int((self.as_utc(when) - self.suggest.UNIX_EPOCH).total_seconds() * 1e6)
                conn.execute("INSERT INTO moz_places VALUES (?,?,?)", (i, url, title))
                conn.execute("INSERT INTO moz_historyvisits VALUES (?,?,?)", (i, i, stamp))
        conn.close()
        self.dbs.append(("firefox", path))
        return path

    def as_utc(self, when):
        """Browsers store UTC; the tests speak local time, same as the tool."""
        return when - (datetime.now() - datetime.utcnow())

    def gather(self, days=3):
        since = datetime.now() - timedelta(days=days)
        return self.suggest.gather(since, self.dbs)

    # -- URL classification --

    def test_leetcode_problem_urls_become_leetcode_events(self):
        for url in (
            "https://leetcode.com/problems/two-sum/",
            "https://leetcode.com/problems/two-sum/description/",
            "https://www.leetcode.com/problems/Two-Sum",
        ):
            with self.subTest(url=url):
                got = self.suggest.classify(url, "Two Sum - LeetCode")
                self.assertEqual(got["type"], "leetcode")
                self.assertEqual(got["detail"], "two-sum")
                self.assertEqual(got["ident"], "lc-two-sum")

    def test_job_boards_yield_company_and_stage(self):
        cases = (
            ("https://boards.greenhouse.io/nvidia/jobs/4172", "nvidia", "gh-4172"),
            ("https://job-boards.greenhouse.io/stripe/jobs/999", "stripe", "gh-999"),
            ("https://jobs.lever.co/figma/8ac3f1e2-0000-4aaa-bbbb-ccccdddd", "figma", None),
            ("https://jobs.ashbyhq.com/janestreet/1a2b3c4d-5e6f", "janestreet", None),
            ("https://nvidia.wd5.myworkdayjobs.com/en-US/careers/job/Remote/SWE-Intern_JR123", "nvidia", None),
        )
        for url, company, ident in cases:
            with self.subTest(url=url):
                got = self.suggest.classify(url, "SWE Intern | Careers")
                self.assertEqual(got["type"], "application")
                self.assertIn(("company", company), got["extras"])
                self.assertIn(("stage", "applied"), got["extras"])
                if ident:
                    self.assertEqual(got["ident"], ident)

    def test_everything_else_is_ignored(self):
        # The allowlist is the privacy story: history it cannot log, it cannot see.
        for url in (
            "https://mail.google.com/mail/u/0/#inbox",
            "https://www.rbcroyalbank.com/accounts",
            "https://leetcode.com/contest/weekly-380/",
            "https://github.com/KassaSana03/personaltracker",
        ):
            with self.subTest(url=url):
                self.assertIsNone(self.suggest.classify(url, "whatever"))

    def test_a_login_or_error_page_still_logs_the_posting_it_points_at(self):
        # Real history is full of these: the tab said "Sign In" while the URL was a job.
        for title in ("Sign In", "Create Account", "Workday is currently unavailable.",
                      "Careers", "", "Jobs - DAT Careers"):
            with self.subTest(title=title):
                got = self.suggest.classify(
                    "https://nvidia.wd5.myworkdayjobs.com/en-US/careers/job/Remote/SWE_JR123",
                    title,
                )
                self.assertEqual(got["type"], "application")
                # Workday puts the title in the URL, so the row is still labelled.
                self.assertEqual(got["detail"], "SWE JR123")

    def test_a_job_url_with_no_readable_slug_falls_back_to_the_company(self):
        got = self.suggest.classify(
            "https://jobs.ashbyhq.com/janestreet/1a2b3c4d-5e6f-0000-1111-222233334444", ""
        )
        self.assertEqual(got["detail"], "janestreet posting")

    def test_one_posting_reached_two_ways_is_one_proposal(self):
        when = datetime.now() - timedelta(hours=1)
        self.chromium_db(
            ("https://jobs.smartrecruiters.com/LuxeMedia/743999", "Web Developer Intern", when),
            ("https://jobs.smartrecruiters.com/LuxeMedia/744000", "Web Developer Intern",
             when + timedelta(minutes=1)),
        )
        got = self.gather()
        self.assertEqual(len(got), 1)
        self.assertLess(abs((got[0]["when"] - when).total_seconds()), 1)

    def test_two_different_jobs_at_one_company_stay_separate(self):
        when = datetime.now() - timedelta(hours=1)
        self.chromium_db(
            ("https://boards.greenhouse.io/nvidia/jobs/1", "SWE Intern", when),
            ("https://boards.greenhouse.io/nvidia/jobs/2", "ML Intern", when),
        )
        self.assertEqual(len(self.gather()), 2)

    def test_a_real_job_title_is_kept(self):
        got = self.suggest.classify(
            "https://nvidia.wd5.myworkdayjobs.com/en-US/careers/job/Remote/SWE_JR123",
            "Software Engineer Intern, Compute Architecture",
        )
        self.assertEqual(got["detail"], "Software Engineer Intern, Compute Architecture")

    def test_proposals_group_by_working_day_then_clock(self):
        # A 00:30 visit belongs to the night before; the table must still read in order.
        base = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)
        if base > datetime.now():
            base -= timedelta(days=1)
        self.chromium_db(
            ("https://leetcode.com/problems/late-one/", "late", base + timedelta(hours=6, minutes=30)),
            ("https://leetcode.com/problems/early-one/", "early", base),
        )
        got = self.gather()
        self.assertEqual([p["detail"] for p in got], ["early-one", "late-one"])
        self.assertEqual(got[0]["day"], got[1]["day"])

    def test_detail_uses_the_job_title_not_the_whole_page_title(self):
        got = self.suggest.classify(
            "https://boards.greenhouse.io/nvidia/jobs/4172",
            "Software Engineer Intern - Summer 2027 | NVIDIA",
        )
        self.assertEqual(got["detail"], "Software Engineer Intern - Summer 2027")

    # -- reading history --

    def test_visits_are_read_from_chromium_and_firefox(self):
        earlier = datetime.now() - timedelta(hours=3)
        later = datetime.now() - timedelta(hours=1)
        self.chromium_db(("https://leetcode.com/problems/two-sum/", "Two Sum", earlier))
        self.firefox_db(("https://jobs.lever.co/figma/8ac3f1e2-0000-4aaa", "SWE Intern", later))
        got = self.gather()
        # Both browsers are read, and the two epochs land on the same timeline.
        self.assertEqual([p["type"] for p in got], ["leetcode", "application"])
        self.assertLess(abs((got[0]["when"] - earlier).total_seconds()), 1)
        self.assertLess(abs((got[1]["when"] - later).total_seconds()), 1)

    def test_visits_older_than_the_window_are_ignored(self):
        self.chromium_db(
            ("https://leetcode.com/problems/old-one/", "old", datetime.now() - timedelta(days=9)),
            ("https://leetcode.com/problems/new-one/", "new", datetime.now() - timedelta(hours=1)),
        )
        self.assertEqual([p["detail"] for p in self.gather(days=3)], ["new-one"])

    def test_the_same_problem_opened_all_evening_is_one_proposal(self):
        base = datetime.now().replace(hour=20, minute=0, second=0, microsecond=0)
        if base > datetime.now():
            base -= timedelta(days=1)
        self.chromium_db(
            ("https://leetcode.com/problems/two-sum/", "Two Sum", base),
            ("https://leetcode.com/problems/two-sum/", "Two Sum", base + timedelta(minutes=20)),
            ("https://leetcode.com/problems/two-sum/description/", "Two Sum", base + timedelta(minutes=40)),
        )
        got = self.gather()
        self.assertEqual(len(got), 1)
        # The first visit of the day is the one that gets logged.
        self.assertLess(abs((got[0]["when"] - base).total_seconds()), 1)

    def test_an_unreadable_database_is_skipped_not_fatal(self):
        bad = os.path.join(self.vault, "not-a-db")
        tracker.write_text(bad, "this is not sqlite")
        self.assertEqual(self.suggest.read_visits("chromium", bad, datetime.now()), [])
        missing = os.path.join(self.vault, "gone", "History")
        self.assertEqual(self.suggest.read_visits("chromium", missing, datetime.now()), [])

    def test_a_locked_database_is_copied_before_reading(self):
        # Chrome holds the file open; the reader must never touch the original.
        path = self.chromium_db(
            ("https://leetcode.com/problems/two-sum/", "Two Sum", datetime.now())
        )
        before = os.path.getmtime(path)
        holder = sqlite3.connect(path)
        holder.execute("BEGIN EXCLUSIVE")
        try:
            self.assertEqual(len(self.gather()), 1)
        finally:
            holder.close()
        self.assertEqual(os.path.getmtime(path), before)

    # -- writing --

    def args(self, **kwargs):
        defaults = {"days": 3, "yes": True, "dry_run": False}
        defaults.update(kwargs)
        return Namespace(**defaults)

    def run_suggest(self, **kwargs):
        os.environ["TRACKER_BROWSERS"] = os.pathsep.join(p for _kind, p in self.dbs)
        self.addCleanup(os.environ.pop, "TRACKER_BROWSERS", None)
        out, err = StringIO(), StringIO()
        old = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            self.suggest.cmd_suggest(self.args(**kwargs))
        finally:
            sys.stdout, sys.stderr = old
        return out.getvalue(), err.getvalue()

    def test_applied_proposals_land_as_normal_events_with_provenance(self):
        when = datetime.now() - timedelta(hours=1)
        self.chromium_db(
            ("https://leetcode.com/problems/two-sum/", "Two Sum", when),
            ("https://boards.greenhouse.io/nvidia/jobs/4172", "SWE Intern | NVIDIA", when),
        )
        out, _ = self.run_suggest()
        self.assertIn("added 2 event(s)", out)

        day = tracker.working_date(when).isoformat()
        events, _ = tracker.load_events(self.vault)
        by_type = {f["type"]: f for f in events}
        self.assertEqual(by_type["leetcode"]["detail"], "two-sum")
        self.assertEqual(by_type["leetcode"]["id"], "lc-two-sum")
        self.assertEqual(by_type["leetcode"]["src"], "suggest")
        self.assertEqual(by_type["application"]["company"], "nvidia")
        self.assertEqual(by_type["application"]["stage"], "applied")
        self.assertIn(day, os.listdir(os.path.join(self.vault, "daily"))[0])

    def test_running_it_twice_adds_nothing(self):
        self.chromium_db(
            ("https://leetcode.com/problems/two-sum/", "Two Sum", datetime.now() - timedelta(hours=1))
        )
        self.run_suggest()
        before = tracker.read_text(self.daily(tracker.working_date().isoformat()))
        out, _ = self.run_suggest()
        self.assertIn("nothing new to propose", out)
        self.assertEqual(tracker.read_text(self.daily(tracker.working_date().isoformat())), before)

    def test_a_hand_logged_event_is_not_proposed_again(self):
        # Same dedupe key as sync, and the state is the Markdown itself.
        self.chromium_db(
            ("https://leetcode.com/problems/two-sum/", "Two Sum", datetime.now() - timedelta(hours=1))
        )
        proposals = self.gather()
        self.assertEqual(len(self.suggest.already_logged(self.vault, proposals)), 1)
        self.write_daily(
            tracker.working_date().isoformat(),
            "## Log\n- [x] type:: leetcode | when:: 2026-08-31T09:00 | id:: lc-two-sum\n",
        )
        self.assertEqual(self.suggest.already_logged(self.vault, proposals), [])

    def test_dry_run_writes_nothing(self):
        self.chromium_db(
            ("https://leetcode.com/problems/two-sum/", "Two Sum", datetime.now() - timedelta(hours=1))
        )
        out, _ = self.run_suggest(dry_run=True)
        self.assertIn("two-sum", out)
        self.assertFalse(os.path.exists(os.path.join(self.vault, "daily")))

    def test_no_browser_history_is_a_clear_error(self):
        os.environ["TRACKER_BROWSERS"] = os.path.join(self.vault, "nope", "History")
        self.addCleanup(os.environ.pop, "TRACKER_BROWSERS", None)
        err = StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            self.suggest.cmd_suggest(self.args())
        self.assertIn("no browser history found", err.getvalue())

    def test_selection_parsing(self):
        parse = self.suggest.parse_selection
        self.assertEqual(parse("a", 3), [0, 1, 2])
        self.assertEqual(parse("", 3), [])
        self.assertEqual(parse("n", 3), [])
        self.assertEqual(parse("1,3", 3), [0, 2])
        self.assertEqual(parse("1-3", 3), [0, 1, 2])
        self.assertEqual(parse("3 1", 3), [0, 2])
        self.assertEqual(parse("2,9", 3), [1])       # out of range is dropped
        self.assertEqual(parse("nonsense", 3), [])   # never guesses


if __name__ == "__main__":
    unittest.main()
