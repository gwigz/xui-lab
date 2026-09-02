from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import cpp_quality  # noqa: E402


class CppQualityTests(unittest.TestCase):
    def test_default_discovery_ignores_non_cpp_adapter_files(self) -> None:
        files = cpp_quality.adapter_files([], cpp_quality.CPP_SUFFIXES)

        self.assertTrue(files)
        self.assertTrue(all(path.suffix in cpp_quality.CPP_SUFFIXES for path in files))
        self.assertNotIn(ROOT / "adapters/alchemy/EVENT_APIS.md", files)

    def test_explicit_viewer_source_is_rejected(self) -> None:
        viewer_source = "viewers/alchemy/indra/newview/llviewerwindow.cpp"

        with self.assertRaisesRegex(
            cpp_quality.QualityError, "outside the adapter tree"
        ):
            cpp_quality.adapter_files([viewer_source], cpp_quality.CPP_SUFFIXES)

    def test_tool_lookup_prefers_the_active_python_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            python = directory / "python"
            tool = directory / "clang-format"
            python.touch()
            tool.write_text(
                "#!/bin/sh\necho 'clang-format version 22.1.8'\n",
                encoding="utf-8",
            )
            os.chmod(tool, 0o755)

            with patch.object(cpp_quality.sys, "executable", str(python)):
                self.assertEqual(str(tool), cpp_quality.llvm_tool("clang-format"))


if __name__ == "__main__":
    unittest.main()
