#include "llviewerprecompiledheaders.h"

#include "xui_lab_ui_host.h"

#include "xui_lab_error.h"
#include "xui_lab_event_api.h"
#include "xui_lab_fork_identity.h"

#include "altextureslot.h"
#include "llaccordionctrl.h"
#include "alfloaterinventoryexplorer.h"
#include "llcallbacklist.h"
#include "llcontrol.h"
#include "llcriticaldamp.h"
#include "lldir.h"
#include "llfloater.h"
#include "llfloaterreg.h"
#include "llfontfreetype.h"
#include "llfontgl.h"
#include "llfolderviewitem.h"
#include "llframetimer.h"
#include "llfocusmgr.h"
#include "llgl.h"
#include "llglslshader.h"
#include "llglstates.h"
#include "llgltexture.h"
#include "llimage.h"
#include "llimagegl.h"
#include "llimagepng.h"
#include "llinitdestroyclass.h"
#include "lllayoutstack.h"
#include "llkeyboard.h"
#include "llmenugl.h"
#include "llmortician.h"
#include "llnotifications.h"
#include "llpanel.h"
#include "llrender.h"
#include "llrender2dutils.h"
#include "llsdjson.h"
#include "llsdutil.h"
#include "llshadermgr.h"
#include "lltrans.h"
#include "lltransutil.h"
#include "llui.h"
#include "llurlaction.h"
#include "lluictrlfactory.h"
#include "lluicolortable.h"
#include "lluiimage.h"
#include "llvertexbuffer.h"
#include "llview.h"
#include "llviewereventrecorder.h"
#include "llviewercontrol.h"
#include "llviewermenu.h"
#include "llwearabletype.h"
#include "llwindow.h"
#include "llwindowcallbacks.h"
#include "llwindowlistener.h"
#include "llxmlnode.h"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdio>
#include <exception>
#include <filesystem>
#include <fstream>
#include <map>
#include <memory>
#include <optional>
#include <ranges>
#include <set>
#include <string>
#include <string_view>
#include <thread>
#include <utility>

namespace
{
using xui_lab::kFork;
using xui_lab::kForkCommit;

void ignoreUISound(const LLUUID&)
{
}

LLSD rectToLLSD(const LLRect& rect)
{ return LLSDMap("left", rect.mLeft)("right", rect.mRight)("bottom", rect.mBottom)("top", rect.mTop); }

class LabTranslationBridge final : public LLTranslationBridge
{
public:
    std::string getString(const std::string& xml_desc) override { return LLTrans::getString(xml_desc); }
};

class LabShaderMgr final : public LLShaderMgr
{
public:
    explicit LabShaderMgr(std::filesystem::path shader_root) : mShaderRoot(std::move(shader_root))
    {
        sInstance = this;
        initAttribsAndUniforms();
    }

    ~LabShaderMgr() override { sInstance = nullptr; }

    std::string getShaderDirPrefix() override { return mShaderRoot.string(); }

    void updateShaderUniforms(LLGLSLShader*) override {}

private:
    std::filesystem::path mShaderRoot;
};

struct ImageDeclaration
{
    std::string            filename;
    LLRect                 scale       = LLRect::null;
    LLRect                 clip        = LLRect::null;
    LLUIImage::EScaleStyle scale_style = LLUIImage::SCALE_INNER;
};

class LabImageProvider final : public LLImageProviderInterface
{
public:
    void loadDeclarations()
    {
        const auto paths = gDirUtilp->findSkinnedFilenames(LLDir::TEXTURES, "textures.xml", LLDir::ALL_SKINS);
        if (paths.empty())
        {
            throw xui_lab::Error("textures", "production textures.xml was not found");
        }

        for (const std::string& path : paths)
        {
            LLXMLNodePtr root;
            if (!LLXMLNode::parseFile(path, root, nullptr))
            {
                throw xui_lab::Error("textures", "failed to parse " + path);
            }
            for (LLXMLNodePtr node = root->getFirstChild(); node.notNull(); node = node->getNextSibling())
            {
                if (!node->hasName("texture"))
                    continue;
                std::string name;
                if (!node->getAttributeString("name", name) || name.empty())
                    continue;

                ImageDeclaration declaration;
                if (!node->getAttributeString("file_name", declaration.filename))
                    declaration.filename = name;
                S32 left   = 0;
                S32 top    = 0;
                S32 right  = 0;
                S32 bottom = 0;
                if (node->getAttributeS32("scale.left", left) && node->getAttributeS32("scale.top", top) &&
                    node->getAttributeS32("scale.right", right) && node->getAttributeS32("scale.bottom", bottom))
                {
                    declaration.scale.set(left, top, right, bottom);
                }
                if (node->getAttributeS32("clip.left", left) && node->getAttributeS32("clip.top", top) &&
                    node->getAttributeS32("clip.right", right) && node->getAttributeS32("clip.bottom", bottom))
                {
                    declaration.clip.set(left, top, right, bottom);
                }
                std::string scale_type;
                if (node->getAttributeString("scale_type", scale_type) && scale_type == "scale_outer")
                {
                    declaration.scale_style = LLUIImage::SCALE_OUTER;
                }
                mDeclarations[name] = std::move(declaration);
            }
        }
    }

    LLPointer<LLUIImage> getUIImage(std::string_view requested_name, S32) override
    {
        const std::string name(requested_name);
        if (const auto found = mImages.find(name); found != mImages.end())
            return found->second;

        ImageDeclaration declaration;
        if (const auto found = mDeclarations.find(name); found != mDeclarations.end())
            declaration = found->second;
        else
            declaration.filename = name;

        const std::string path = gDirUtilp->findSkinnedFilename(LLDir::TEXTURES, declaration.filename);
        if (path.empty())
            throw xui_lab::Error("texture", "production UI texture not found: " + name);

        LLPointer<LLImageFormatted> formatted = LLImageFormatted::createFromExtension(path);
        LLPointer<LLImageRaw>       raw       = new LLImageRaw();
        if (formatted.isNull() || !formatted->load(path) || !formatted->decode(raw, 0.f))
        {
            throw xui_lab::Error("texture", "failed to decode production UI texture: " + path);
        }

        LLPointer<LLGLTexture> texture = new LLGLTexture(raw, false);
        texture->setBoostLevel(LLGLTexture::BOOST_UI);
        texture->setNoDelete();
        LLPointer<LLUIImage> image = new LLUIImage(name, texture);
        image->setScaleStyle(declaration.scale_style);
        if (declaration.clip != LLRect::null)
        {
            image->setClipRegion(normalize(declaration.clip, texture->getWidth(), texture->getHeight()));
        }
        if (declaration.scale != LLRect::null)
        {
            image->setScaleRegion(normalize(declaration.scale, image->getWidth(), image->getHeight()));
        }
        mImages.emplace(name, image);
        return image;
    }

