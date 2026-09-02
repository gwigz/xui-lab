#pragma once

#include "xui_lab_types.h"

#include "llsd.h"

#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>

class LLFloater;
class LLPanel;
class LLView;

namespace xui_lab
{
struct UIHostConfig
{
    std::filesystem::path resource_root;
    std::filesystem::path artifact_dir;
    S32                   pixel_width;
    S32                   pixel_height;
    F64                   ui_scale;
    bool                  interactive = false;
};

class UIHost final
{
public:
    explicit UIHost(const UIHostConfig& config);
    ~UIHost();

    UIHost(const UIHost&)            = delete;
    UIHost& operator=(const UIHost&) = delete;

    void                                             openSubject(Subject subject);
    [[nodiscard]] LLSD                               advanceFrames(S32 count);
    void                                             renderFrame(bool swap);
    [[nodiscard]] LLSD                               resizeViewport(const LLSD& command);
    [[nodiscard]] LLSD                               resizeSubject(const LLSD& command);
    [[nodiscard]] LLSD                               reload();
    [[nodiscard]] LLSD                               diagnostics() const;
    [[nodiscard]] LLSD                               capture(const LLSD& command, LLView* highlighted, std::string_view fixture_id);
    void                                             pumpInteractive();
    [[nodiscard]] bool                               closeRequested() const noexcept;
    [[nodiscard]] std::optional<std::pair<S32, S32>> takePointerMove();
    [[nodiscard]] LLSD                               takeInteractiveActions();
    void                                             setHighlight(LLView* target) noexcept;
    [[nodiscard]] LLSD                               inputKey(std::string_view key, const LLSD& modifiers);
    [[nodiscard]] LLSD                               inputText(std::string_view text, bool replace);
    void                                             recordAction(LLSD action);
    [[nodiscard]] const LLSD&                        recordedActions() const noexcept;

    [[nodiscard]] LLPanel*   root() const noexcept;
    [[nodiscard]] LLFloater* floater() const noexcept;

private:
    class Impl;
    std::unique_ptr<Impl> mImpl;
};
} // namespace xui_lab
