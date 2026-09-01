#!/usr/bin/env python3
"""Invariant tests: append-only writes, parse round-trip, and the numbers engine."""

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