    LLPointer<LLUIImage> getUIImageByID(const LLUUID& id, S32) override
    { throw xui_lab::Error("texture_id", "network texture UUID is unavailable in xui-lab: " + id.asString()); }

    void installWhiteTexture()
    {
        const LLPointer<LLUIImage> white_image   = getUIImage("white.tga", LLGLTexture::BOOST_UI);
        LLImageGL*                 white_texture = white_image->getImage()->getGLTexture();
        if (!white_texture || !white_texture->getTexName())
            throw xui_lab::Error("texture", "production white UI texture has no GL texture");
        ALTextureSlot::sWhiteTexture = white_texture->getTexName();
    }

    void cleanUp() override
    {
        ALTextureSlot::sWhiteTexture = 0;
        LLUIImage::cleanupClass();
        mImages.clear();
    }

private:
    static LLRectf normalize(const LLRect& rect, S32 width, S32 height)
    {
        return { llclamp(static_cast<F32>(rect.mLeft) / static_cast<F32>(width), 0.f, 1.f),
                 llclamp(static_cast<F32>(rect.mTop) / static_cast<F32>(height), 0.f, 1.f),
                 llclamp(static_cast<F32>(rect.mRight) / static_cast<F32>(width), 0.f, 1.f),
                 llclamp(static_cast<F32>(rect.mBottom) / static_cast<F32>(height), 0.f, 1.f) };
    }

    std::map<std::string, ImageDeclaration, std::less<>>     mDeclarations;
    std::map<std::string, LLPointer<LLUIImage>, std::less<>> mImages;
};

class LabWindow final : public LLWindowCallbacks
{
public:
    LabWindow(S32 width, S32 height, bool interactive)
    {
        const U32 flags = interactive ? 0 : LLWindow::WINDOW_FLAG_HIDDEN;
        mWindow = LLWindowManager::createWindow(this, "Alchemy Viewer XUI Lab", "xui-lab", 0, 0, width, height, flags, false, true, false,
                                                true, false);
        if (!mWindow)
            throw xui_lab::Error("window", "failed to create the production LLWindow");
        if (interactive)
            mWindow->show();
    }

    ~LabWindow() override
    {
        if (mWindow)
            LLWindowManager::destroyWindow(mWindow);
    }

    [[nodiscard]] LLWindow* get() const noexcept { return mWindow; }
    [[nodiscard]] F32       systemUIScale() const
    {
        const F32 scale = mWindow->getSystemUISize();
        return scale > 0.f ? scale : 1.f;
    }
    void                                             setRoot(LLView* root) noexcept { mRoot = root; }
    [[nodiscard]] std::optional<std::pair<S32, S32>> takePointerMove() { return std::exchange(mPointerMove, std::nullopt); }
    [[nodiscard]] std::optional<std::pair<S32, S32>> takeResize() { return std::exchange(mResize, std::nullopt); }
    [[nodiscard]] bool                               closeRequested() const noexcept { return mCloseRequested; }

    void gatherInput()
    {
        mGatheringInput = true;
        mWindow->gatherInput();
        mGatheringInput = false;
    }

    [[nodiscard]] LLSD takeInteractiveActions()
    {
        LLSD result         = std::move(mInteractiveActions);
        mInteractiveActions = LLSD::emptyArray();
        return result;
    }

    [[nodiscard]] LLSD takeScrollResult()
    {
        LLSD result   = std::move(mScrollResult);
        mScrollResult = LLSD();
        return result;
    }

    bool sendKey(KEY key, MASK mask)
    {
        const bool down = handleTranslatedKeyDown(key, mask, false);
        const bool up   = handleTranslatedKeyUp(key, mask);
        return down || up;
    }

    bool sendUnicode(llwchar character) { return handleUnicodeChar(character, MASK_NONE); }

    bool handleMouseDown(LLWindow*, LLCoordGL position, MASK mask) override
    {
        const LLCoordGL screen = screenPosition(position);
        if (LLMouseHandler* capture = gFocusMgr.getMouseCapture())
        {
            S32 local_x = 0;
            S32 local_y = 0;
            capture->screenPointToLocal(screen.mX, screen.mY, &local_x, &local_y);
            return capture->handleMouseDown(local_x, local_y, mask);
        }
        return mRoot->handleMouseDown(screen.mX, screen.mY, mask);
    }

    bool handleMouseUp(LLWindow*, LLCoordGL position, MASK mask) override
    {
        const LLCoordGL screen = screenPosition(position);
        bool            handled;
        if (LLMouseHandler* capture = gFocusMgr.getMouseCapture())
        {
            S32 local_x = 0;
            S32 local_y = 0;
            capture->screenPointToLocal(screen.mX, screen.mY, &local_x, &local_y);
            handled = capture->handleMouseUp(local_x, local_y, mask);
        }
        else
        {
            handled = mRoot->handleMouseUp(screen.mX, screen.mY, mask);
        }
        queuePointerAction("click", screen);
        return handled;
    }

    bool handleRightMouseDown(LLWindow*, LLCoordGL position, MASK mask) override
    {
        const LLCoordGL screen     = screenPosition(position);
        const bool      menu_shown = gMenuHolder && gMenuHolder->hasVisibleMenu();
        bool            handled;
        if (LLMouseHandler* capture = gFocusMgr.getMouseCapture())
        {
            S32 local_x = 0;
            S32 local_y = 0;
            capture->screenPointToLocal(screen.mX, screen.mY, &local_x, &local_y);
            handled = capture->handleRightMouseDown(local_x, local_y, mask);
        }
        else
        {
            handled = mRoot->handleRightMouseDown(screen.mX, screen.mY, mask);
        }
        if (!menu_shown)
            publishContextMenuSpawnPos(screen);
        return handled;
    }

