from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from xui_lab.contracts import RuntimeMetadataContract
from xui_lab.domain import ForkId
from xui_lab.io import git_commit, matching_runtime_commit


class GitIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name)
        self.git("init", "--quiet")
        self.git("config", "user.name", "XUI Lab")
        self.git("config", "user.email", "xui-lab@example.test")
        (self.source / "viewer.txt").write_text("same source\n", encoding="utf-8")
        self.git("add", "viewer.txt")
        self.git("commit", "--quiet", "-m", "Original subject")
        self.original = git_commit(self.source)

    def git(self, *arguments: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.source), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )

    def metadata(self, commit: str) -> RuntimeMetadataContract:
        return RuntimeMetadataContract.model_validate(
            {"fork": "alchemy", "forkCommit": commit, "protocolVersion": 1}
        )

    def test_matches_a_reworded_commit_with_the_same_tree(self) -> None:
        self.git("commit", "--quiet", "--amend", "-m", "Reworded subject")
        reworded = git_commit(self.source)

        self.assertNotEqual(self.original, reworded)
        self.assertEqual(
            self.original,
            matching_runtime_commit(
                self.source,
                ForkId("alchemy"),
                reworded,
                self.metadata(self.original),
            ),
        )

    def test_rejects_a_runtime_built_from_different_source(self) -> None:
        (self.source / "viewer.txt").write_text("changed source\n", encoding="utf-8")
        self.git("commit", "--quiet", "-am", "Change source")

        self.assertIsNone(
            matching_runtime_commit(
                self.source,
                ForkId("alchemy"),
                git_commit(self.source),
                self.metadata(self.original),
            )
        )


if __name__ == "__main__":
    unittest.main()
