#include "llviewerprecompiledheaders.h"

#include "xui_lab_runtime.h"

#include "xui_lab_error.h"
#include "xui_lab_event_api.h"
#include "xui_lab_inspection.h"
#include "xui_lab_inventory_fixture.h"
#include "xui_lab_fork_identity.h"
#include "xui_lab_types.h"
#include "xui_lab_ui_host.h"

#include "lleventapi.h"
#include "llapp.h"
#include "llfolderviewitem.h"
#include "llfolderviewmodelinventory.h"
#include "llinventorymodel.h"
#include "llsdjson.h"
#include "llsdutil.h"
#include "llui.h"
#include "llview.h"
#include "llviewermenu.h"

#include <algorithm>
#include <chrono>
#include <deque>
#include <exception>
#include <initializer_list>
#include <iostream>
#include <memory>
#include <mutex>
#include <ranges>
#include <set>
#include <string>
#include <string_view>
#include <thread>
#include <tuple>

namespace
{
using xui_lab::kFork;
using xui_lab::kForkCommit;

using LabError = xui_lab::Error;
using xui_lab::callEventApi;
using xui_lab::postEventApi;
using xui_lab::Subject;
using xui_lab::subjectName;

bool hasModifier(const LLSD& modifiers, std::string_view expected)
{
    return std::ranges::any_of(llsd::inArray(modifiers), [expected](const LLSD& modifier) { return modifier.asString() == expected; });
}

class Runtime final : public LLEventAPI
{
public:
    explicit Runtime(bool interactive = false) :
        LLEventAPI("XUILab", "Lifecycle operations for the standalone production UI host"),
        mInteractive(interactive)
    {
        add("initialize", "Initialize the selected fork, resources, window, and subject.", &Runtime::initialize);
        add("installCapabilities", "Install the capabilities requested by the scenario.", &Runtime::installCapabilities);
        add("frames", "Advance an exact number of UI frames.",
            [this](const LLSD& command)
            {
                requireInitialized();
                return mUIHost->advanceFrames(command["count"].asInteger());
            });
        add("stable", "Advance frames until the production UI tree stops changing.", &Runtime::stabilize);
        add("resizeViewport", "Resize the host viewport and production LLUI root.", &Runtime::resizeViewport);
        add("resizeSubject", "Resize the open production floater.", &Runtime::resizeSubject);
        add("capture", "Capture the production UI framebuffer.", &Runtime::capture);
        add("reload", "Destroy and recreate the registered subject from source XUI.", &Runtime::reload);
        add("diagnostics", "Report runtime, subject, viewport, focus, and graphics state.",
            [this](const LLSD&)
            {
                requireInitialized();
                return diagnostics();
            });
        add("shutdown", "Acknowledge shutdown so the parent can collect the process.", &Runtime::requestShutdown);
        add("query", "Translate high-level inspection requests to production event APIs.", &Runtime::query);
        add("input", "Translate high-level input requests to the production LLWindow event API.", &Runtime::input);
        add("pick", "Return the frontmost visible control at an LLUI screen position.", &Runtime::pick);
        add("highlight", "Select the control drawn by the headed hover overlay.", &Runtime::highlight);
    }

    ~Runtime() override { shutdown(); }

    bool done() const noexcept { return mDone; }

    void pumpInteractive()
    {
        if (!mInitialized)
        {
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
            return;
        }
        mUIHost->pumpInteractive();
        for (const LLSD& action : llsd::inArray(mUIHost->takeInteractiveActions()))
        {
            if (action.has("x") && action.has("y"))
            {
                LLView* target = mInspection->pickView(action["x"].asInteger(), action["y"].asInteger());
                if (target && !target->getPathname().empty())
                {
                    LLSD recorded         = action;
                    recorded["path"]      = target->getPathname();
                    recorded["controlId"] = mInspection->controlId(target);
                    mUIHost->recordAction(std::move(recorded));
                }
            }
            else
            {
                mUIHost->recordAction(action);
            }
        }
        if (const auto position = mUIHost->takePointerMove())
            mUIHost->setHighlight(mInspection->pickView(position->first, position->second));
        if (mUIHost->closeRequested())
            mDone = true;
    }

private:
    static Subject parseSubject(const LLSD& value)
    {
        if (!value.isString())
            throw LabError("subject", "subject must be a string");
        if (value.asString() == "test_widgets")
            return Subject::TestWidgets;
        if (value.asString() == "inventory_explorer")
            return Subject::InventoryExplorer;
        throw LabError("subject", "unsupported registered subject: " + value.asString());
    }