    // showPopup stores the OS cursor as the spawn point. The lab never moves
    // that cursor, so the matching right mouse up looks like a drag and commits
    // or hides the menu. Write the injected click instead.
    static void publishContextMenuSpawnPos(LLCoordGL screen)
    {
        if (!gMenuHolder || !gMenuHolder->hasVisibleMenu())
            return;
        S32 local_x = 0;
        S32 local_y = 0;
        gMenuHolder->screenPointToLocal(screen.mX, screen.mY, &local_x, &local_y);
        LLMenuHolderGL::sContextMenuSpawnPos.set(local_x, local_y);
    }

    bool handleRightMouseUp(LLWindow*, LLCoordGL position, MASK mask) override
    {
        const LLCoordGL screen = screenPosition(position);
        bool            handled;
        if (LLMouseHandler* capture = gFocusMgr.getMouseCapture())
        {
            S32 local_x = 0;
            S32 local_y = 0;
            capture->screenPointToLocal(screen.mX, screen.mY, &local_x, &local_y);
            handled = capture->handleRightMouseUp(local_x, local_y, mask);
        }
        else
        {
            handled = mRoot->handleRightMouseUp(screen.mX, screen.mY, mask);
        }
        queuePointerAction("right_click", screen);
        return handled;
    }

    bool handleMiddleMouseDown(LLWindow*, LLCoordGL position, MASK mask) override
    {
        const LLCoordGL screen = screenPosition(position);
        if (LLMouseHandler* capture = gFocusMgr.getMouseCapture())
        {
            S32 local_x = 0;
            S32 local_y = 0;
            capture->screenPointToLocal(screen.mX, screen.mY, &local_x, &local_y);
            return capture->handleMiddleMouseDown(local_x, local_y, mask);
        }
        return mRoot->handleMiddleMouseDown(screen.mX, screen.mY, mask);
    }

    bool handleMiddleMouseUp(LLWindow*, LLCoordGL position, MASK mask) override
    {
        const LLCoordGL screen = screenPosition(position);
        if (LLMouseHandler* capture = gFocusMgr.getMouseCapture())
        {
            S32 local_x = 0;
            S32 local_y = 0;
            capture->screenPointToLocal(screen.mX, screen.mY, &local_x, &local_y);
            return capture->handleMiddleMouseUp(local_x, local_y, mask);
        }
        return mRoot->handleMiddleMouseUp(screen.mX, screen.mY, mask);
    }

    bool handleDoubleClick(LLWindow*, LLCoordGL position, MASK mask) override
    {
        const LLCoordGL screen  = screenPosition(position);
        const bool      handled = mRoot->handleDoubleClick(screen.mX, screen.mY, mask);
        queuePointerAction("double_click", screen);
        return handled;
    }

    void handleMouseMove(LLWindow*, LLCoordGL position, MASK mask) override
    {
        const LLCoordGL screen = screenPosition(position);
        mPointerMove           = std::pair(screen.mX, screen.mY);
        mCurrentPointer        = screen;
        if (LLMouseHandler* capture = gFocusMgr.getMouseCapture())
        {
            S32 local_x = 0;
            S32 local_y = 0;
            capture->screenPointToLocal(screen.mX, screen.mY, &local_x, &local_y);
            capture->handleHover(local_x, local_y, mask);
            return;
        }
        mRoot->handleHover(screen.mX, screen.mY, mask);
    }

    void handleScrollWheel(LLWindow*, LLScrollDelta delta) override
    {
        bool handled = false;
        if (LLMouseHandler* capture = gFocusMgr.getMouseCapture())
        {
            S32 local_x = 0;
            S32 local_y = 0;
            capture->screenPointToLocal(mCurrentPointer.mX, mCurrentPointer.mY, &local_x, &local_y);
            handled = capture->handleScrollWheel(local_x, local_y, delta);
        }
        else if (LLUICtrl* top = gFocusMgr.getTopCtrl())
        {
            S32 local_x = 0;
            S32 local_y = 0;
            top->screenPointToLocal(mCurrentPointer.mX, mCurrentPointer.mY, &local_x, &local_y);
            handled = top->handleScrollWheel(local_x, local_y, delta);
        }
        if (!handled)
            handled = mRoot->handleScrollWheel(mCurrentPointer.mX, mCurrentPointer.mY, delta);

        mScrollResult = LLSDMap("handled", handled)("clicks", delta.mClicks)("x", mCurrentPointer.mX)("y", mCurrentPointer.mY);
        if (mGatheringInput)
            mInteractiveActions.append(
                LLSDMap("action", "scroll")("clicks", delta.mClicks)("x", mCurrentPointer.mX)("y", mCurrentPointer.mY));
    }

    bool handleTranslatedKeyDown(KEY key, MASK mask, bool) override
    {
        LLFocusableElement* focus = gFocusMgr.getKeyboardFocus();
        if (focus && !(mask & (MASK_CONTROL | MASK_ALT)) && key >= 0x20 && key < 0x7f && !focus->wantsKeyUpKeyDown())
            return true;
        const bool handled = (gMenuHolder && gMenuHolder->handleKey(key, mask, true)) || (focus && focus->handleKey(key, mask, false)) ||
                             mRoot->handleKey(key, mask, true);
        queueKeyAction(key, focus);
        return handled;
    }

    bool handleTranslatedKeyUp(KEY key, MASK mask) override
    {
        LLFocusableElement* focus = gFocusMgr.getKeyboardFocus();
        return focus ? focus->handleKeyUp(key, mask, false) : mRoot->handleKeyUp(key, mask, true);
    }

    bool handleUnicodeChar(llwchar character, MASK) override
    {
        LLFocusableElement* focus   = gFocusMgr.getKeyboardFocus();
        const bool          handled = focus ? focus->handleUnicodeChar(character, false) : mRoot->handleUnicodeChar(character, true);
        queueTextAction(character, focus);
        return handled;
    }

