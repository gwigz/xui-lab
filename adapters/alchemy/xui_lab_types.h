#pragma once

#include <string_view>

namespace xui_lab
{
enum class Subject
{
    TestWidgets,
    InventoryExplorer
};

[[nodiscard]] constexpr std::string_view subjectName(Subject subject) noexcept
{
    switch (subject)
    {
        case Subject::TestWidgets:
            return "test_widgets";
        case Subject::InventoryExplorer:
            return "inventory_explorer";
    }
}
} // namespace xui_lab