    static LLUUID requireUuid(const LLSD& object, const std::string& key, const std::string& label, bool allow_null = false)
    {
        if (!object.isMap() || !object[key].isString() || object[key].asString().empty())
        {
            throw LabError("fixture", label + "." + key + " must be a non-empty string");
        }
        const std::string value = object[key].asString();
        if (!LLUUID::validate(value))
            throw LabError("fixture", label + "." + key + " must be a UUID");
        LLUUID id(value);
        if (!allow_null && id.isNull())
            throw LabError("fixture", label + "." + key + " must not be null");
        return id;
    }

    LLSD initialize(const LLSD& command)
    {
        if (mInitialized)
            throw LabError("already_initialized", "runtime initialization may only occur once");
        if (command["fork"].asString() != kFork || command["forkCommit"].asString() != kForkCommit)
        {
            throw LabError("source_mismatch", "controller fork metadata does not match this binary");
        }
        mSubject = parseSubject(command["subject"]);

        const LLSD& viewport = command["viewport"];
        mUIHost              = std::make_unique<xui_lab::UIHost>(xui_lab::UIHostConfig{
            .resource_root = command["resourceRoot"].asString(),
            .artifact_dir  = command["artifactDir"].asString(),
            .pixel_width   = viewport["width"].asInteger(),
            .pixel_height  = viewport["height"].asInteger(),
            .ui_scale      = viewport["uiScale"].asReal(),
            .interactive   = mInteractive,
        });
        if (mSubject == Subject::InventoryExplorer)
        {
            mInventoryFixture = std::make_unique<xui_lab::InventoryFixture>(xui_lab::parseInventoryFixture(command["fixture"]));
        }
        mUIHost->openSubject(mSubject);
        mInspection  = std::make_unique<xui_lab::Inspection>(*mUIHost->root());
        mInitialized = true;
        (void)mUIHost->advanceFrames(2);

        return LLSDMap("supportedCapabilities", supportedCapabilities())("fork", std::string(kFork))(
            "forkCommit", std::string(kForkCommit))("subject", std::string(subjectName(mSubject)));
    }

    LLSD supportedCapabilities() const
    {
        LLSD capabilities = LLSD::emptyArray();
        capabilities.append("input");
        capabilities.append("inspection");
        capabilities.append("external_effects");
        if (mSubject == Subject::InventoryExplorer)
        {
            capabilities.append("inventory_model");
            capabilities.append("agent_identity");
            capabilities.append("menus");
            capabilities.append("texture_fetch");
        }
        return capabilities;
    }

    LLSD installCapabilities(const LLSD& command)
    {
        requireInitialized();
        const LLSD& requested = command["capabilities"];
        if (!requested.isArray())
        {
            throw LabError("capabilities", "capabilities must be an array");
        }

        std::set<std::string> supported;
        for (const LLSD& capability : llsd::inArray(supportedCapabilities()))
        {
            supported.insert(capability.asString());
        }
        for (const LLSD& capability : llsd::inArray(requested))
        {
            if (!capability.isString() || !supported.contains(capability.asString()))
            {
                throw LabError("missing_capability", "subject does not support capability: " + capability.asString());
            }
            mCapabilities.insert(capability.asString());
        }

        LLSD installed = LLSD::emptyArray();
        for (const std::string& capability : mCapabilities)
            installed.append(capability);
        return LLSDMap("capabilities", installed)("eventApis", exposedEventApiMetadata())("inputOperations", inputOperations());
    }

    LLSD stabilize(const LLSD& command)
    {
        requireInitialized();
        const S32 required = command["consecutiveFrames"].asInteger();
        const S32 maximum  = command["maximumFrames"].asInteger();
        if (required <= 0 || maximum < required)
            throw LabError("stable", "invalid stabilization frame counts");

        std::string previous;
        S32         consecutive = 0;
        for (S32 frame = 1; frame <= maximum; ++frame)
        {
            mUIHost->renderFrame(true);
            const std::string current = LlsdToJson(callEventApi("LLWindow", LLSDMap("op", "getSubtree")));
            consecutive               = current == previous ? consecutive + 1 : 1;
            previous                  = current;
            if (consecutive >= required)
                return LLSDMap("stable", true)("frames", frame);
        }
        return LLSDMap("stable", false)("frames", maximum);
    }