    void handleResize(LLWindow*, S32 width, S32 height) override { mResize = std::pair(width, height); }

    bool handleDPIChanged(LLWindow*, F32, S32 width, S32 height) override
    {
        mResize = std::pair(width, height);
        return true;
    }

    bool handleCloseRequest(LLWindow*, bool) override
    {
        mCloseRequested = true;
        return false;
    }

    void handleQuit(LLWindow*) override { mCloseRequested = true; }

private:
    void queuePointerAction(std::string_view action, LLCoordGL position)
    {
        if (mGatheringInput)
            mInteractiveActions.append(LLSDMap("action", std::string(action))("x", position.mX)("y", position.mY));
    }

    void queueKeyAction(KEY key, LLFocusableElement* focus)
    {
        auto* view = dynamic_cast<LLView*>(focus);
        if (mGatheringInput && view)
            mInteractiveActions.append(LLSDMap("action", "key")("path", view->getPathname())("key", LLKeyboard::stringFromKey(key, false)));
    }

    void queueTextAction(llwchar character, LLFocusableElement* focus)
    {
        auto* view = dynamic_cast<LLView*>(focus);
        if (mGatheringInput && view && character >= 0x20 && character != 0x7f)
            mInteractiveActions.append(
                LLSDMap("action", "text")("path", view->getPathname())("text", wstring_to_utf8str(LLWString(1, character))));
    }

    LLCoordGL screenPosition(LLCoordGL position)
    {
        S32 screen_x = 0;
        S32 screen_y = 0;
        LLUI::getInstance()->glPointToScreen(position.mX, position.mY, &screen_x, &screen_y);
        return { screen_x, screen_y };
    }

    LLWindow*                          mWindow = nullptr;
    LLView*                            mRoot   = nullptr;
    LLCoordGL                          mCurrentPointer;
    std::optional<std::pair<S32, S32>> mPointerMove;
    std::optional<std::pair<S32, S32>> mResize;
    LLSD                               mInteractiveActions = LLSD::emptyArray();
    LLSD                               mScrollResult;
    bool                               mGatheringInput = false;
    bool                               mCloseRequested = false;
};

LLSD describeView(LLView* view)
{ return view ? view->getInfo() : LLSD(); }
} // namespace

namespace xui_lab
{
class UIHost::Impl final
{
public:
    explicit Impl(const UIHostConfig& config) :
        mResourceRoot(std::filesystem::weakly_canonical(config.resource_root)),
        mArtifactDir(std::filesystem::weakly_canonical(std::filesystem::absolute(config.artifact_dir))),
        mWidth(config.pixel_width),
        mHeight(config.pixel_height),
        mUIScale(config.ui_scale),
        mInteractive(config.interactive)
    {
        if (!std::filesystem::is_directory(mResourceRoot / "skins") || !std::filesystem::is_directory(mResourceRoot / "app_settings"))
        {
            throw Error("resource_root", "resource root lacks production skins or app_settings");
        }
        if (mWidth <= 0 || mHeight <= 0 || mUIScale <= 0.0)
        {
            throw Error("viewport", "viewport values must be positive");
        }
        std::filesystem::create_directories(mArtifactDir);
        initializeUI();
        mInitialized = true;
    }

    ~Impl() { shutdown(); }

    void openSubject(Subject subject)
    {
        if (mSubject)
            throw Error("subject", "runtime subject may only be opened once");
        mSubject = subject;
        if (subject == Subject::TestWidgets)
        {
            LLFloaterReg::add("test_widgets", "floater_test_widgets.xml", &LLFloaterReg::build<LLFloater>);
        }
        else
        {
            LLFloaterReg::add("inventory_explorer", "floater_al_inventory_explorer.xml", &LLFloaterReg::build<ALFloaterInventoryExplorer>);
        }
        postEventApi("LLFloaterReg", LLSDMap("op", "showInstance")("name", std::string(subjectName(subject)))("focus", true));
        mFloater = LLFloaterReg::findInstance(std::string(subjectName(subject)));
        if (!mFloater)
        {
            throw Error("subject", "registered floater failed to instantiate: " + std::string(subjectName(subject)));
        }
        mFloater->center();
    }

