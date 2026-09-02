#include "llviewerprecompiledheaders.h"

#include "xui_lab_event_api.h"

#include "xui_lab_error.h"

#include "llevents.h"

#include <string>

namespace xui_lab
{
LLSD callEventApi(std::string_view api_name, const LLSD& command)
{
    LLEventStream       reply_pump("xui-lab-event-reply", true);
    LLSD                reply;
    bool                received   = false;
    LLTempBoundListener connection = reply_pump.listen("capture",
                                                       [&reply, &received](const LLSD& event)
                                                       {
                                                           reply    = event;
                                                           received = true;
                                                           return true;
                                                       });

    LLSD request     = command;
    request["reply"] = reply_pump.getName();
    LLEventPumps::instance().obtain(std::string(api_name)).post(request);
    if (!received)
    {
        throw Error("event_api", "event API did not reply: " + std::string(api_name));
    }
    if (reply["error"].isDefined())
    {
        throw Error("event_api", reply["error"].asString());
    }
    return reply;
}

void postEventApi(std::string_view api_name, const LLSD& command)
{ LLEventPumps::instance().obtain(std::string(api_name)).post(command); }
} // namespace xui_lab
