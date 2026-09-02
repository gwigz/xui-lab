#pragma once

#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>

namespace xui_lab
{
class Error final : public std::runtime_error
{
public:
    Error(std::string code, std::string_view message) : std::runtime_error(std::string(message)), mCode(std::move(code)) {}

    [[nodiscard]] const std::string& code() const noexcept { return mCode; }

private:
    std::string mCode;
};
} // namespace xui_lab
