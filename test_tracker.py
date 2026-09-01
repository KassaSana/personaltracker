#!/usr/bin/env python3
"""Invariant tests: append-only writes, parse round-trip, and the numbers engine."""

import contextlib
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
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

    def test_stats_writes_generated_notes(self):
        self.seed("2026-08-31", "type:: commit | when:: 2026-08-31T09:00")
        self.run_cli("stats", "30")
        for name in tracker.GENERATED_NOTES:
            path = os.path.join(self.vault, name)
            self.assertTrue(os.path.isfile(path), name)
            self.assertTrue(tracker.read_text(path).startswith("<!-- Generated by tracker.py"))

    def test_generated_notes_are_not_label_candidates(self):
        self.seed("2026-08-31", "type:: commit | when:: 2026-08-31T09:00")
        self.run_cli("stats", "7")
        recent = list(tracker.iter_recent_notes(self.vault, datetime(2000, 1, 1)))
        self.assertFalse([p for p in recent if os.path.basename(p) in tracker.GENERATED_NOTES])

    def test_stats_rejects_bad_windows(self):
        for argv in (("stats", "9"), ("stats", "--weeks", "0")):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.run_cli(*argv)


if __name__ == "__main__":
    unittest.main()
