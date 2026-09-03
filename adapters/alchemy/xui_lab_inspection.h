#pragma once

#include "llrect.h"
#include "llsd.h"
#include "lluuid.h"

#include <string_view>
#include <string>
#include <unordered_map>
#include <vector>

class LLPanel;
class LLView;

namespace xui_lab
{
class Inspection final
{
public:
    explicit Inspection(LLPanel& root) noexcept;

    [[nodiscard]] LLSD        menus() const;
    [[nodiscard]] LLSD        inventory(const std::vector<LLUUID>& fixture_object_ids) const;
    [[nodiscard]] LLSD        value(std::string_view path) const;
    [[nodiscard]] LLSD        tree(const LLSD& command) const;
    [[nodiscard]] LLSD        layoutDiagnostics() const;
    [[nodiscard]] LLSD        pick(S32 x, S32 y) const;
    [[nodiscard]] LLView*     pickView(S32 x, S32 y) const;
    [[nodiscard]] LLView*     resolvePath(std::string_view path) const;
    [[nodiscard]] LLView*     resolveControlId(std::string_view control_id) const;
    [[nodiscard]] LLView*     resolveModelId(const LLUUID& id) const;
    [[nodiscard]] std::string controlId(LLView* view) const;

    // Screen rectangle clipped by every ancestor.
    [[nodiscard]] static LLRect clippedScreenRect(const LLView& view);

private:
    void rebuildControlIndex() const;

    LLPanel&                                         mRoot;
    mutable std::unordered_map<std::string, LLView*> mViewsByControlId;
    mutable std::unordered_map<LLView*, std::string> mControlIdsByView;
};
} // namespace xui_lab