    void initializeUI()
    {
        gDirUtilp->initAppDirs("AlchemyNext", mResourceRoot.string());
        gDirUtilp->setSkinFolder("default", "en");
        const auto app_settings = mResourceRoot / "app_settings";
        if (!gSavedSettings.loadFromFile((app_settings / "settings.xml").string(), true) ||
            !gSavedPerAccountSettings.loadFromFile((app_settings / "settings_per_account.xml").string(), true) ||
            !gWarningSettings.loadFromFile((app_settings / "ignorable_dialogs.xml").string(), true))
        {
            throw Error("settings", "failed to load production viewer settings");
        }
        if (!gSkinSettings.loadFromFile((mResourceRoot / "skins" / "default" / "skin_settings.xml").string(), true, false))
        {
            throw Error("settings", "failed to load production skin settings");
        }
        LLUIColorTable::instance().loadFromSettings();

        LLRender::sGLCoreProfile = true;
        mWindow                  = std::make_unique<LabWindow>(mWidth, mHeight, mInteractive);
        LLCoordWindow pixel_size;
        if (!mWindow->get()->getSize(&pixel_size))
            throw Error("window", "production LLWindow did not report its framebuffer size");
        mWidth  = pixel_size.mX;
        mHeight = pixel_size.mY;
        LLVertexBuffer::initClass(mWindow->get());
        if (!gGL.init(true))
            throw Error("render", "production LLRender failed to initialize");
        LLImageGL::initClass(mWindow->get(), LLGLTexture::MAX_GL_IMAGE_CATEGORY, true, false);

        mShaderMgr                         = std::make_unique<LabShaderMgr>(app_settings / "shaders" / "class");
        gUIProgram.mName                   = "xui-lab UI Shader";
        gUIProgram.mShaderFiles            = { { "interface/uiV.glsl", GL_VERTEX_SHADER }, { "interface/uiF.glsl", GL_FRAGMENT_SHADER } };
        gUIProgram.mShaderLevel            = 1;
        gUIProgram.mFeatures.attachNothing = true;
        gSolidColorProgram.mName           = "xui-lab Solid Color Shader";
        gSolidColorProgram.mShaderFiles    = { { "interface/solidcolorV.glsl", GL_VERTEX_SHADER },
                                               { "interface/solidcolorF.glsl", GL_FRAGMENT_SHADER } };
        gSolidColorProgram.mShaderLevel    = 1;
        gSolidColorProgram.mFeatures.attachNothing = true;
        if (!gUIProgram.createShader() || !gSolidColorProgram.createShader())
        {
            throw Error("shader", "failed to compile production LLUI shaders");
        }

        mImages = std::make_unique<LabImageProvider>();
        mImages->loadDeclarations();
        mImages->installWhiteTexture();
        LLUI::settings_map_t settings;
        settings["config"]  = &gSavedSettings;
        settings["ignores"] = &gWarningSettings;
        settings["floater"] = &gSavedSettings;
        settings["account"] = &gSavedPerAccountSettings;
        LLUI::createInstance(settings, mImages.get(), ignoreUISound, ignoreUISound);
        LLUI::getInstance()->mWindow = mWindow->get();
        mSystemUIScale               = mWindow->systemUIScale();
        LLUI::setScaleFactor(LLVector2(displayScale(), displayScale()));

        std::set<std::string> default_args;
        LLTransUtil::parseStrings("strings.xml", default_args);
        LLTransUtil::parseLanguageStrings("language_settings.xml");
        LLTranslationBridge::ptr_t translation = std::make_shared<LabTranslationBridge>();
        LLWearableType::initParamSingleton(translation);
        LLNotifications::instance();
        LLViewerEventRecorder::createInstance();
        LLFloater::initClass();
        LLInitClassList::instance().fireCallbacks();
        initialize_edit_menu();
        initialize_spellcheck_menu();

        LLFontManager::initClass();
        LLFontGL::initClass(gSavedSettings.getF32("FontScreenDPI"), displayScale(), displayScale(), gDirUtilp->getAppRODataDir(),
                            gSavedSettings.getLLSD("AlchemyUIFontOverrides"));
        LLFolderViewItem::initClass();

        const S32       virtual_width  = static_cast<S32>(ll_round(static_cast<F32>(mWidth) / displayScale()));
        const S32       virtual_height = static_cast<S32>(ll_round(static_cast<F32>(mHeight) / displayScale()));
        LLPanel::Params root_params;
        root_params.name("xui-lab-root");
        root_params.rect(LLRect(0, virtual_height, virtual_width, 0));
        root_params.follows.flags(FOLLOWS_ALL);
        mRoot = LLUICtrlFactory::create<LLPanel>(root_params);
        LLUI::getInstance()->setRootView(mRoot);
        mWindow->setRoot(mRoot);
        mWindowListener = std::make_unique<LLWindowListener>(mWindow.get(), []() { return gKeyboard; });

        LLFloaterView::Params floater_view_params;
        floater_view_params.name("Floater View");
        floater_view_params.rect(mRoot->getLocalRect());
        floater_view_params.mouse_opaque(false);
        floater_view_params.follows.flags(FOLLOWS_ALL);
        floater_view_params.tab_stop(false);
        gFloaterView = LLUICtrlFactory::create<LLFloaterView>(floater_view_params);
        mRoot->addChild(gFloaterView);

        LLViewerMenuHolderGL::Params menu_holder_params;
        menu_holder_params.name("Menu Holder");
        menu_holder_params.rect(mRoot->getLocalRect());
        menu_holder_params.follows.flags(FOLLOWS_ALL);
        menu_holder_params.mouse_opaque(false);
        gMenuHolder = LLUICtrlFactory::create<LLViewerMenuHolderGL>(menu_holder_params);
        mRoot->addChild(gMenuHolder);
        LLMenuGL::sMenuContainer = gMenuHolder;

        gSavedSettings.setBOOL("LocalFileSystemBrowsingEnabled", false);
        gSavedSettings.setBOOL("DisableExternalBrowser", true);
        installExternalEffectIntercepts();
    }

    void installExternalEffectIntercepts()
    {
        const auto record_url = [this](std::string_view channel, const std::string& url)
        {
            recordExternalEffect(LLSDMap("kind", "url")("channel", std::string(channel))("url", url)("result", "recorded"));
        };
        LLUrlAction::setOpenURLCallback([record_url](const std::string& url) { record_url("open", url); });
        LLUrlAction::setOpenURLInternalCallback([record_url](const std::string& url) { record_url("internal", url); });
        LLUrlAction::setOpenURLExternalCallback([record_url](const std::string& url) { record_url("external", url); });
        LLUrlAction::setExecuteSLURLCallback(
            [this](const std::string& url, bool trusted)
            {
                // HTTP(S) falls through to the open-URL callback.
                if (url.starts_with("http://") || url.starts_with("https://"))
                    return false;
                recordExternalEffect(LLSDMap("kind", "url")("channel", "slurl")("url", url)("trusted", trusted)("result", "recorded"));
                return true;
            });
    }

    void recordExternalEffect(LLSD effect) { mExternalEffects.append(std::move(effect)); }

    void renderFrame(bool swap, bool include_live_overlay = true)
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(16));
        LLFrameTimer::updateFrameTime();
        LLFrameTimer::updateFrameCount();
        LLSmoothInterpolation::updateInterpolants();
        ++mFrameCount;
        LLImageGL::updateClass();
        LLUIImage::updateClass();
        gIdleCallbacks.callFunctions();
        LLMortician::updateClass();
        LLAccordionCtrl::updateClass();
        LLLayoutStack::updateClass();
        mRoot->updateBoundingRect();

        glViewport(0, 0, mWidth, mHeight);
        glClearColor(0.f, 0.f, 0.f, 1.f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        gl_state_for_2d(mWidth, mHeight);
        LLGLSUIDefault ui_state;
        gUIProgram.bind();
        gGL.color4f(1.f, 1.f, 1.f, 1.f);
        LLView::sIsDrawing = true;
        gGL.pushMatrix();
        LLUI::pushMatrix();
        gGL.scaleUI(displayScale(), displayScale(), 1.f);
        mRoot->draw();
        LLUI::popMatrix();
        gGL.popMatrix();
        LLView::sIsDrawing = false;
        gUIProgram.unbind();
        gGL.flush();
        if (include_live_overlay && mInteractive && mHighlight)
            drawHighlight(mHighlight);
        if (swap)
            mWindow->get()->swapBuffers();
    }