    LLSD resizeViewport(const LLSD& command)
    {
        requireInitialized();
        return mUIHost->resizeViewport(command);
    }

    LLSD resizeSubject(const LLSD& command)
    {
        requireInitialized();
        return mUIHost->resizeSubject(command);
    }

    LLSD reload(const LLSD&)
    {
        requireInitialized();
        return mUIHost->reload();
    }

    LLSD requestShutdown(const LLSD&)
    {
        mDone = true;
        return LLSDMap("shutdown", true);
    }

    LLSD query(const LLSD& command)
    {
        requireInitialized();
        const std::string kind = command["kind"].asString();
        if (kind == "menus")
        {
            requireCapability("menus");
            return mInspection->menus();
        }
        if (kind == "inventory")
        {
            requireCapability("inventory_model");
            return mInspection->inventory(mInventoryFixture->objectIds());
        }
        requireCapability("inspection");
        if (kind == "value")
        {
            if (!command["path"].isString())
                throw LabError("path", "control path must be a string");
            return mInspection->value(command["path"].asString());
        }
        if (kind != "tree")
            throw LabError("query", "unsupported query kind: " + kind);
        return mInspection->tree(command);
    }

    LLSD diagnostics()
    {
        LLSD result                  = mUIHost->diagnostics();
        result["subject"]["fixture"] = fixtureId();
        result["eventApis"]          = exposedEventApiMetadata();
        result["processId"]          = LLApp::getPid();
        if (mInspection)
            result["layout"] = mInspection->layoutDiagnostics();
        return result;
    }

    [[nodiscard]] bool hasCapability(std::string_view capability) const { return mCapabilities.contains(std::string(capability)); }

    void requireCapability(std::string_view capability) const
    {
        if (!hasCapability(capability))
        {
            throw LabError("missing_capability", "operation requires installed capability: " + std::string(capability));
        }
    }

    static void addEventApiMetadata(LLSD& result, std::string_view api_name, std::initializer_list<std::string_view> allowed_operations)
    {
        const auto api = LLEventAPI::getInstance(std::string(api_name));
        if (!api)
            return;

        LLSD operations = result.has(std::string(api_name)) ? result[std::string(api_name)]["operations"] : LLSD::emptyArray();
        for (const std::string_view operation_name : allowed_operations)
        {
            LLSD operation = api->getMetadata(std::string(operation_name));
            if (operation.isDefined())
                operations.append(operation);
        }
        if (operations.size() == 0)
            return;
        result[std::string(api_name)] =
            LLSDMap("description", api->getDesc())("dispatchKey", api->getDispatchKey())("operations", operations);
    }

    LLSD exposedEventApiMetadata() const
    {
        LLSD result = LLSD::emptyMap();
        addEventApiMetadata(result, "XUILab",
                            { "initialize", "installCapabilities", "frames", "stable", "resizeViewport", "resizeSubject", "capture",
                              "reload", "diagnostics", "shutdown", "pick", "highlight" });
        addEventApiMetadata(result, "LLFloaterReg",
                            { "getBuildMap", "showInstance", "hideInstance", "toggleInstance", "toggleInstanceOrBringToFront",
                              "instanceVisible", "clickButton" });
        if (hasCapability("inspection"))
        {
            addEventApiMetadata(result, "XUILab", { "query" });
            addEventApiMetadata(result, "LLWindow", { "getInfo", "getPaths", "getSubtree" });
            addEventApiMetadata(result, "UI", { "getValue" });
        }
        if (hasCapability("input"))
        {
            addEventApiMetadata(result, "XUILab", { "input" });
            addEventApiMetadata(result, "LLWindow",
                                { "mouseDown", "mouseDoubleClick", "mouseUp", "mouseMove", "mouseScroll", "selectAll", "pasteText" });
            addEventApiMetadata(result, "UI", { "setSelectedByValue" });
        }
        return result;
    }

