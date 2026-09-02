"""Tests for the command-line contract."""

from __future__ import annotations

import unittest

from xui_lab.cli import parser


class CommandLineTests(unittest.TestCase):
    def test_interactive_default_viewport_fits_the_test_floater(self) -> None:
        args = parser().parse_args(["interactive", "test_widgets"])

        self.assertEqual((1200, 800), (args.width, args.height))


if __name__ == "__main__":
    unittest.main()