    LLSD advanceFrames(S32 count)
    {
        if (count < 0)
            throw Error("frames", "frame count must not be negative");
        for (S32 index = 0; index < count; ++index)
            renderFrame(true);
        return LLSDMap("frames", count)("frameCount", mFrameCount);
    }

    LLSD resizeViewport(const LLSD& command)
    {
        const S32 width    = command["width"].asInteger();
        const S32 height   = command["height"].asInteger();
        const F64 ui_scale = command.has("uiScale") ? command["uiScale"].asReal() : mUIScale;
        if (width <= 0 || height <= 0 || ui_scale <= 0.0)
        {
            throw Error("viewport", "resize width, height, and uiScale must be positive");
        }

        mUIScale = ui_scale;
        if (!mWindow->get()->setSize(LLCoordScreen(width, height)))
            throw Error("viewport", "production window rejected the requested screen size");
        LLCoordScreen measured_window;
        if (!mWindow->get()->getSize(&measured_window) || measured_window.mX != width || measured_window.mY != height)
            throw Error("viewport", "production window did not reach the requested screen size");
        LLCoordWindow measured_pixels;
        if (!mWindow->get()->getSize(&measured_pixels))
            throw Error("viewport", "production window did not report its resized framebuffer");
        reshape(measured_pixels);
        renderFrame(true);
        return diagnostics()["viewport"];
    }

    LLSD resizeSubject(const LLSD& command)
    {
        if (!mFloater)
            throw Error("subject", "no subject floater is open");
        const S32 width  = command["width"].asInteger();
        const S32 height = command["height"].asInteger();
        if (width < mFloater->getMinWidth() || height < mFloater->getMinHeight())
        {
            throw Error("subject",
                        "subject size must be at least " + std::to_string(mFloater->getMinWidth()) + "x" +
                            std::to_string(mFloater->getMinHeight()));
        }
        mFloater->reshape(width, height);
        mFloater->center();
        renderFrame(true);
        return LLSDMap("width", mFloater->getRect().getWidth())("height", mFloater->getRect().getHeight())(
            "minWidth", mFloater->getMinWidth())("minHeight", mFloater->getMinHeight())("view", mFloater->getInfo());
    }

    void reshape(LLCoordWindow size)
    {
        mWidth         = size.mX;
        mHeight        = size.mY;
        mSystemUIScale = mWindow->systemUIScale();
        LLUI::setScaleFactor(LLVector2(displayScale(), displayScale()));
        mRoot->reshape(static_cast<S32>(ll_round(static_cast<F32>(mWidth) / displayScale())),
                       static_cast<S32>(ll_round(static_cast<F32>(mHeight) / displayScale())));
    }

    void pumpInteractive()
    {
        mWindow->gatherInput();
        if (const auto resized = mWindow->takeResize())
            reshape(LLCoordWindow(resized->first, resized->second));
        renderFrame(true);
    }

    LLSD reload()
    {
        const Subject current_subject = subject();
        mHighlight                    = nullptr;
        gFocusMgr.setKeyboardFocus(nullptr);
        postEventApi("LLFloaterReg", LLSDMap("op", "hideInstance")("name", std::string(subjectName(current_subject))));
        mFloater = nullptr;
        LLMortician::updateClass();
        postEventApi("LLFloaterReg", LLSDMap("op", "showInstance")("name", std::string(subjectName(current_subject)))("focus", true));
        mFloater = LLFloaterReg::findInstance(std::string(subjectName(current_subject)));
        if (!mFloater)
        {
            throw Error("subject", "registered floater failed to reload: " + std::string(subjectName(current_subject)));
        }
        mFloater->center();
        advanceFrames(2);
        return LLSDMap("subject", std::string(subjectName(current_subject)))("view", mFloater->getInfo());
    }

    [[nodiscard]] LLSD diagnostics() const
    {
        const Subject current_subject = subject();
        LLCoordWindow pixel_size(mWidth, mHeight);
        const bool    measured_window = mWindow->get()->getSize(&pixel_size);
        LLCoordScreen screen_size;
        const bool    measured_screen = mWindow->get()->getSize(&screen_size);
        const LLRect  llui_rect       = mRoot->getRect();
        LLSD          graphics;
        gGLManager.asLLSD(graphics);
        const LLSD overlay =
            LLSDMap("visible", mInteractive && mHighlight != nullptr)("path", mHighlight ? mHighlight->getPathname() : std::string());
        return LLSDMap("focus", describeView(dynamic_cast<LLView*>(gFocusMgr.getKeyboardFocus())))(
            "mouseCapture", describeView(dynamic_cast<LLView*>(gFocusMgr.getMouseCapture())))(
            "visibleMenu", describeView(gMenuHolder ? gMenuHolder->getVisibleMenu() : nullptr))(
            "subject", LLSDMap("id", std::string(subjectName(current_subject)))("view", describeView(mFloater)))(
            "window", LLSDMap("interactive", mInteractive)("visible", mWindow->get()->getVisible()))(
            "viewport", LLSDMap("pixelWidth", pixel_size.mX)("pixelHeight", pixel_size.mY)("windowMeasured", measured_window)(
                            "windowWidth", screen_size.mX)("windowHeight", screen_size.mY)("screenMeasured", measured_screen)(
                            "lluiWidth", llui_rect.getWidth())("lluiHeight", llui_rect.getHeight())("uiScale", mUIScale)(
                            "systemUIScale", mSystemUIScale)("effectiveUIScale", displayScale()))("graphics", graphics)("overlay", overlay)(
            "recording", mRecordedActions)("effects", mExternalEffects)("httpService", false);
    }