    LLView* resolveTarget(const LLSD& command) const
    {
        if (command.has("controlId"))
            return mInspection->resolveControlId(command["controlId"].asString());
        if (command.has("modelId"))
        {
            requireCapability("inventory_model");
            return mInspection->resolveModelId(requireUuid(command, "modelId", "input"));
        }
        if (!command["path"].isString())
            throw LabError("path", "target path must be a string");
        return mInspection->resolvePath(command["path"].asString());
    }

    static LLSD pointerEventAt(std::string_view operation, std::string_view button, S32 screen_x, S32 screen_y)
    {
        S32 gl_x = 0;
        S32 gl_y = 0;
        LLUI::getInstance()->screenPointToGL(screen_x, screen_y, &gl_x, &gl_y);
        return LLSDMap("op", std::string(operation))("button", std::string(button))("x", gl_x)("y", gl_y);
    }

    // Hit the visible portion. A scrolled row's full rectangle can sit under
    // another control.
    static LLRect inputRect(LLView* target)
    {
        const LLRect clipped = xui_lab::Inspection::clippedScreenRect(*target);
        return clipped.getWidth() > 0 && clipped.getHeight() > 0 ? clipped : target->calcScreenRect();
    }

    static LLSD pointerEvent(std::string_view operation, std::string_view button, LLView* target)
    {
        const LLRect screen_rect = inputRect(target);
        return pointerEventAt(operation, button, screen_rect.getCenterX(), screen_rect.getCenterY());
    }

    LLSD inputOperations() const
    {
        LLSD operations = LLSD::emptyArray();
        if (!hasCapability("input"))
            return operations;
        for (const std::string_view operation :
             { "click", "doubleClick", "rightClick", "fill", "text", "key", "scroll", "drag", "dragAndDrop" })
            operations.append(std::string(operation));
        return operations;
    }

    [[nodiscard]] LLView* resolveSelector(const LLSD& selector) const
    {
        if (!selector.isMap())
            throw LabError("input", "input selector must be an object");
        return resolveTarget(selector);
    }

    static std::string_view acceptanceName(EAcceptance acceptance)
    {
        switch (acceptance)
        {
            case ACCEPT_POSTPONED:
                return "postponed";
            case ACCEPT_NO:
                return "no";
            case ACCEPT_NO_CUSTOM:
                return "noCustom";
            case ACCEPT_NO_LOCKED:
                return "noLocked";
            case ACCEPT_YES_COPY_SINGLE:
                return "yesCopySingle";
            case ACCEPT_YES_SINGLE:
                return "yesSingle";
            case ACCEPT_YES_COPY_MULTI:
                return "yesCopyMulti";
            case ACCEPT_YES_MULTI:
                return "yesMulti";
        }
        throw LabError("input", "production drag-and-drop returned an unknown acceptance value");
    }

    std::pair<EDragAndDropType, LLInventoryObject*> dragCargo(LLView* source) const
    {
        auto* folder_item = dynamic_cast<LLFolderViewItem*>(source);
        auto* model_item  = folder_item ? dynamic_cast<LLFolderViewModelItemInventory*>(folder_item->getViewModelItem()) : nullptr;
        if (!model_item)
            return { DAD_NONE, nullptr };

        requireCapability("inventory_model");
        EDragAndDropType cargo_type = DAD_NONE;
        LLUUID           cargo_id;
        if (!model_item->startDrag(&cargo_type, &cargo_id) || cargo_type == DAD_NONE || cargo_id.isNull())
            throw LabError("input", "production inventory source refused the drag: " + source->getPathname());
        LLInventoryObject* cargo = gInventory.getObject(cargo_id);
        if (!cargo)
            throw LabError("model_id", "drag-and-drop inventory object not found: " + cargo_id.asString());
        return { cargo_type, cargo };
    }

    [[nodiscard]] bool dispatchDragAndDrop(S32 screen_x, S32 screen_y, bool drop, EDragAndDropType cargo_type, void* cargo,
                                           EAcceptance* acceptance, std::string& tooltip)
    {
        if (LLUICtrl* top = gFocusMgr.getTopCtrl())
        {
            S32 local_x = 0;
            S32 local_y = 0;
            top->screenPointToLocal(screen_x, screen_y, &local_x, &local_y);
            if (top->handleDragAndDrop(local_x, local_y, MASK_NONE, drop, cargo_type, cargo, acceptance, tooltip))
                return true;
        }

        S32 local_x = 0;
        S32 local_y = 0;
        mUIHost->root()->screenPointToLocal(screen_x, screen_y, &local_x, &local_y);
        return mUIHost->root()->handleDragAndDrop(local_x, local_y, MASK_NONE, drop, cargo_type, cargo, acceptance, tooltip);
    }

