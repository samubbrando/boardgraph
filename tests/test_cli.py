import unittest
from pathlib import Path

from boardgraph.cli import build_parser


class RenderPeopleArgsTests(unittest.TestCase):
    def test_people_flags_have_safe_defaults(self):
        args = build_parser().parse_args(["render", "--show-assignees"])
        self.assertTrue(args.show_assignees)
        self.assertEqual(args.people, Path("people-names.json"))
        self.assertEqual(args.assignee_format, "both")
        self.assertFalse(args.strict_people)

    def test_assignee_format_and_strict(self):
        args = build_parser().parse_args(
            [
                "render",
                "--show-assignees",
                "--assignee-format",
                "name",
                "--strict-people",
            ]
        )
        self.assertEqual(args.assignee_format, "name")
        self.assertTrue(args.strict_people)


if __name__ == "__main__":
    unittest.main()
