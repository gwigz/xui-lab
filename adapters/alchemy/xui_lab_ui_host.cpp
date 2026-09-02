#include "llviewerprecompiledheaders.h"

#include "xui_lab_ui_host.h"

#include "xui_lab_error.h"
#include "xui_lab_event_api.h"

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
#include "llmenugl.h"
#include "llmortician.h"
#include "llnotifications.h"
#include "llpanel.h"
#include "llrender.h"
#include "llrender2dutils.h"
#include "llsdjson.h"
#include "llshadermgr.h"
#include "lltrans.h"
#include "lltransutil.h"
#include "llui.h"
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
constexpr std::string_view kFork       = XUI_LAB_FORK;
constexpr std::string_view kForkCommit = XUI_LAB_FORK_COMMIT;

void ignoreUISound(const LLUUID&)
{
}

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

    void cleanUp() override
    {
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
    LabWindow(S32 width, S32 height)
    {
        mWindow = LLWindowManager::createWindow(this, "xui-lab", "xui-lab", 0, 0, width, height, LLWindow::WINDOW_FLAG_HIDDEN, false, true,
                                                false, true, false);
        if (!mWindow)
            throw xui_lab::Error("window", "failed to create the hidden production LLWindow");
    }

    ~LabWindow() override
    {
        if (mWindow)
            LLWindowManager::destroyWindow(mWindow);
    }

    [[nodiscard]] LLWindow* get() const noexcept { return mWindow; }
    void                    setRoot(LLView* root) noexcept { mRoot = root; }

    bool handleMouseDown(LLWindow*, LLCoordGL position, MASK mask) override
    {
        setMousePosition(position);
        return mRoot->handleMouseDown(position.mX, position.mY, mask);
    }

    bool handleMouseUp(LLWindow*, LLCoordGL position, MASK mask) override
    {
        setMousePosition(position);
        return mRoot->handleMouseUp(position.mX, position.mY, mask);
    }

    bool handleRightMouseDown(LLWindow*, LLCoordGL position, MASK mask) override
    {
        setMousePosition(position);
        return mRoot->handleRightMouseDown(position.mX, position.mY, mask);
    }

    bool handleRightMouseUp(LLWindow*, LLCoordGL position, MASK mask) override
    {
        setMousePosition(position);
        return mRoot->handleRightMouseUp(position.mX, position.mY, mask);
    }

    bool handleMiddleMouseDown(LLWindow*, LLCoordGL position, MASK mask) override
    {
        setMousePosition(position);
        return mRoot->handleMiddleMouseDown(position.mX, position.mY, mask);
    }

    bool handleMiddleMouseUp(LLWindow*, LLCoordGL position, MASK mask) override
    {
        setMousePosition(position);
        return mRoot->handleMiddleMouseUp(position.mX, position.mY, mask);
    }

    bool handleDoubleClick(LLWindow*, LLCoordGL position, MASK mask) override
    {
        setMousePosition(position);
        return mRoot->handleDoubleClick(position.mX, position.mY, mask);
    }

    void handleMouseMove(LLWindow*, LLCoordGL position, MASK mask) override
    {
        setMousePosition(position);
        mRoot->handleHover(position.mX, position.mY, mask);
    }

private:
    void setMousePosition(LLCoordGL position) { LLUI::getInstance()->setMousePositionScreen(position.mX, position.mY); }

    LLWindow* mWindow = nullptr;
    LLView*   mRoot   = nullptr;
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
        mUIScale(config.ui_scale)
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
        mWindow                  = std::make_unique<LabWindow>(mWidth, mHeight);
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
        LLUI::settings_map_t settings;
        settings["config"]  = &gSavedSettings;
        settings["ignores"] = &gWarningSettings;
        settings["floater"] = &gSavedSettings;
        settings["account"] = &gSavedPerAccountSettings;
        LLUI::createInstance(settings, mImages.get(), ignoreUISound, ignoreUISound);
        LLUI::getInstance()->mWindow = mWindow->get();
        LLUI::setScaleFactor(LLVector2(static_cast<F32>(mUIScale), static_cast<F32>(mUIScale)));

        std::set<std::string> default_args;
        LLTransUtil::parseStrings("strings.xml", default_args);
        LLTransUtil::parseLanguageStrings("language_settings.xml");
        LLTranslationBridge::ptr_t translation = std::make_shared<LabTranslationBridge>();
        LLWearableType::initParamSingleton(translation);
        LLNotifications::instance();
        LLViewerEventRecorder::createInstance();
        LLFloater::initClass();
        LLInitClassList::instance().fireCallbacks();

        LLFontManager::initClass();
        LLFontGL::initClass(gSavedSettings.getF32("FontScreenDPI"), static_cast<F32>(mUIScale), static_cast<F32>(mUIScale),
                            gDirUtilp->getAppRODataDir(), gSavedSettings.getLLSD("AlchemyUIFontOverrides"));
        LLFolderViewItem::initClass();

        const S32       virtual_width  = static_cast<S32>(ll_round(mWidth / mUIScale));
        const S32       virtual_height = static_cast<S32>(ll_round(mHeight / mUIScale));
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
    }

    void renderFrame(bool swap)
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
        glClearColor(0.12f, 0.12f, 0.12f, 1.f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        gl_state_for_2d(mWidth, mHeight);
        LLGLSUIDefault ui_state;
        gUIProgram.bind();
        gGL.color4f(1.f, 1.f, 1.f, 1.f);
        LLView::sIsDrawing = true;
        gGL.pushMatrix();
        LLUI::pushMatrix();
        gGL.scaleUI(static_cast<F32>(mUIScale), static_cast<F32>(mUIScale), 1.f);
        mRoot->draw();
        LLUI::popMatrix();
        gGL.popMatrix();
        LLView::sIsDrawing = false;
        gUIProgram.unbind();
        gGL.flush();
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

    LLSD resize(const LLSD& command)
    {
        const S32 width    = command["width"].asInteger();
        const S32 height   = command["height"].asInteger();
        const F64 ui_scale = command.has("uiScale") ? command["uiScale"].asReal() : mUIScale;
        if (width <= 0 || height <= 0 || ui_scale <= 0.0)
        {
            throw Error("viewport", "resize width, height, and uiScale must be positive");
        }

        mWidth   = width;
        mHeight  = height;
        mUIScale = ui_scale;
        LLUI::setScaleFactor(LLVector2(static_cast<F32>(mUIScale), static_cast<F32>(mUIScale)));
        mWindow->get()->setSize(LLCoordWindow(mWidth, mHeight));
        mRoot->reshape(static_cast<S32>(ll_round(mWidth / mUIScale)), static_cast<S32>(ll_round(mHeight / mUIScale)));
        renderFrame(true);
        return diagnostics()["viewport"];
    }

    LLSD reload()
    {
        const Subject current_subject = subject();
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
        const LLRect  llui_rect       = mRoot->getRect();
        LLSD          graphics;
        gGLManager.asLLSD(graphics);
        return LLSDMap("focus", describeView(dynamic_cast<LLView*>(gFocusMgr.getKeyboardFocus())))(
            "mouseCapture", describeView(dynamic_cast<LLView*>(gFocusMgr.getMouseCapture())))(
            "visibleMenu", describeView(gMenuHolder ? gMenuHolder->getVisibleMenu() : nullptr))(
            "subject", LLSDMap("id", std::string(subjectName(current_subject)))("view", describeView(mFloater)))(
            "viewport", LLSDMap("pixelWidth", pixel_size.mX)("pixelHeight", pixel_size.mY)("windowMeasured", measured_window)(
                            "lluiWidth", llui_rect.getWidth())("lluiHeight", llui_rect.getHeight())("uiScale", mUIScale))("graphics",
                                                                                                                          graphics);
    }

    void drawHighlight(LLView* target)
    {
        const LLRect rect = target->calcScreenRect();
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

        renderFrame(false);
        std::string highlighted_path;
        if (highlighted)
        {
            highlighted_path = highlighted->getPathname();
            drawHighlight(highlighted);
        }
        LLPointer<LLImageRaw> raw = new LLImageRaw(mWidth, mHeight, 4);
        glReadPixels(0, 0, mWidth, mHeight, GL_RGBA, GL_UNSIGNED_BYTE, raw->getData());
        LLPointer<LLImagePNG> png = new LLImagePNG();
        if (!png->encode(raw, 0.f) || !png->save(path.string()))
        {
            throw Error("capture", "failed to save the rendered frame");
        }
        mWindow->get()->swapBuffers();

        const LLSD metadata = LLSDMap("fork", std::string(kFork))("forkCommit", std::string(kForkCommit))(
            "subject", std::string(subjectName(current_subject)))("fixture", std::string(fixture_id))(
            "viewport", LLSDMap("width", mWidth)("height", mHeight)("uiScale", mUIScale));
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
    bool                              mInitialized = false;
    std::optional<Subject>            mSubject;
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
LLSD UIHost::resize(const LLSD& command)
{ return mImpl->resize(command); }
LLSD UIHost::reload()
{ return mImpl->reload(); }
LLSD UIHost::diagnostics() const
{ return mImpl->diagnostics(); }
LLSD UIHost::capture(const LLSD& command, LLView* highlighted, std::string_view fixture_id)
{ return mImpl->capture(command, highlighted, fixture_id); }
LLPanel* UIHost::root() const noexcept
{ return mImpl->mRoot; }
LLFloater* UIHost::floater() const noexcept
{ return mImpl->mFloater; }
} // namespace xui_lab