    LLSD dragAndDrop(const LLSD& command)
    {
        const LLSD& source_selector = command["source"];
        const LLSD& target_selector = command["target"];
        LLView*     source          = resolveSelector(source_selector);
        LLView*     target          = resolveSelector(target_selector);
        if (!source->isInVisibleChain())
            throw LabError("input", "drag-and-drop source must be visible");

        const auto [cargo_type, cargo] = dragCargo(source);
        bool tray_drag_capture         = false;
        if (!target->isInVisibleChain())
        {
            auto* folder_item = dynamic_cast<LLFolderViewItem*>(source);
            if (!folder_item)
                throw LabError("input", "drag-and-drop target is hidden and the source cannot start a production inventory drag");
            LLToolDragAndDrop::instance().setMouseCapture(true);
            tray_drag_capture = true;
            mUIHost->renderFrame(true);
            if (!target->isInVisibleChain())
            {
                gFocusMgr.removeMouseCaptureWithoutCallback(&LLToolDragAndDrop::instance());
                throw LabError("input", "drag-and-drop target did not become visible during the production drag");
            }
        }
        EAcceptance acceptance = ACCEPT_NO;
        std::string tooltip;
        bool        handled      = false;
        bool        accepted     = false;
        bool        drop_handled = false;
        try
        {
            const LLRect target_rect = target->calcScreenRect();
            const S32    screen_x    = target_rect.getCenterX();
            const S32    screen_y    = target_rect.getCenterY();
            handled                  = dispatchDragAndDrop(screen_x, screen_y, false, cargo_type, cargo, &acceptance, tooltip);
            accepted                 = handled && acceptance >= ACCEPT_YES_COPY_SINGLE;
            if (accepted)
            {
                EAcceptance drop_acceptance = acceptance;
                drop_handled                = dispatchDragAndDrop(screen_x, screen_y, true, cargo_type, cargo, &drop_acceptance, tooltip);
            }
        }
        catch (...)
        {
            if (tray_drag_capture)
                gFocusMgr.removeMouseCaptureWithoutCallback(&LLToolDragAndDrop::instance());
            throw;
        }
        if (tray_drag_capture)
            gFocusMgr.removeMouseCaptureWithoutCallback(&LLToolDragAndDrop::instance());
        mUIHost->renderFrame(true);

        const std::string source_control_id = mInspection->controlId(source);
        const std::string target_control_id = mInspection->controlId(target);
        mUIHost->recordAction(LLSDMap("action", "drag_and_drop")("path", source->getPathname())("controlId", source_control_id)(
            "targetPath", target->getPathname())("targetControlId", target_control_id));
        return LLSDMap("event", "dragAndDrop")("handled", handled)("accepted", accepted)("dropped", accepted && drop_handled)(
            "acceptance", std::string(acceptanceName(acceptance)))("tooltip", tooltip)("cargoType", static_cast<S32>(cargo_type))(
            "source", describeControl(source))("target", describeControl(target));
    }

    LLSD describeControl(LLView* view) const
    {
        if (!view)
            return {};
        LLSD result          = view->getInfo();
        result["control_id"] = mInspection->controlId(view);
        return result;
    }

    std::pair<S32, S32> commandPosition(const LLSD& command, LLView* target) const
    {
        if (command.has("x") && command.has("y"))
            return { command["x"].asInteger(), command["y"].asInteger() };
        const LLRect rect = inputRect(target);
        return { rect.getCenterX(), rect.getCenterY() };
    }

