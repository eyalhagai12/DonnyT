"""Tests for the pure pieces: reading hand-written notes, and who-did-what.

Stdlib unittest, no network, no config file:

    python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from donnyt.config import Config, TeamMember  # noqa: E402
from donnyt.gitlab import MergeRequest  # noqa: E402
from donnyt.graph import GraphBuilder, working_days  # noqa: E402
from donnyt.jira import Issue, adf_text  # noqa: E402
from donnyt.vault import (  # noqa: E402
    Vault, bullets, dump_frontmatter, parse_frontmatter, parse_table, section, sections, unlink,
)

BRIEF = """# Sprint 7

%% Guidance the lead never sees in reading view. %%

## Vectors

%% The goals, most important first. %%

- **Correct v0** — measure: both bugs have a failing test
-

## Availability

| Person | Days off | Notes |
| --- | --- | --- |
| [[Dan Levi]] | 10-15, 10-16 | reserve duty |
| [[Tamar Adler\\|Tamar]] | — | 50% |
|  |  |  |

## Notes

Release freeze on 10-22.

<!-- donnyt:begin overview -->
## Overview

- generated, not the lead's
<!-- donnyt:end overview -->
"""


class Sections(unittest.TestCase):
    def test_reads_second_level_headings(self):
        self.assertEqual(list(sections(BRIEF)), ["Vectors", "Availability", "Notes"])

    def test_skips_managed_blocks_and_comments(self):
        self.assertNotIn("Overview", sections(BRIEF))
        self.assertNotIn("goals", section(BRIEF, "vectors"))

    def test_lookup_is_case_insensitive(self):
        self.assertEqual(section(BRIEF, "NOTES"), "Release freeze on 10-22.")
        self.assertEqual(section(BRIEF, "no such heading"), "")


class Bullets(unittest.TestCase):
    def test_skips_the_empty_template_bullet(self):
        self.assertEqual(bullets(section(BRIEF, "vectors")),
                         ["**Correct v0** — measure: both bugs have a failing test"])


class Tables(unittest.TestCase):
    def test_rows_keyed_by_header_with_links_unwrapped(self):
        rows = parse_table(section(BRIEF, "availability"))
        self.assertEqual([r["Person"] for r in rows], ["Dan Levi", "Tamar Adler"])
        self.assertEqual(rows[0]["Days off"], "10-15, 10-16")

    def test_blank_template_row_is_not_a_person(self):
        self.assertEqual(len(parse_table(section(BRIEF, "availability"))), 2)

    def test_no_table_is_no_rows(self):
        self.assertEqual(parse_table("- a list, not a table"), [])

    def test_unlink(self):
        self.assertEqual(unlink("[[A|b]] and [[C#heading]]"), "A and C")


class Frontmatter(unittest.TestCase):
    def test_round_trip(self):
        data = {"type": "sprint", "start": "2026-10-04", "on_call_cost": 0.5,
                "people": ["[[Maya Cohen]]", "[[Dan Levi]]"]}
        parsed, body = parse_frontmatter(dump_frontmatter(data) + "\n\n# Body\n")
        self.assertEqual(parsed, data)
        self.assertEqual(body.strip(), "# Body")

    def test_empty_key_is_an_empty_list(self):
        parsed, _ = parse_frontmatter("---\nstart:\nend: 2026-10-08\n---\n")
        self.assertEqual(parsed, {"start": [], "end": "2026-10-08"})


class WorkingDays(unittest.TestCase):
    def test_sunday_to_thursday_week(self):
        self.assertEqual(working_days("2026-10-04", "2026-10-15", ["Fri", "Sat"]), 10)

    def test_monday_to_friday_week(self):
        self.assertEqual(working_days("2026-10-05", "2026-10-16", ["Sat", "Sun"]), 10)

    def test_unparseable_dates(self):
        self.assertIsNone(working_days("soon", "later", []))


class Adf(unittest.TestCase):
    def test_cloud_rich_text_to_plain(self):
        doc = {"type": "doc", "content": [
            {"type": "paragraph", "content": [
                {"type": "text", "text": "Keep fields"}, {"type": "hardBreak"},
                {"type": "text", "text": "not sent."}]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "one"}]}]}]},
        ]}
        self.assertEqual(adf_text(doc).strip(), "Keep fields\nnot sent.\n\n- one")

    def test_data_center_text_passes_through(self):
        self.assertEqual(adf_text("plain wiki text"), "plain wiki text")


class DoneBy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config = Config(raw={}, root=Path(self.tmp.name), members=[
            TeamMember(name="Maya Cohen", jira="maya", gitlab="maya"),
            TeamMember(name="Lior Ben-David", jira="lior", gitlab="lior"),
        ])
        self.builder = GraphBuilder.__new__(GraphBuilder)
        self.builder.config = config
        self.builder.vault = Vault(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_gitlab_usernames_resolve_to_roster_names(self):
        """One person is one note: `lior` in GitLab is `Lior Ben-David` in Jira."""
        done = [Issue("TEAM-11", "Random order", "Done", "Bug", "Lior Ben-David", None, "Medium",
                      url="http://jira/TEAM-11")]
        mr = MergeRequest(2, "TEAM-11 Oldest first", "merged", "b", "main", "lior", "http://gl/2",
                          project="team/todo")
        text = self.builder._done_by(done, [(mr, ["maya", "lior"])])

        self.assertIn("### [[Lior Ben-David]]", text)
        self.assertIn("### [[Maya Cohen]]", text)
        self.assertNotIn("[[lior]]", text)
        self.assertIn("Reviewed [team/todo!2](http://gl/2) TEAM-11 Oldest first — for Lior Ben-David", text)
        # An author approving their own MR is not a review.
        self.assertEqual(text.count("Reviewed"), 1)

    def test_finished_then_merged_then_reviewed(self):
        done = [Issue("TEAM-19", "Paging", "Done", "Story", "Maya Cohen", None, "Medium", url="u")]
        theirs = MergeRequest(3, "TEAM-13", "merged", "b", "main", "lior", "http://gl/3")
        hers = MergeRequest(5, "TEAM-19", "merged", "b", "main", "maya", "http://gl/5")
        text = self.builder._done_by(done, [(theirs, ["maya"]), (hers, [])])
        maya = text.split("### [[Maya Cohen]]")[1].split("###")[0]
        self.assertLess(maya.index("Finished"), maya.index("Merged"))
        self.assertLess(maya.index("Merged"), maya.index("Reviewed"))

    def test_without_gitlab_says_so(self):
        done = [Issue("TEAM-1", "x", "Done", "Task", "Maya Cohen", None, "Medium", url="u")]
        self.assertIn("GitLab was not read", self.builder._done_by(done, None))
        self.assertEqual(self.builder._done_by([], []), "_Nothing finished yet._")


if __name__ == "__main__":
    unittest.main()
