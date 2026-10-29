# T1 (2026-10-25): the usd_check command lists readable issues, not the repr of the validator Issue.

from __future__ import annotations

import unittest

from features.usd_assembler.validate.validator import Issue
from flux_actions.commands.utility import _issue_text


class IssueText(unittest.TestCase):
    def test_validator_issue(self) -> None:
        self.assertEqual(_issue_text(Issue("warn", "pas de defaultPrim")), "warn: pas de defaultPrim")
        self.assertEqual(_issue_text(Issue("error", "instance vide", "/town/PROPS/chair_01")),
                         "error: instance vide (/town/PROPS/chair_01)")

    def test_plain_value(self) -> None:
        self.assertEqual(_issue_text("deja un texte"), "deja un texte")


if __name__ == "__main__":
    unittest.main()