    LLSD input(const LLSD& command)
    {
        requireInitialized();
        requireCapability("input");
        const std::string event = command["event"].asString();
        if (event != "click" && event != "doubleClick" && event != "key" && event != "text" && event != "fill" && event != "scroll" &&
            event != "drag" && event != "dragAndDrop")
        {
            throw LabError("input", "unsupported input event: " + event);
        }
        if (event == "dragAndDrop")
            return dragAndDrop(command);
        const bool has_target_selector = command.has("path") || command.has("modelId") || command.has("controlId");
        LLView*    target              = has_target_selector ? resolveTarget(command) : nullptr;
        if (!target && (event == "click" || event == "doubleClick" || event == "scroll") && command.has("x") && command.has("y"))
            target = mInspection->pickView(command["x"].asInteger(), command["y"].asInteger());
        if (!target && event == "drag" && command.has("startX") && command.has("startY"))
            target = mInspection->pickView(command["startX"].asInteger(), command["startY"].asInteger());
        if (!target && event != "click" && event != "doubleClick" && event != "drag")
            throw LabError("input", "input event requires a target control");
        const LLSD before = inputState();
        if (event == "scroll")
        {
            if (!command["clicks"].isInteger())
                throw LabError("input", "scroll clicks must be a non-zero integer");
            const S32 clicks = command["clicks"].asInteger();
            if (clicks == 0)
                throw LabError("input", "scroll clicks must be a non-zero integer");
            const auto [screen_x, screen_y] = commandPosition(command, target);
            (void)callEventApi("LLWindow", pointerEventAt("mouseMove", "LEFT", screen_x, screen_y));
            (void)mUIHost->takeScrollResult();
            postEventApi("LLWindow", LLSDMap("op", "mouseScroll")("clicks", clicks));
            LLSD result = mUIHost->takeScrollResult();
            if (!result.isMap())
                throw LabError("input", "production window did not report the scroll result");
            result["event"]     = event;
            result["path"]      = target->getPathname();
            result["controlId"] = mInspection->controlId(target);
            addInputState(result, before);
            mUIHost->recordAction(
                LLSDMap("action", "scroll")("path", target->getPathname())("controlId", mInspection->controlId(target))("clicks", clicks));
            mUIHost->renderFrame(true);
            return result;
        }
        if (event == "key" || event == "text" || event == "fill")
        {
            const std::string path           = target->getPathname();
            LLView*           keyboard_focus = dynamic_cast<LLView*>(gFocusMgr.getKeyboardFocus());
            const bool        target_has_focus =
                keyboard_focus && (keyboard_focus == target || keyboard_focus->hasAncestor(target) || target->hasAncestor(keyboard_focus));
            if (!target_has_focus)
            {
                (void)callEventApi("LLWindow", pointerEvent("mouseDown", "LEFT", target));
                (void)callEventApi("LLWindow", pointerEvent("mouseUp", "LEFT", target));
            }
            LLSD result;
            if (event == "key")
            {
                const std::string key       = command["key"].asString();
                const LLSD&       modifiers = command["modifiers"];
                if ((key == "a" || key == "A") && hasModifier(modifiers, "control") && !hasModifier(modifiers, "shift") &&
                    !hasModifier(modifiers, "alt"))
                {
                    const LLSD select_all = callEventApi("LLWindow", LLSDMap("op", "selectAll"));
                    result                = LLSDMap("handled", true)("key", key)("modifiers", modifiers)("selectAll", select_all);
                }
                else
                {
                    result = mUIHost->inputKey(key, modifiers);
                }
            }
            else if (event == "fill")
            {
                const LLSD select_all = callEventApi("LLWindow", LLSDMap("op", "selectAll"));
                const LLSD paste_text = callEventApi("LLWindow", LLSDMap("op", "pasteText")("text", command["text"]));
                result =
                    LLSDMap("handled", true)("text", command["text"])("replace", true)("selectAll", select_all)("pasteText", paste_text);
            }
            else
            {
                result = mUIHost->inputText(command["text"].asString(), false);
            }
            result["path"]      = path;
            result["controlId"] = mInspection->controlId(target);
            result["event"]     = event;
            addInputState(result, before);
            mUIHost->recordAction(LLSDMap("action", event)("path", path)("controlId", mInspection->controlId(target))(
                event == "key" ? "key" : "text", event == "key" ? command["key"] : command["text"]));
            mUIHost->renderFrame(true);
            return result;
        }
        if (event == "drag")
        {
            S32 start_x = 0;
            S32 start_y = 0;
            S32 end_x   = 0;
            S32 end_y   = 0;
            if (has_target_selector)
            {
                std::tie(start_x, start_y) = commandPosition(command, target);
                end_x                      = start_x + command["deltaX"].asInteger();
                end_y                      = start_y + command["deltaY"].asInteger();
            }
            else
            {
                start_x = command["startX"].asInteger();
                start_y = command["startY"].asInteger();
                end_x   = command["endX"].asInteger();
                end_y   = command["endY"].asInteger();
            }
            const LLSD down           = callEventApi("LLWindow", pointerEventAt("mouseDown", "LEFT", start_x, start_y));
            const LLSD after_down     = inputState();
            LLView*    gesture_target = dynamic_cast<LLView*>(gFocusMgr.getMouseCapture());
            if (!gesture_target)
                gesture_target = target;
            const LLSD move       = callEventApi("LLWindow", pointerEventAt("mouseMove", "LEFT", end_x, end_y));
            const LLSD after_move = inputState();
            const LLSD up         = callEventApi("LLWindow", pointerEventAt("mouseUp", "LEFT", end_x, end_y));
            mUIHost->renderFrame(true);
            LLSD result = LLSDMap("path", gesture_target ? gesture_target->getPathname() : std::string())(
                "controlId", gesture_target ? mInspection->controlId(gesture_target) : std::string())("event", event)(
                "handled", down["handled"].asBoolean() || move["handled"].asBoolean() || up["handled"].asBoolean())("down", down)(
                "move", move)("up", up)("start", LLSDMap("x", start_x)("y", start_y))("end", LLSDMap("x", end_x)("y", end_y))(
                "mouseCaptureAfterDown", after_down["mouseCapture"])("mouseCaptureAfterMove", after_move["mouseCapture"]);
            addInputState(result, before);
            if (gesture_target)
                mUIHost->recordAction(LLSDMap("action", "drag")("path", gesture_target->getPathname())(
                    "controlId", mInspection->controlId(gesture_target))("deltaX", end_x - start_x)("deltaY", end_y - start_y));
            return result;
        }
        const std::string button = command["button"].asString();
        if (button != "left" && button != "right")
            throw LabError("input", "button must be left or right");
        if (event == "doubleClick" && button != "left")
        {
            throw LabError("input", "doubleClick supports only the left button");
        }

        const std::string path              = target ? target->getPathname() : std::string();
        const auto [screen_x, screen_y]     = commandPosition(command, target);
        const std::string production_button = button == "left" ? "LEFT" : "RIGHT";
        const std::string down_operation    = event == "doubleClick" ? "mouseDoubleClick" : "mouseDown";
        const LLSD        down = callEventApi("LLWindow", pointerEventAt(down_operation, production_button, screen_x, screen_y));
        const bool        menu_visible_after_down = gMenuHolder && gMenuHolder->hasVisibleMenu();
        const LLSD        up = callEventApi("LLWindow", pointerEventAt("mouseUp", production_button, screen_x, screen_y));
        mUIHost->renderFrame(true);

        LLSD result =
            LLSDMap("path", path)("controlId", target ? mInspection->controlId(target) : std::string())("modelId", command["modelId"])(
                "event", event)("button", button)("handled", down["handled"].asBoolean() || up["handled"].asBoolean())(
                "downHandled", down["handled"])("upHandled", up["handled"])("menuVisibleAfterDown", menu_visible_after_down)(
                "menuVisibleAfterUp", gMenuHolder && gMenuHolder->hasVisibleMenu())("down", down)("up", up);
        addInputState(result, before);
        const std::string action = event == "doubleClick" ? "double_click" : (button == "right" ? "right_click" : "click");
        mUIHost->recordAction(
            LLSDMap("action", action)("path", path)("controlId", target ? mInspection->controlId(target) : std::string()));
        return result;
    }

