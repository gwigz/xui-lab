"""Compile the provider seam without viewer headers or libraries."""

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters/alchemy"


class SubjectProviderTests(unittest.TestCase):
    def build(self, names: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="lab providers ") as temporary:
            root = Path(temporary)
            (root / "llviewerprecompiledheaders.h").write_text("")
            (root / "main.cpp").write_text("""#include "xui_lab_types.h"
#include <iostream>
int main() {
    try {
        for (const auto& subject : xui_lab::extensionSubjects())
            std::cout << xui_lab::subjectName(&subject) << "\\n";
    } catch (const std::exception& error) {
        std::cerr << error.what();
        return 1;
    }
}
""")
            providers = []
            for index, name in enumerate(names):
                source = root / f"provider{index}.cpp"
                source.write_text(f'''#include "xui_lab_types.h"
namespace xui_lab {{
class Fixture{index} final : public SubjectFixture {{
    void registerWindow() override {{}}
}};
void register{index}(std::vector<ExtensionSubject>& subjects) {{
    subjects.push_back({{"{name}", {{"input"}}, [](EffectRecorder) {{
        return std::make_unique<Fixture{index}>();
    }}}});
}}
}}
''')
                provider = root / f"provider{index}.cmake"
                provider.write_text(
                    f'xui_lab_add_subject_provider(REGISTER register{index} SOURCES "{source}")\n'
                )
                providers.append(str(provider))
            (
                root / "CMakeLists.txt"
            ).write_text(f'''cmake_minimum_required(VERSION 3.24)
project(providers LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(VIEWER_BINARY_NAME viewer)
add_library(viewer INTERFACE)
set_property(TARGET viewer PROPERTY XUI_LAB_SUBJECT_PROVIDERS "{";".join(providers)}")
add_executable(xui-lab main.cpp "{ADAPTER}/xui_lab_types.cpp")
target_include_directories(xui-lab PRIVATE "{ADAPTER}" "{root}")
include("{ADAPTER}/SubjectProviders.cmake")
''')
            build = root / "build"
            for command in (
                ["cmake", "-S", str(root), "-B", str(build)],
                ["cmake", "--build", str(build)],
            ):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return subprocess.run(
                [str(build / "xui-lab")], capture_output=True, text=True
            )

    def test_without_providers(self) -> None:
        result = self.build(())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_multiple_providers(self) -> None:
        result = self.build(("project_first", "project_second"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(), ["project_first", "project_second"]
        )

    def test_duplicate_and_builtin_names_are_rejected(self) -> None:
        for names in (("project_same", "project_same"), ("preferences",)):
            with self.subTest(names=names):
                result = self.build(names)
                self.assertEqual(result.returncode, 1)
                self.assertIn("duplicate extension subject", result.stderr)
