#pragma once

#include "xui_lab_types.h"

#include "llsd.h"

#include <filesystem>
#include <memory>
#include <string_view>

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
};

class UIHost final
{
public:
    explicit UIHost(const UIHostConfig& config);
    ~UIHost();

    UIHost(const UIHost&)            = delete;
    UIHost& operator=(const UIHost&) = delete;

    void               openSubject(Subject subject);
    [[nodiscard]] LLSD advanceFrames(S32 count);
    void               renderFrame(bool swap);
    [[nodiscard]] LLSD resize(const LLSD& command);
    [[nodiscard]] LLSD reload();
    [[nodiscard]] LLSD diagnostics() const;
    [[nodiscard]] LLSD capture(const LLSD& command, LLView* highlighted, std::string_view fixture_id);

    [[nodiscard]] LLPanel*   root() const noexcept;
    [[nodiscard]] LLFloater* floater() const noexcept;

private:
    class Impl;
    std::unique_ptr<Impl> mImpl;
};
} // namespace xui_lab