    LLSD inputState() const
    {
        return LLSDMap("focus", describeControl(dynamic_cast<LLView*>(gFocusMgr.getKeyboardFocus())))(
            "mouseCapture", describeControl(dynamic_cast<LLView*>(gFocusMgr.getMouseCapture())));
    }

    void addInputState(LLSD& result, const LLSD& before) const
    {
        const LLSD after              = inputState();
        result["focusBefore"]         = before["focus"];
        result["focusAfter"]          = after["focus"];
        result["focusChanged"]        = before["focus"] != after["focus"];
        result["mouseCaptureBefore"]  = before["mouseCapture"];
        result["mouseCaptureAfter"]   = after["mouseCapture"];
        result["mouseCaptureChanged"] = before["mouseCapture"] != after["mouseCapture"];
    }

    LLSD pick(const LLSD& command)
    {
        requireInitialized();
        requireCapability("inspection");
        return mInspection->pick(command["x"].asInteger(), command["y"].asInteger());
    }

    LLSD highlight(const LLSD& command)
    {
        requireInitialized();
        requireCapability("inspection");
        LLView* target = command["target"].isMap() ? resolveTarget(command["target"]) : nullptr;
        mUIHost->setHighlight(target);
        mUIHost->renderFrame(true);
        return LLSDMap("visible", target != nullptr)("path", target ? target->getPathname() : std::string());
    }

