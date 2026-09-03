#include "llviewerprecompiledheaders.h"

#include "xui_lab_runtime.h"
#include "xui_lab_fork_identity.h"

#include "llcommon.h"
#include "llerrorcontrol.h"
#include "llsdjson.h"

#include <exception>
#include <iostream>
#include <string>
#include <string_view>

namespace
{
using xui_lab::kFork;
using xui_lab::kForkCommit;

class CommonRuntime final
{
public:
    CommonRuntime() { LLCommon::initClass(); }
    ~CommonRuntime() { LLCommon::cleanupClass(); }

    CommonRuntime(const CommonRuntime&)            = delete;
    CommonRuntime& operator=(const CommonRuntime&) = delete;
};
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
        CommonRuntime common;
        if (argc == 2 && std::string_view(argv[1]) == "--scenario")
            return xui_lab::runScenario();
        if (argc == 2 && std::string_view(argv[1]) == "--interactive")
            return xui_lab::runInteractive();
        std::cerr << "usage: xui-lab --metadata | --scenario | --interactive\n";
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
