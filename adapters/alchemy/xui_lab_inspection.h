#pragma once

#include "llsd.h"
#include "lluuid.h"

#include <string_view>
#include <vector>

class LLPanel;
class LLView;

namespace xui_lab
{
class Inspection final
{
public:
    explicit Inspection(LLPanel& root) noexcept;

    [[nodiscard]] LLSD    menus() const;
    [[nodiscard]] LLSD    inventory(const std::vector<LLUUID>& fixture_object_ids) const;
    [[nodiscard]] LLSD    value(std::string_view path) const;
    [[nodiscard]] LLSD    tree(const LLSD& command) const;
    [[nodiscard]] LLView* resolvePath(std::string_view path) const;
    [[nodiscard]] LLView* resolveModelId(const LLUUID& id) const;

private:
    LLPanel& mRoot;
};
} // namespace xui_lab
