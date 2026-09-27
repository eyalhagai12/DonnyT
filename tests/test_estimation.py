"""Tests for estimation's pure pieces: repo mapping, similarity, sizes, diffs.

    python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from donnyt.config import Config, ConfigError  # noqa: E402
from donnyt.estimate import rank_similar, similarity, size_points, words  # noqa: E402
from donnyt.gitlab import Change, _count_lines  # noqa: E402
from donnyt.jira import Issue, adf_doc, adf_text  # noqa: E402


def config(raw: dict) -> Config:
    return Config(raw=raw, root=Path("."))


def issue(key: str, summary: str, description: str = "") -> Issue:
    return Issue(key, summary, "Done", "Story", "", None, "Medium", description=description)


class RepoMapping(unittest.TestCase):
    MULTI = {"gitlab": {"repos": [
        {"project": "team/todo", "jira": ["api", "Backend"]},
        {"project": "team/todo-cli", "jira": ["cli"]},
    ]}}

    def test_components_and_labels_pick_repos_case_insensitively(self):
        c = config(self.MULTI)
        self.assertEqual([r.project for r in c.repos_for(["API"], [])], ["team/todo"])
        self.assertEqual([r.project for r in c.repos_for([], ["cli"])], ["team/todo-cli"])
        self.assertEqual([r.project for r in c.repos_for(["api"], ["cli"])], ["team/todo", "team/todo-cli"])

    def test_nothing_mapped_is_empty_so_the_skill_asks(self):
        self.assertEqual(config(self.MULTI).repos_for(["billing"], []), [])

    def test_single_project_config_still_works(self):
        c = config({"gitlab": {"default_project": "team/api"}})
        self.assertEqual([r.project for r in c.repos_for(["anything"], [])], ["team/api"])
        self.assertEqual(c.gitlab_default_project, "team/api")

    def test_default_project_falls_back_to_the_first_repo(self):
        self.assertEqual(config(self.MULTI).gitlab_default_project, "team/todo")


class Sizes(unittest.TestCase):
    def test_default_scale(self):
        self.assertEqual(config({}).estimation_sizes, {"XS": 1, "S": 2, "M": 3, "L": 5, "XL": 8})

    def test_custom_scale_is_ordered_and_upper_cased(self):
        c = config({"estimation": {"sizes": {"big": 13, "small": 1}}})
        self.assertEqual(list(c.estimation_sizes), ["SMALL", "BIG"])

    def test_bad_scale_names_the_setting(self):
        with self.assertRaisesRegex(ConfigError, "estimation.sizes"):
            config({"estimation": {"sizes": {"M": "three"}}}).estimation_sizes

    def test_size_points(self):
        sizes = config({}).estimation_sizes
        self.assertEqual(size_points(" m ", sizes), 3)
        with self.assertRaises(ValueError):
            size_points("XXL", sizes)


class Similarity(unittest.TestCase):
    def test_words_drop_short_and_stop_words(self):
        self.assertEqual(words("Add a due date to the todo"), {"due", "date", "todo"})

    def test_overlap(self):
        self.assertEqual(similarity("due dates", "due dates"), 1.0)
        self.assertEqual(similarity("due dates", "rate limiting"), 0.0)

    def test_rank_best_first_without_itself_or_strangers(self):
        target = issue("T-1", "Filter todos by due date", "overdue filter")
        pool = [
            target,
            issue("T-2", "Sort todos by due date"),
            issue("T-3", "Rate limit the API"),
            issue("T-4", "Filter todos by done state", "done filter"),
        ]
        ranked = [i.key for i, _ in rank_similar(target, pool)]
        self.assertNotIn("T-1", ranked)
        self.assertNotIn("T-3", ranked)
        # Sharing "todos due date" beats sharing "filter todos".
        self.assertEqual(ranked, ["T-2", "T-4"])


class Diffs(unittest.TestCase):
    def test_count_lines_skips_headers(self):
        diff = "--- a/x.go\n+++ b/x.go\n@@ -1,2 +1,3 @@\n context\n-old\n+new\n+more\n"
        self.assertEqual(_count_lines(diff), (2, 1))

    def test_areas_most_touched_first(self):
        change = Change("team/todo", "mr", files=[
            "internal/todo/a.go", "internal/todo/b.go", "cmd/todo/main.go", "README.md"])
        self.assertEqual(change.areas, ["internal/todo", "cmd/todo", "."])


class CloudComments(unittest.TestCase):
    def test_adf_doc_round_trips_through_adf_text(self):
        text = "Estimate: M (3 points)\n\nLike TEAM-12: one package, tests."
        self.assertEqual(adf_text(adf_doc(text)).strip(), text)


if __name__ == "__main__":
    unittest.main()