    LLSD capture(const LLSD& command)
    {
        requireInitialized();
        LLView* highlighted = command["includeOverlay"].asBoolean() ? resolveTarget(command["highlight"]) : nullptr;
        return mUIHost->capture(command, highlighted, fixtureId());
    }

    void requireInitialized() const
    {
        if (!mInitialized)
            throw LabError("not_initialized", "initialize must be the first command");
    }

    [[nodiscard]] std::string fixtureId() const { return mInventoryFixture ? mInventoryFixture->id() : std::string(); }

    void shutdown()
    {
        if (!mInitialized)
            return;
        mInspection.reset();
        mUIHost.reset();
        mInventoryFixture.reset();
        mInitialized = false;
    }

    std::unique_ptr<xui_lab::InventoryFixture> mInventoryFixture;
    std::unique_ptr<xui_lab::UIHost>           mUIHost;
    std::unique_ptr<xui_lab::Inspection>       mInspection;
    bool                                       mInitialized = false;
    bool                                       mDone        = false;
    bool                                       mInteractive = false;
    std::set<std::string>                      mCapabilities;
    Subject                                    mSubject = Subject::TestWidgets;
};

LLSD failure(const std::string& code, const std::string& message)
{ return LLSDMap("ok", false)("error", LLSDMap("code", code)("message", message)); }

void writeResponse(const LLSD& response)
{
    std::cout << LlsdToJson(response) << '\n';
    std::cout.flush();
}

int scenarioMain()
{
    Runtime     runtime;
    std::string line;
    while (!runtime.done() && std::getline(std::cin, line))
    {
        LLSD        command;
        std::string parse_error;
        if (!LlsdFromJsonString(line, command, &parse_error) || !command.isMap())
        {
            writeResponse(failure("json", parse_error));
            continue;
        }
        try
        {
            writeResponse(LLSDMap("ok", true)("result", callEventApi("XUILab", command)));
        }
        catch (const LabError& error)
        {
            writeResponse(failure(error.code(), error.what()));
        }
        catch (const std::exception& error)
        {
            writeResponse(failure("internal", error.what()));
        }
    }
    return 0;
}

struct InteractiveInput
{
    std::mutex              mutex;
    std::deque<std::string> lines;
    bool                    closed = false;
};

int interactiveMain()
{
    Runtime runtime(true);
    auto    input = std::make_shared<InteractiveInput>();
    std::thread(
        [input]()
        {
            std::string line;
            while (std::getline(std::cin, line))
            {
                const std::scoped_lock lock(input->mutex);
                input->lines.push_back(std::move(line));
            }
            const std::scoped_lock lock(input->mutex);
            input->closed = true;
        })
        .detach();

    while (!runtime.done())
    {
        std::deque<std::string> lines;
        bool                    closed = false;
        {
            const std::scoped_lock lock(input->mutex);
            lines.swap(input->lines);
            closed = input->closed;
        }
        for (const std::string& line : lines)
        {
            LLSD        command;
            std::string parse_error;
            if (!LlsdFromJsonString(line, command, &parse_error) || !command.isMap())
            {
                writeResponse(failure("json", parse_error));
                continue;
            }
            try
            {
                writeResponse(LLSDMap("ok", true)("result", callEventApi("XUILab", command)));
            }
            catch (const LabError& error)
            {
                writeResponse(failure(error.code(), error.what()));
            }
            catch (const std::exception& error)
            {
                writeResponse(failure("internal", error.what()));
            }
        }
        if (closed && lines.empty())
            break;
        runtime.pumpInteractive();
    }
    return 0;
}
} // namespace

int xui_lab::runScenario()
{ return scenarioMain(); }

int xui_lab::runInteractive()
{ return interactiveMain(); }
