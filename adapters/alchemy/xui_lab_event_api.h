#pragma once

#include "llsd.h"

#include <string_view>

namespace xui_lab
{
LLSD callEventApi(std::string_view api_name, const LLSD& command);
void postEventApi(std::string_view api_name, const LLSD& command);
} // namespace xui_lab
