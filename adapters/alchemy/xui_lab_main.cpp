#include "llviewerprecompiledheaders.h"

#include "xui_lab_runtime.h"

#include "llerrorcontrol.h"
#include "llsdjson.h"

#include <exception>
#include <iostream>
#include <string>
#include <string_view>

namespace
{
constexpr std::string_view kFork       = XUI_LAB_FORK;
constexpr std::string_view kForkCommit = XUI_LAB_FORK_COMMIT;
} // namespace

int main(int argc, char** argv)
{
    try
    {
        LLError::initForApplication(".", ".");
        LLError::setDefaultLevel(LLError::LEVEL_WARN);
        if (argc == 2 && std::string_view(argv[1]) == "--metadata")
        {
            std::cout << LlsdToJson(LLSDMap("fork", std::string(kFork))("forkCommit", std::string(kForkCommit))("protocolVersion", 1))
                      << '\n';
            return 0;
        }
        if (argc == 2 && std::string_view(argv[1]) == "--scenario")
            return xui_lab::runScenario();
        std::cerr << "usage: xui-lab --metadata | --scenario\n";
        return 2;
    }
    catch (const std::exception& error)
    {
        std::cerr << "xui-lab: " << error.what() << '\n';
        return 1;
    }
    catch (...)
    {
        std::cerr << "xui-lab: unknown startup failure\n";
        return 1;
    }
}