    LLRect drawHighlight(LLView* target)
    {
        LLRect rect;
        LLUI::getInstance()->screenRectToGL(target->calcScreenRect(), &rect);
        gSolidColorProgram.bind();
        gGL.getTextureSlot(0)->unbind();
        gGL.color4f(1.f, 0.2f, 0.1f, 1.f);
        gGL.begin(LLRender::LINES);
        gGL.vertex2i(rect.mLeft, rect.mBottom);
        gGL.vertex2i(rect.mRight, rect.mBottom);
        gGL.vertex2i(rect.mRight, rect.mBottom);
        gGL.vertex2i(rect.mRight, rect.mTop);
        gGL.vertex2i(rect.mRight, rect.mTop);
        gGL.vertex2i(rect.mLeft, rect.mTop);
        gGL.vertex2i(rect.mLeft, rect.mTop);
        gGL.vertex2i(rect.mLeft, rect.mBottom);
        gGL.end();
        gGL.flush();
        gSolidColorProgram.unbind();
        return rect;
    }

    LLSD capture(const LLSD& command, LLView* highlighted, std::string_view fixture_id)
    {
        const Subject         current_subject = subject();
        std::filesystem::path path;
        if (command.has("path"))
        {
            if (!command["path"].isString() || command["path"].asString().empty())
            {
                throw Error("capture_path", "capture path must be a non-empty string");
            }
            const std::string           value = command["path"].asString();
            const std::filesystem::path relative_path(value);
            std::string                 portable_value = value;
            std::ranges::replace(portable_value, '\\', '/');
            const std::filesystem::path portable_path(portable_value);
            if (relative_path.is_absolute() || (!value.empty() && (value.front() == '/' || value.front() == '\\')) ||
                (value.size() >= 2 && std::isalpha(static_cast<unsigned char>(value.front())) && value[1] == ':') ||
                std::ranges::any_of(portable_path, [](const auto& part) { return part == ".."; }))
            {
                throw Error("capture_path", "capture path must stay beneath the scenario artifact directory");
            }
            path                                       = std::filesystem::weakly_canonical(mArtifactDir / relative_path);
            const std::filesystem::path contained_path = path.lexically_relative(mArtifactDir);
            if (contained_path.empty() || *contained_path.begin() == "..")
            {
                throw Error("capture_path", "capture path must stay beneath the scenario artifact directory");
            }
        }
        else
        {
            std::string name = command["name"].asString();
            if (name.empty())
                name = "frame";
            if (name == "." || name == ".." || name.find_first_of("/\\:") != std::string::npos)
            {
                throw Error("capture_name", "capture name must not create subdirectories");
            }
            path = mArtifactDir / (name + ".png");
        }
        std::filesystem::create_directories(path.parent_path());

        renderFrame(false, false);
        std::string           highlighted_path;
        std::optional<LLRect> highlighted_rect;
        if (highlighted)
        {
            highlighted_path = highlighted->getPathname();
            highlighted_rect = drawHighlight(highlighted);
        }
        LLPointer<LLImageRaw> raw = new LLImageRaw(mWidth, mHeight, 4);
        glReadPixels(0, 0, mWidth, mHeight, GL_RGBA, GL_UNSIGNED_BYTE, raw->getData());
        LLPointer<LLImagePNG> png = new LLImagePNG();
        if (!png->encode(raw, 0.f) || !png->save(path.string()))
        {
            throw Error("capture", "failed to save the rendered frame");
        }
        mWindow->get()->swapBuffers();

        const LLSD live_overlay =
            LLSDMap("visible", mInteractive && mHighlight != nullptr)("path", mHighlight ? mHighlight->getPathname() : std::string());
        LLCoordScreen screen_size;
        const bool    measured_screen = mWindow->get()->getSize(&screen_size);
        LLSD          overlay_metadata =
            LLSDMap("included", highlighted != nullptr)("highlightedPath", highlighted_path)("interactiveState", live_overlay);
        if (highlighted_rect)
            overlay_metadata["framebufferRect"] = rectToLLSD(*highlighted_rect);
        LLSD graphics;
        gGLManager.asLLSD(graphics);
        LLSD metadata = LLSDMap("schemaVersion", 1)("fork", std::string(kFork))("forkCommit", std::string(kForkCommit))(
            "subject", std::string(subjectName(current_subject)))("fixture", std::string(fixture_id))(
            "viewport", LLSDMap("width", mWidth)("height", mHeight)("uiScale", mUIScale)("systemUIScale", mSystemUIScale)(
                            "effectiveUIScale", displayScale())("windowWidth", screen_size.mX)("windowHeight", screen_size.mY)(
                            "screenMeasured", measured_screen))("overlay", overlay_metadata)("graphics", graphics);
        if (command.has("step") && command["step"].isString() && !command["step"].asString().empty())
            metadata["scenarioStep"] = command["step"].asString();
        if (command.has("action") && command["action"].isString() && !command["action"].asString().empty())
            metadata["action"] = command["action"].asString();
        if (command.has("sequence") && command["sequence"].isInteger())
            metadata["sequence"] = command["sequence"].asInteger();
        std::ofstream sidecar(path.string() + ".json");
        sidecar << LlsdToJson(metadata) << '\n';
        return LLSDMap("path", path.string())("metadata", metadata)("highlightedPath", highlighted_path);
    }

    void shutdown()
    {
        if (!mInitialized)
            return;
        if (mSubject)
        {
            try
            {
                postEventApi("LLFloaterReg", LLSDMap("op", "hideInstance")("name", std::string(subjectName(mSubject.value()))));
            }
            catch (const std::exception& error)
            {
                std::fputs("xui-lab: subject hide failed during shutdown: ", stderr);
                std::fputs(error.what(), stderr);
                std::fputc('\n', stderr);
            }
            catch (...)
            {
                std::fputs("xui-lab: unknown subject hide failure during shutdown\n", stderr);
            }
        }
        mWindowListener.reset();
        LLUI::getInstance()->setRootView(nullptr);
        delete mRoot;
        mRoot                    = nullptr;
        mFloater                 = nullptr;
        gFloaterView             = nullptr;
        gMenuHolder              = nullptr;
        LLMenuGL::sMenuContainer = nullptr;
        LLFolderViewItem::cleanupClass();
        LLFontGL::destroyAllGL();
        mImages->cleanUp();
        LLUI::deleteSingleton();
        LLViewerEventRecorder::deleteSingleton();
        gSolidColorProgram.unload();
        gUIProgram.unload();
        LLImageGL::cleanupClass();
        LLVertexBuffer::cleanupClass();
        gGL.shutdown();
        mShaderMgr.reset();
        mWindow.reset();
        mImages.reset();
        mInitialized = false;
    }

    [[nodiscard]] Subject subject() const
    {
        if (!mSubject)
            throw Error("subject", "runtime subject is not open");
        return mSubject.value();
    }

    [[nodiscard]] F32 displayScale() const { return static_cast<F32>(mUIScale * mSystemUIScale); }

    [[nodiscard]] bool closeRequested() const noexcept { return mWindow->closeRequested(); }

    [[nodiscard]] std::optional<std::pair<S32, S32>> takePointerMove() { return mWindow->takePointerMove(); }

    [[nodiscard]] LLSD takeInteractiveActions() { return mWindow->takeInteractiveActions(); }

    [[nodiscard]] LLSD takeScrollResult() { return mWindow->takeScrollResult(); }

    void setHighlight(LLView* target) noexcept { mHighlight = target; }

    LLSD inputKey(std::string_view requested_key, const LLSD& modifiers)
    {
        KEY key = KEY_NONE;
        if (!LLKeyboard::keyFromString(std::string(requested_key), &key))
            throw Error("input", "unknown keyboard key: " + std::string(requested_key));
        MASK mask = MASK_NONE;
        for (const LLSD& modifier : llsd::inArray(modifiers))
        {
            const std::string name = modifier.asString();
            if (name == "shift")
                mask |= MASK_SHIFT;
            else if (name == "control")
                mask |= MASK_CONTROL;
            else if (name == "alt")
                mask |= MASK_ALT;
            else
                throw Error("input", "unknown keyboard modifier: " + name);
        }
        bool handled = mWindow->sendKey(key, mask);
        if (key == KEY_RETURN)
            handled = mWindow->sendUnicode('\r') || handled;
        return LLSDMap("handled", handled)("key", std::string(requested_key))("modifiers", modifiers);
    }

    LLSD inputText(std::string_view text, bool replace)
    {
        bool handled = false;
        if (replace)
        {
            handled = mWindow->sendKey('A', MASK_CONTROL) || handled;
            handled = mWindow->sendKey(KEY_BACKSPACE, MASK_NONE) || handled;
        }
        for (const llwchar character : utf8str_to_wstring(std::string(text)))
            handled = mWindow->sendUnicode(character) || handled;
        return LLSDMap("handled", handled)("text", std::string(text))("replace", replace);
    }

    void recordAction(LLSD action)
    {
        if (mRecordedActions.isUndefined())
            mRecordedActions = LLSD::emptyArray();
        mRecordedActions.append(std::move(action));
    }

    [[nodiscard]] const LLSD& recordedActions() const noexcept { return mRecordedActions; }

    [[nodiscard]] LLSD externalEffects() const { return mExternalEffects; }

    std::unique_ptr<LabWindow>        mWindow;
    std::unique_ptr<LLWindowListener> mWindowListener;
    std::unique_ptr<LabShaderMgr>     mShaderMgr;
    std::unique_ptr<LabImageProvider> mImages;
    LLPanel*                          mRoot    = nullptr;
    LLFloater*                        mFloater = nullptr;
    std::filesystem::path             mResourceRoot;
    std::filesystem::path             mArtifactDir;
    S32                               mWidth;
    S32                               mHeight;
    S32                               mFrameCount = 0;
    F64                               mUIScale;
    F32                               mSystemUIScale = 1.f;
    bool                              mInitialized   = false;
    bool                              mInteractive   = false;
    std::optional<Subject>            mSubject;
    LLView*                           mHighlight       = nullptr;
    LLSD                              mRecordedActions = LLSD::emptyArray();
    LLSD                              mExternalEffects = LLSD::emptyArray();
};

UIHost::UIHost(const UIHostConfig& config) : mImpl(std::make_unique<Impl>(config))
{
}

UIHost::~UIHost() = default;

void UIHost::openSubject(Subject subject)
{ mImpl->openSubject(subject); }
LLSD UIHost::advanceFrames(S32 count)
{ return mImpl->advanceFrames(count); }
void UIHost::renderFrame(bool swap)
{ mImpl->renderFrame(swap); }
LLSD UIHost::resizeViewport(const LLSD& command)
{ return mImpl->resizeViewport(command); }

LLSD UIHost::resizeSubject(const LLSD& command)
{ return mImpl->resizeSubject(command); }
LLSD UIHost::reload()
{ return mImpl->reload(); }
LLSD UIHost::diagnostics() const
{ return mImpl->diagnostics(); }
LLSD UIHost::capture(const LLSD& command, LLView* highlighted, std::string_view fixture_id)
{ return mImpl->capture(command, highlighted, fixture_id); }
void UIHost::pumpInteractive()
{ mImpl->pumpInteractive(); }
bool UIHost::closeRequested() const noexcept
{ return mImpl->closeRequested(); }
std::optional<std::pair<S32, S32>> UIHost::takePointerMove()
{ return mImpl->takePointerMove(); }
LLSD UIHost::takeInteractiveActions()
{ return mImpl->takeInteractiveActions(); }
LLSD UIHost::takeScrollResult()
{ return mImpl->takeScrollResult(); }
void UIHost::setHighlight(LLView* target) noexcept
{ mImpl->setHighlight(target); }
LLSD UIHost::inputKey(std::string_view key, const LLSD& modifiers)
{ return mImpl->inputKey(key, modifiers); }
LLSD UIHost::inputText(std::string_view text, bool replace)
{ return mImpl->inputText(text, replace); }
void UIHost::recordAction(LLSD action)
{ mImpl->recordAction(std::move(action)); }
const LLSD& UIHost::recordedActions() const noexcept
{ return mImpl->recordedActions(); }
LLSD UIHost::externalEffects() const
{ return mImpl->externalEffects(); }
LLPanel* UIHost::root() const noexcept
{ return mImpl->mRoot; }
LLFloater* UIHost::floater() const noexcept
{ return mImpl->mFloater; }
} // namespace xui_lab
