#include "llviewerprecompiledheaders.h"

#include "llaccordionctrl.h"
#include "alfloaterinventoryexplorer.h"
#include "llagentdata.h"
#include "llavatarname.h"
#include "llavatarnamecache.h"
#include "llcallbacklist.h"
#include "llcontrol.h"
#include "llcriticaldamp.h"
#include "lldir.h"
#include "llerrorcontrol.h"
#include "lleventapi.h"
#include "llevents.h"
#include "llfloater.h"
#include "llfloaterreg.h"
#include "llfontfreetype.h"
#include "llfontgl.h"
#include "llfolderviewitem.h"
#include "llfolderviewmodelinventory.h"
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
#include "llinventorymodel.h"
#include "llinventoryobserver.h"
#include "llinventorypanel.h"
#include "llkeyboard.h"
#include "lllayoutstack.h"
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
#include "lluictrl.h"
#include "lluictrlfactory.h"
#include "lluicolortable.h"
#include "lluiimage.h"
#include "llvertexbuffer.h"
#include "llview.h"
#include "llviewereventrecorder.h"
#include "llviewercontrol.h"
#include "llviewerfoldertype.h"
#include "llviewerinventory.h"
#include "llviewermenu.h"
#include "llwearabletype.h"
#include "llwindow.h"
#include "llwindowcallbacks.h"
#include "llwindowlistener.h"
#include "llxmlnode.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <utility>
#include <vector>

void ignoreUISound(const LLUUID&)
{
}

class XUILabInventoryFixtureLoader final
{
public:
    static void addCategory(LLInventoryModel& inventory, LLViewerInventoryCategory* category)
    {
        inventory.addCategory(category);
    }

    static void addItem(LLInventoryModel& inventory, LLViewerInventoryItem* item)
    {
        inventory.addItem(item);
    }

    static LLSD validate(const LLInventoryModel& inventory)
    {
        LLSD result;
        inventory.validate()->asLLSD(result);
        return result;
    }
};

namespace
{
constexpr std::string_view kFork = XUI_LAB_FORK;
constexpr std::string_view kForkCommit = XUI_LAB_FORK_COMMIT;

class LabError final : public std::runtime_error
{
public:
    LabError(std::string code, std::string message)
        : std::runtime_error(std::move(message)), mCode(std::move(code))
    {
    }

    const std::string& code() const noexcept { return mCode; }

private:
    std::string mCode;
};

class LabTranslationBridge final : public LLTranslationBridge
{
public:
    std::string getString(const std::string& xml_desc) override
    {
        return LLTrans::getString(xml_desc);
    }
};

class LabShaderMgr final : public LLShaderMgr
{
public:
    explicit LabShaderMgr(std::filesystem::path shader_root)
        : mShaderRoot(std::move(shader_root))
    {
        sInstance = this;
        initAttribsAndUniforms();
    }

    ~LabShaderMgr() override { sInstance = nullptr; }

    std::string getShaderDirPrefix() override
    {
        return mShaderRoot.string();
    }

    void updateShaderUniforms(LLGLSLShader*) override
    {
    }

private:
    std::filesystem::path mShaderRoot;
};

struct ImageDeclaration
{
    std::string filename;
    LLRect scale = LLRect::null;
    LLRect clip = LLRect::null;
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
            throw LabError("textures", "production textures.xml was not found");
        }

        for (const std::string& path : paths)
        {
            LLXMLNodePtr root;
            if (!LLXMLNode::parseFile(path, root, nullptr))
            {
                throw LabError("textures", "failed to parse " + path);
            }
            for (LLXMLNodePtr node = root->getFirstChild(); node.notNull(); node = node->getNextSibling())
            {
                if (!node->hasName("texture")) continue;
                std::string name;
                if (!node->getAttributeString("name", name) || name.empty()) continue;

                ImageDeclaration declaration;
                if (!node->getAttributeString("file_name", declaration.filename)) declaration.filename = name;
                S32 left = 0;
                S32 top = 0;
                S32 right = 0;
                S32 bottom = 0;
                if (node->getAttributeS32("scale.left", left) &&
                    node->getAttributeS32("scale.top", top) &&
                    node->getAttributeS32("scale.right", right) &&
                    node->getAttributeS32("scale.bottom", bottom))
                {
                    declaration.scale.set(left, top, right, bottom);
                }
                if (node->getAttributeS32("clip.left", left) &&
                    node->getAttributeS32("clip.top", top) &&
                    node->getAttributeS32("clip.right", right) &&
                    node->getAttributeS32("clip.bottom", bottom))
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
        if (const auto found = mImages.find(name); found != mImages.end()) return found->second;

        ImageDeclaration declaration;
        if (const auto found = mDeclarations.find(name); found != mDeclarations.end()) declaration = found->second;
        else declaration.filename = name;

        const std::string path = gDirUtilp->findSkinnedFilename(LLDir::TEXTURES, declaration.filename);
        if (path.empty()) throw LabError("texture", "production UI texture not found: " + name);

        LLPointer<LLImageFormatted> formatted = LLImageFormatted::createFromExtension(path);
        LLPointer<LLImageRaw> raw = new LLImageRaw();
        if (formatted.isNull() || !formatted->load(path) || !formatted->decode(raw, 0.f))
        {
            throw LabError("texture", "failed to decode production UI texture: " + path);
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
    {
        throw LabError("texture_id", "network texture UUID is unavailable in xui-lab: " + id.asString());
    }

    void cleanUp() override
    {
        LLUIImage::cleanupClass();
        mImages.clear();
    }

private:
    static LLRectf normalize(const LLRect& rect, S32 width, S32 height)
    {
        return LLRectf(
            llclamp(static_cast<F32>(rect.mLeft) / width, 0.f, 1.f),
            llclamp(static_cast<F32>(rect.mTop) / height, 0.f, 1.f),
            llclamp(static_cast<F32>(rect.mRight) / width, 0.f, 1.f),
            llclamp(static_cast<F32>(rect.mBottom) / height, 0.f, 1.f));
    }

    std::map<std::string, ImageDeclaration, std::less<>> mDeclarations;
    std::map<std::string, LLPointer<LLUIImage>, std::less<>> mImages;
};

class LabWindow final : public LLWindowCallbacks
{
public:
    LabWindow(S32 width, S32 height)
    {
        mWindow = LLWindowManager::createWindow(
            this, "xui-lab", "xui-lab", 0, 0, width, height, LLWindow::WINDOW_FLAG_HIDDEN,
            false, true, false, true, false);
        if (!mWindow) throw LabError("window", "failed to create the hidden production LLWindow");
    }

    ~LabWindow() override
    {
        if (mWindow) LLWindowManager::destroyWindow(mWindow);
    }

    LLWindow* get() const noexcept { return mWindow; }

    void setRoot(LLView* root) noexcept { mRoot = root; }

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
    void setMousePosition(LLCoordGL position)
    {
        LLUI::getInstance()->setMousePositionScreen(position.mX, position.mY);
    }

    LLWindow* mWindow = nullptr;
    LLView* mRoot = nullptr;
};

void addFolderState(LLSD& node, LLFolderViewItem* item)
{
    node["label"] = wstring_to_utf8str(item->getLabel());
    node["selected"] = item->isSelected();
    node["open"] = item->isOpen();
    if (auto* model_item = dynamic_cast<LLFolderViewModelItemInventory*>(item->getViewModelItem()))
    {
        node["model_id"] = model_item->getUUID();
    }
}

LLSD buildFolderTree(LLFolderViewItem* item, const std::string& parent_path)
{
    LLSD node = item->getInfo();
    addFolderState(node, item);
    const std::string segment = node.has("model_id")
        ? "@" + node["model_id"].asString()
        : item->getName();
    node["path"] = parent_path + "/" + segment;

    LLSD children = LLSD::emptyArray();
    S32 hit_order = 0;
    if (auto* folder = dynamic_cast<LLFolderViewFolder*>(item))
    {
        for (auto iterator = folder->getFoldersBegin(); iterator != folder->getFoldersEnd(); ++iterator)
        {
            LLSD child = buildFolderTree(*iterator, node["path"].asString());
            child["hit_test_order"] = hit_order++;
            children.append(child);
        }
        for (auto iterator = folder->getItemsBegin(); iterator != folder->getItemsEnd(); ++iterator)
        {
            LLSD child = buildFolderTree(*iterator, node["path"].asString());
            child["hit_test_order"] = hit_order++;
            children.append(child);
        }
    }
    node["children"] = children;
    return node;
}

LLSD buildTree(LLView* view)
{
    LLSD node = view->getInfo();
    if (auto* control = dynamic_cast<LLUICtrl*>(view)) node["value"] = control->getValue();
    if (auto* menu_item = dynamic_cast<LLMenuItemGL*>(view)) node["label"] = menu_item->getLabel();
    if (auto* folder_item = dynamic_cast<LLFolderViewItem*>(view))
    {
        addFolderState(node, folder_item);
    }
    LLSD children = LLSD::emptyArray();
    S32 hit_order = 0;
    if (auto* folder = dynamic_cast<LLFolderViewFolder*>(view))
    {
        for (auto iterator = folder->getFoldersBegin(); iterator != folder->getFoldersEnd(); ++iterator)
        {
            LLSD child_node = buildFolderTree(*iterator, node["path"].asString());
            child_node["hit_test_order"] = hit_order++;
            children.append(child_node);
        }
        for (auto iterator = folder->getItemsBegin(); iterator != folder->getItemsEnd(); ++iterator)
        {
            LLSD child_node = buildFolderTree(*iterator, node["path"].asString());
            child_node["hit_test_order"] = hit_order++;
            children.append(child_node);
        }
    }
    else
    {
        for (auto* child : *view->getChildList())
        {
            LLSD child_node = buildTree(child);
            child_node["hit_test_order"] = hit_order++;
            children.append(child_node);
        }
    }
    node["children"] = children;
    return node;
}

LLSD callEventApi(std::string_view api_name, const LLSD& command)
{
    LLEventStream reply_pump("xui-lab-event-reply", true);
    LLSD reply;
    bool received = false;
    LLTempBoundListener connection = reply_pump.listen(
        "capture", [&reply, &received](const LLSD& event)
        {
            reply = event;
            received = true;
            return true;
        });

    LLSD request = command;
    request["reply"] = reply_pump.getName();
    LLEventPumps::instance().obtain(std::string(api_name)).post(request);
    if (!received)
    {
        throw LabError("event_api", "event API did not reply: " + std::string(api_name));
    }
    if (reply["error"].isDefined())
    {
        throw LabError("event_api", reply["error"].asString());
    }
    return reply;
}

void postEventApi(std::string_view api_name, const LLSD& command)
{
    LLEventPumps::instance().obtain(std::string(api_name)).post(command);
}

class Runtime final : public LLEventAPI
{
public:
    Runtime()
        : LLEventAPI("XUILab", "Lifecycle operations for the standalone production UI host")
    {
        add("initialize", "Initialize the selected fork, resources, window, and subject.",
            &Runtime::initialize);
        add("installCapabilities", "Install the capabilities requested by the scenario.",
            &Runtime::installCapabilities);
        add("frames", "Advance an exact number of UI frames.",
            [this](const LLSD& command) { requireInitialized(); return advanceFrames(command["count"].asInteger()); });
        add("stable", "Advance frames until the production UI tree stops changing.",
            &Runtime::stabilize);
        add("resize", "Resize the host viewport and production LLUI root.",
            &Runtime::resize);
        add("capture", "Capture the production UI framebuffer.",
            &Runtime::capture);
        add("reload", "Destroy and recreate the registered subject from source XUI.",
            &Runtime::reload);
        add("diagnostics", "Report runtime, subject, viewport, focus, and graphics state.",
            [this](const LLSD&) { requireInitialized(); return diagnostics(); });
        add("shutdown", "Acknowledge shutdown so the parent can collect the process.",
            &Runtime::requestShutdown);
        add("query", "Translate high-level inspection requests to production event APIs.",
            &Runtime::query);
        add("input", "Translate high-level input requests to the production LLWindow event API.",
            &Runtime::input);
    }

    ~Runtime() override { shutdown(); }

    bool done() const noexcept { return mDone; }

private:
    enum class Subject
    {
        TestWidgets,
        InventoryExplorer
    };

    static Subject parseSubject(const LLSD& value)
    {
        if (!value.isString()) throw LabError("subject", "subject must be a string");
        if (value.asString() == "test_widgets") return Subject::TestWidgets;
        if (value.asString() == "inventory_explorer") return Subject::InventoryExplorer;
        throw LabError("subject", "unsupported registered subject: " + value.asString());
    }

    [[nodiscard]] std::string_view subjectName() const noexcept
    {
        switch (mSubject)
        {
            case Subject::TestWidgets: return "test_widgets";
            case Subject::InventoryExplorer: return "inventory_explorer";
        }
    }

    static constexpr std::array<std::string_view, 7> inventoryPanelNames()
    {
        return {
            "all_items_tree", "all_items_list", "recent_collection_view", "worn_collection_view",
            "favorites_collection_view", "type_filter_collection_view", "all_items_grid"
        };
    }

    static std::string requireString(const LLSD& object, const std::string& key, const std::string& label)
    {
        if (!object.isMap() || !object[key].isString() || object[key].asString().empty())
        {
            throw LabError("fixture", label + "." + key + " must be a non-empty string");
        }
        return object[key].asString();
    }

    static LLUUID requireUuid(const LLSD& object, const std::string& key, const std::string& label, bool allow_null = false)
    {
        const std::string value = requireString(object, key, label);
        if (!LLUUID::validate(value)) throw LabError("fixture", label + "." + key + " must be a UUID");
        LLUUID id(value);
        if (!allow_null && id.isNull()) throw LabError("fixture", label + "." + key + " must not be null");
        return id;
    }

    void loadInventoryFixture(const LLSD& fixture)
    {
        if (!fixture.isMap())
        {
            throw LabError("missing_capability", "inventory_model requires a deterministic fixture");
        }
        mFixtureId = requireString(fixture, "id", "fixture");
        const LLSD agent = fixture["agent"];
        const LLUUID agent_id = requireUuid(agent, "id", "fixture.agent");
        gAgentID = agent_id;
        gAgentUsername = requireString(agent, "name", "fixture.agent");

        LLAvatarNameCache::initializeOffline();
        const LLSD avatar_names = fixture["avatarNames"];
        if (!avatar_names.isArray())
        {
            throw LabError("fixture", "fixture.avatarNames must be an array");
        }
        for (LLSD::array_const_iterator entry = avatar_names.beginArray(); entry != avatar_names.endArray(); ++entry)
        {
            const LLUUID id = requireUuid(*entry, "id", "fixture.avatarNames entry");
            LLSD record;
            record["username"] = requireString(*entry, "userName", "fixture.avatarNames entry");
            record["display_name"] = requireString(*entry, "displayName", "fixture.avatarNames entry");
            record["legacy_first_name"] = record["display_name"];
            record["legacy_last_name"] = "Resident";
            record["is_display_name_default"] = false;
            record["display_name_expires"] = "2100-01-01T00:00:00Z";
            record["display_name_next_update"] = "2100-01-01T00:00:00Z";
            LLAvatarName avatar_name;
            avatar_name.fromLLSD(record);
            LLAvatarNameCache::getInstance()->insert(id, avatar_name);
        }

        const LLSD inventory = fixture["inventory"];
        if (!inventory.isArray() || inventory.size() == 0)
        {
            throw LabError("fixture", "fixture.inventory must be a non-empty array");
        }

        std::set<LLUUID> category_ids;
        std::map<LLUUID, S32> descendant_counts;
        LLUUID root_id;
        for (LLSD::array_const_iterator entry = inventory.beginArray(); entry != inventory.endArray(); ++entry)
        {
            const std::string kind = requireString(*entry, "kind", "fixture.inventory entry");
            if (kind != "root" && kind != "folder") continue;
            const LLUUID id = requireUuid(*entry, "id", "fixture.inventory entry");
            const LLUUID parent_id = requireUuid(*entry, "parentId", "fixture.inventory entry", true);
            if (!category_ids.insert(id).second) throw LabError("fixture", "duplicate inventory UUID: " + id.asString());
            mFixtureObjectIds.push_back(id);
            if (kind == "root")
            {
                if (root_id.notNull()) throw LabError("fixture", "fixture.inventory must contain exactly one root");
                if (parent_id.notNull()) throw LabError("fixture", "inventory root parentId must be null");
                root_id = id;
            }
            else
            {
                ++descendant_counts[parent_id];
            }
        }
        if (root_id.isNull()) throw LabError("fixture", "fixture.inventory must contain one root");

        gInventory.setRootFolderID(root_id);
        for (LLSD::array_const_iterator entry = inventory.beginArray(); entry != inventory.endArray(); ++entry)
        {
            const std::string kind = requireString(*entry, "kind", "fixture.inventory entry");
            if (kind != "root" && kind != "folder") continue;
            const LLUUID id = requireUuid(*entry, "id", "fixture.inventory entry");
            const LLUUID parent_id = requireUuid(*entry, "parentId", "fixture.inventory entry", true);
            LLPointer<LLViewerInventoryCategory> category = new LLViewerInventoryCategory(
                id, parent_id,
                kind == "root" ? LLFolderType::FT_ROOT_INVENTORY : LLFolderType::FT_NONE,
                requireString(*entry, "name", "fixture.inventory entry"), agent_id);
            category->setVersion(LLViewerInventoryCategory::VERSION_INITIAL);
            category->setDescendentCount(descendant_counts[id]);
            XUILabInventoryFixtureLoader::addCategory(gInventory, category);
        }

        for (LLSD::array_const_iterator entry = inventory.beginArray(); entry != inventory.endArray(); ++entry)
        {
            const std::string kind = requireString(*entry, "kind", "fixture.inventory entry");
            if (kind == "root" || kind == "folder") continue;
            if (kind != "notecard") throw LabError("fixture", "unsupported inventory kind: " + kind);
            const LLUUID id = requireUuid(*entry, "id", "fixture.inventory entry");
            const LLUUID parent_id = requireUuid(*entry, "parentId", "fixture.inventory entry");
            mFixtureObjectIds.push_back(id);
            if (!category_ids.contains(parent_id))
            {
                throw LabError("fixture", "inventory item parent is not a fixture folder: " + parent_id.asString());
            }
            LLPermissions permissions;
            permissions.init(agent_id, agent_id, LLUUID::null, LLUUID::null);
            permissions.initMasks(PERM_ALL, PERM_ALL, PERM_NONE, PERM_NONE, PERM_MOVE | PERM_TRANSFER);
            LLPointer<LLViewerInventoryItem> item = new LLViewerInventoryItem(
                id, parent_id, permissions, id.combine(agent_id), LLAssetType::AT_NOTECARD,
                LLInventoryType::IT_NOTECARD, requireString(*entry, "name", "fixture.inventory entry"),
                "xui-lab deterministic notecard", LLSaleInfo(), 0, 1700000000);
            item->setComplete(true);
            XUILabInventoryFixtureLoader::addItem(gInventory, item);
            ++descendant_counts[parent_id];
        }

        const LLUUID library_owner_id = LLUUID::generateNewID(mFixtureId + ":library-owner");
        const LLUUID library_root_id = LLUUID::generateNewID(mFixtureId + ":library-root");
        gInventory.setLibraryOwnerID(library_owner_id);
        gInventory.setLibraryRootFolderID(library_root_id);
        LLPointer<LLViewerInventoryCategory> library_root = new LLViewerInventoryCategory(
            library_root_id, LLUUID::null, LLFolderType::FT_ROOT_INVENTORY, "Library", library_owner_id);
        library_root->setVersion(LLViewerInventoryCategory::VERSION_INITIAL);
        library_root->setDescendentCount(0);
        XUILabInventoryFixtureLoader::addCategory(gInventory, library_root);

        for (S32 value = LLFolderType::FT_TEXTURE; value < LLFolderType::FT_COUNT; ++value)
        {
            const auto folder_type = static_cast<LLFolderType::EType>(value);
            if (LLFolderType::lookup(folder_type) == LLFolderType::badLookup() ||
                folder_type == LLFolderType::FT_ROOT_INVENTORY ||
                !LLFolderType::lookupIsSingletonType(folder_type))
            {
                continue;
            }
            const LLUUID id = LLUUID::generateNewID(mFixtureId + ":system:" + std::to_string(value));
            LLPointer<LLViewerInventoryCategory> category = new LLViewerInventoryCategory(
                id, root_id, folder_type, LLViewerFolderType::lookupNewCategoryName(folder_type), agent_id);
            category->setVersion(LLViewerInventoryCategory::VERSION_INITIAL);
            category->setDescendentCount(0);
            XUILabInventoryFixtureLoader::addCategory(gInventory, category);
            category_ids.insert(id);
            ++descendant_counts[root_id];
        }

        for (const LLUUID& category_id : category_ids)
        {
            if (LLViewerInventoryCategory* category = gInventory.getCategory(category_id))
            {
                category->setDescendentCount(descendant_counts[category_id]);
            }
        }
        gInventory.buildParentChildMap();
        if (!gInventory.isInventoryUsable() || !gInventory.getCategory(root_id) || gInventory.getItemCount() == 0)
        {
            throw LabError(
                "inventory_model",
                "production inventory model rejected the fixture: " +
                    LlsdToJson(XUILabInventoryFixtureLoader::validate(gInventory)));
        }
    }

    LLSD initialize(const LLSD& command)
    {
        if (mInitialized) throw LabError("already_initialized", "runtime initialization may only occur once");
        if (command["fork"].asString() != kFork || command["forkCommit"].asString() != kForkCommit)
        {
            throw LabError("source_mismatch", "controller fork metadata does not match this binary");
        }
        mSubject = parseSubject(command["subject"]);

        mResourceRoot = std::filesystem::weakly_canonical(command["resourceRoot"].asString());
        if (!std::filesystem::is_directory(mResourceRoot / "skins") ||
            !std::filesystem::is_directory(mResourceRoot / "app_settings"))
        {
            throw LabError("resource_root", "resource root lacks production skins or app_settings");
        }
        mArtifactDir = std::filesystem::weakly_canonical(
            std::filesystem::absolute(command["artifactDir"].asString()));
        std::filesystem::create_directories(mArtifactDir);

        const LLSD viewport = command["viewport"];
        mWidth = viewport["width"].asInteger();
        mHeight = viewport["height"].asInteger();
        mUIScale = viewport["uiScale"].asReal();
        if (mWidth <= 0 || mHeight <= 0 || mUIScale <= 0.0)
        {
            throw LabError("viewport", "viewport values must be positive");
        }

        mFixture = command["fixture"];
        initializeUI();
        mInitialized = true;
        advanceFrames(2);

        return LLSDMap("supportedCapabilities", supportedCapabilities())
            ("fork", std::string(kFork))
            ("forkCommit", std::string(kForkCommit))
            ("subject", std::string(subjectName()));
    }

    LLSD supportedCapabilities() const
    {
        LLSD capabilities = LLSD::emptyArray();
        capabilities.append("input");
        capabilities.append("inspection");
        if (mSubject == Subject::InventoryExplorer)
        {
            capabilities.append("inventory_model");
            capabilities.append("agent_identity");
            capabilities.append("menus");
        }
        return capabilities;
    }

    LLSD installCapabilities(const LLSD& command)
    {
        requireInitialized();
        const LLSD requested = command["capabilities"];
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
        for (const std::string& capability : mCapabilities) installed.append(capability);
        return LLSDMap("capabilities", installed)("eventApis", exposedEventApiMetadata());
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
            throw LabError("settings", "failed to load production viewer settings");
        }
        if (!gSkinSettings.loadFromFile(
                (mResourceRoot / "skins" / "default" / "skin_settings.xml").string(), true, false))
        {
            throw LabError("settings", "failed to load production skin settings");
        }
        LLUIColorTable::instance().loadFromSettings();

        LLRender::sGLCoreProfile = true;
        mWindow = std::make_unique<LabWindow>(mWidth, mHeight);
        LLVertexBuffer::initClass(mWindow->get());
        if (!gGL.init(true)) throw LabError("render", "production LLRender failed to initialize");
        LLImageGL::initClass(mWindow->get(), LLGLTexture::MAX_GL_IMAGE_CATEGORY, true, false);

        mShaderMgr = std::make_unique<LabShaderMgr>(app_settings / "shaders" / "class");
        gUIProgram.mName = "xui-lab UI Shader";
        gUIProgram.mShaderFiles = {{"interface/uiV.glsl", GL_VERTEX_SHADER}, {"interface/uiF.glsl", GL_FRAGMENT_SHADER}};
        gUIProgram.mShaderLevel = 1;
        gUIProgram.mFeatures.attachNothing = true;
        gSolidColorProgram.mName = "xui-lab Solid Color Shader";
        gSolidColorProgram.mShaderFiles = {
            {"interface/solidcolorV.glsl", GL_VERTEX_SHADER}, {"interface/solidcolorF.glsl", GL_FRAGMENT_SHADER}};
        gSolidColorProgram.mShaderLevel = 1;
        gSolidColorProgram.mFeatures.attachNothing = true;
        if (!gUIProgram.createShader() || !gSolidColorProgram.createShader())
        {
            throw LabError("shader", "failed to compile production LLUI shaders");
        }

        mImages = std::make_unique<LabImageProvider>();
        mImages->loadDeclarations();
        LLUI::settings_map_t settings;
        settings["config"] = &gSavedSettings;
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
        LLFontGL::initClass(
            gSavedSettings.getF32("FontScreenDPI"), static_cast<F32>(mUIScale), static_cast<F32>(mUIScale),
            gDirUtilp->getAppRODataDir(), gSavedSettings.getLLSD("AlchemyUIFontOverrides"));
        LLFolderViewItem::initClass();

        const S32 virtual_width = ll_round(mWidth / mUIScale);
        const S32 virtual_height = ll_round(mHeight / mUIScale);
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

        if (mSubject == Subject::InventoryExplorer) loadInventoryFixture(mFixture);
        if (mSubject == Subject::TestWidgets)
        {
            LLFloaterReg::add("test_widgets", "floater_test_widgets.xml", &LLFloaterReg::build<LLFloater>);
        }
        else
        {
            LLFloaterReg::add(
                "inventory_explorer", "floater_al_inventory_explorer.xml",
                &LLFloaterReg::build<ALFloaterInventoryExplorer>);
        }
        postEventApi(
            "LLFloaterReg",
            LLSDMap("op", "showInstance")("name", std::string(subjectName()))("focus", true));
        mFloater = LLFloaterReg::findInstance(std::string(subjectName()));
        if (!mFloater) throw LabError("subject", "registered floater failed to instantiate: " + std::string(subjectName()));
        mFloater->center();
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
        if (swap) mWindow->get()->swapBuffers();
    }

    LLSD advanceFrames(S32 count)
    {
        if (count < 0) throw LabError("frames", "frame count must not be negative");
        for (S32 index = 0; index < count; ++index) renderFrame(true);
        return LLSDMap("frames", count)("frameCount", mFrameCount);
    }

    LLSD stabilize(const LLSD& command)
    {
        requireInitialized();
        const S32 required = command["consecutiveFrames"].asInteger();
        const S32 maximum = command["maximumFrames"].asInteger();
        if (required <= 0 || maximum < required) throw LabError("stable", "invalid stabilization frame counts");

        std::string previous;
        S32 consecutive = 0;
        for (S32 frame = 1; frame <= maximum; ++frame)
        {
            renderFrame(true);
            const std::string current = LlsdToJson(
                callEventApi("LLWindow", LLSDMap("op", "getSubtree")));
            consecutive = current == previous ? consecutive + 1 : 1;
            previous = current;
            if (consecutive >= required) return LLSDMap("stable", true)("frames", frame);
        }
        return LLSDMap("stable", false)("frames", maximum);
    }

    LLSD resize(const LLSD& command)
    {
        requireInitialized();
        const S32 width = command["width"].asInteger();
        const S32 height = command["height"].asInteger();
        const F64 ui_scale = command.has("uiScale") ? command["uiScale"].asReal() : mUIScale;
        if (width <= 0 || height <= 0 || ui_scale <= 0.0)
        {
            throw LabError("viewport", "resize width, height, and uiScale must be positive");
        }

        mWidth = width;
        mHeight = height;
        mUIScale = ui_scale;
        LLUI::setScaleFactor(LLVector2(static_cast<F32>(mUIScale), static_cast<F32>(mUIScale)));
        mWindow->get()->setSize(LLCoordWindow(mWidth, mHeight));
        mRoot->reshape(ll_round(mWidth / mUIScale), ll_round(mHeight / mUIScale));
        renderFrame(true);
        return diagnostics()["viewport"];
    }

    LLSD reload(const LLSD&)
    {
        requireInitialized();
        gFocusMgr.setKeyboardFocus(nullptr);
        postEventApi(
            "LLFloaterReg",
            LLSDMap("op", "hideInstance")("name", std::string(subjectName())));
        mFloater = nullptr;
        LLMortician::updateClass();
        postEventApi(
            "LLFloaterReg",
            LLSDMap("op", "showInstance")("name", std::string(subjectName()))("focus", true));
        mFloater = LLFloaterReg::findInstance(std::string(subjectName()));
        if (!mFloater)
        {
            throw LabError("subject", "registered floater failed to reload: " + std::string(subjectName()));
        }
        mFloater->center();
        advanceFrames(2);
        return LLSDMap("subject", std::string(subjectName()))("view", mFloater->getInfo());
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
            LLSD result = LLSDMap("visible", gMenuHolder && gMenuHolder->hasVisibleMenu());
            LLSD menus = LLSD::emptyArray();
            if (gMenuHolder)
            {
                for (LLView* child : *gMenuHolder->getChildList())
                {
                    if (dynamic_cast<LLMenuGL*>(child)) menus.append(buildTree(child));
                }
            }
            result["menus"] = menus;
            if (gMenuHolder && gMenuHolder->getVisibleMenu())
            {
                result["tree"] = buildTree(gMenuHolder->getVisibleMenu());
            }
            return result;
        }
        if (kind == "inventory")
        {
            requireCapability("inventory_model");
            LLSD objects = LLSD::emptyArray();
            for (const LLUUID& id : mFixtureObjectIds)
            {
                const LLInventoryObject* object = gInventory.getObject(id);
                LLSD entry = LLSDMap("id", id)("present", object != nullptr);
                if (object)
                {
                    entry["name"] = object->getName();
                    entry["parentId"] = object->getParentUUID();
                }
                LLSD views = LLSD::emptyMap();
                for (const std::string_view panel_name : inventoryPanelNames())
                {
                    if (LLInventoryPanel* panel = mRoot->findChild<LLInventoryPanel>(panel_name))
                    {
                        if (LLFolderViewItem* item = panel->getItemByID(id))
                        {
                            views[std::string(panel_name)] = LLSDMap("present", true)
                                ("visibleChain", panel->isInVisibleChain())
                                ("rect", item->getInfo()["screen_rect"]);
                        }
                    }
                }
                entry["views"] = views;
                objects.append(entry);
            }
            return LLSDMap("usable", gInventory.isInventoryUsable())
                ("rootId", gInventory.getRootFolderID())
                ("itemCount", gInventory.getItemCount())
                ("objects", objects);
        }
        requireCapability("inspection");
        if (kind == "value")
        {
            if (!command["path"].isString()) throw LabError("path", "control path must be a string");
            return callEventApi(
                "UI", LLSDMap("op", "getValue")("path", command["path"]));
        }
        if (kind != "tree") throw LabError("query", "unsupported query kind: " + kind);
        LLSD request = LLSDMap("op", "getSubtree");
        if (command.has("path")) request["under"] = command["path"];
        return callEventApi("LLWindow", request);
    }

    static LLSD describeView(LLView* view)
    {
        return view ? view->getInfo() : LLSD();
    }

    LLSD diagnostics()
    {
        LLCoordWindow pixel_size(mWidth, mHeight);
        const bool measured_window = mWindow->get()->getSize(&pixel_size);
        const LLRect llui_rect = mRoot->getRect();

        LLSD graphics;
        gGLManager.asLLSD(graphics);

        return LLSDMap
            ("focus", describeView(dynamic_cast<LLView*>(gFocusMgr.getKeyboardFocus())))
            ("mouseCapture", describeView(dynamic_cast<LLView*>(gFocusMgr.getMouseCapture())))
            ("visibleMenu", describeView(gMenuHolder ? gMenuHolder->getVisibleMenu() : nullptr))
            ("subject", LLSDMap
                ("id", std::string(subjectName()))
                ("fixture", mFixtureId)
                ("view", describeView(mFloater)))
            ("viewport", LLSDMap
                ("pixelWidth", pixel_size.mX)
                ("pixelHeight", pixel_size.mY)
                ("windowMeasured", measured_window)
                ("lluiWidth", llui_rect.getWidth())
                ("lluiHeight", llui_rect.getHeight())
                ("uiScale", mUIScale))
            ("graphics", graphics)
            ("eventApis", exposedEventApiMetadata());
    }

    [[nodiscard]] bool hasCapability(std::string_view capability) const
    {
        return mCapabilities.contains(std::string(capability));
    }

    void requireCapability(std::string_view capability) const
    {
        if (!hasCapability(capability))
        {
            throw LabError(
                "missing_capability", "operation requires installed capability: " + std::string(capability));
        }
    }

    static void addEventApiMetadata(
        LLSD& result, std::string_view api_name, std::initializer_list<std::string_view> allowed_operations)
    {
        const auto api = LLEventAPI::getInstance(std::string(api_name));
        if (!api) return;

        LLSD operations = result.has(std::string(api_name))
            ? result[std::string(api_name)]["operations"]
            : LLSD::emptyArray();
        for (const std::string_view operation_name : allowed_operations)
        {
            LLSD operation = api->getMetadata(std::string(operation_name));
            if (operation.isDefined()) operations.append(operation);
        }
        if (operations.size() == 0) return;
        result[std::string(api_name)] = LLSDMap
            ("description", api->getDesc())
            ("dispatchKey", api->getDispatchKey())
            ("operations", operations);
    }

    LLSD exposedEventApiMetadata() const
    {
        LLSD result = LLSD::emptyMap();
        addEventApiMetadata(result, "XUILab", {
            "initialize", "installCapabilities", "frames", "stable", "resize",
            "capture", "reload", "diagnostics", "shutdown"});
        addEventApiMetadata(result, "LLFloaterReg", {
            "getBuildMap", "showInstance", "hideInstance", "toggleInstance",
            "toggleInstanceOrBringToFront", "instanceVisible", "clickButton"});
        if (hasCapability("inspection"))
        {
            addEventApiMetadata(result, "XUILab", {"query"});
            addEventApiMetadata(result, "LLWindow", {"getInfo", "getPaths", "getSubtree"});
            addEventApiMetadata(result, "UI", {"getValue"});
        }
        if (hasCapability("input"))
        {
            addEventApiMetadata(result, "XUILab", {"input"});
            addEventApiMetadata(result, "LLWindow", {
                "mouseDown", "mouseDoubleClick", "mouseUp", "mouseMove", "mouseScroll"});
            addEventApiMetadata(result, "UI", {"setSelectedByValue"});
        }
        return result;
    }

    LLView* resolveTarget(const LLSD& command) const
    {
        if (command.has("modelId"))
        {
            requireCapability("inventory_model");
            const LLUUID id = requireUuid(command, "modelId", "input");
            LLFolderViewItem* fallback = nullptr;
            for (const std::string_view panel_name : inventoryPanelNames())
            {
                LLInventoryPanel* panel = mRoot->findChild<LLInventoryPanel>(panel_name);
                LLFolderViewItem* item = panel ? panel->getItemByID(id) : nullptr;
                if (!item) continue;
                if (panel->isInVisibleChain()) return item;
                if (!fallback) fallback = item;
            }
            if (fallback) return fallback;
            throw LabError("model_id", "inventory view item not found: " + id.asString());
        }
        if (!command["path"].isString()) throw LabError("path", "target path must be a string");
        const std::string path = command["path"].asString();
        if (path.empty() || path.front() != '/') throw LabError("path", "target path must be absolute");
        LLView* target = LLUI::getInstance()->resolvePath(mRoot, path);
        if (!target || target->getPathname() != path) throw LabError("path", "view not found: " + path);
        return target;
    }

    LLSD input(const LLSD& command)
    {
        requireInitialized();
        requireCapability("input");
        const std::string event = command["event"].asString();
        if (event != "click" && event != "doubleClick")
        {
            throw LabError("input", "the proven input slice supports click and doubleClick events");
        }
        LLView* target = resolveTarget(command);
        const std::string button = command["button"].asString();
        if (button != "left" && button != "right") throw LabError("input", "button must be left or right");
        if (event == "doubleClick" && button != "left")
        {
            throw LabError("input", "doubleClick supports only the left button");
        }

        const std::string path = target->getPathname();
        const std::string production_button = button == "left" ? "LEFT" : "RIGHT";
        const std::string down_operation = event == "doubleClick" ? "mouseDoubleClick" : "mouseDown";
        const LLSD down = callEventApi(
            "LLWindow", LLSDMap("op", down_operation)("button", production_button)("path", path));
        const bool menu_visible_after_down = gMenuHolder && gMenuHolder->hasVisibleMenu();
        const LLSD up = callEventApi(
            "LLWindow", LLSDMap("op", "mouseUp")("button", production_button)("path", path));
        renderFrame(true);

        return LLSDMap("path", path)
            ("modelId", command["modelId"])
            ("event", event)
            ("button", button)
            ("handled", down["handled"].asBoolean() || up["handled"].asBoolean())
            ("downHandled", down["handled"])
            ("upHandled", up["handled"])
            ("menuVisibleAfterDown", menu_visible_after_down)
            ("menuVisibleAfterUp", gMenuHolder && gMenuHolder->hasVisibleMenu())
            ("down", down)
            ("up", up);
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

    LLSD capture(const LLSD& command)
    {
        requireInitialized();
        std::filesystem::path path;
        if (command.has("path"))
        {
            if (!command["path"].isString() || command["path"].asString().empty())
            {
                throw LabError("capture_path", "capture path must be a non-empty string");
            }
            const std::string value = command["path"].asString();
            const std::filesystem::path relative_path(value);
            std::string portable_value = value;
            std::ranges::replace(portable_value, '\\', '/');
            const std::filesystem::path portable_path(portable_value);
            if (relative_path.is_absolute() ||
                (!value.empty() && (value.front() == '/' || value.front() == '\\')) ||
                (value.size() >= 2 && std::isalpha(static_cast<unsigned char>(value.front())) && value[1] == ':') ||
                std::ranges::any_of(portable_path, [](const auto& part) { return part == ".."; }))
            {
                throw LabError("capture_path", "capture path must stay beneath the scenario artifact directory");
            }
            path = std::filesystem::weakly_canonical(mArtifactDir / relative_path);
            const std::filesystem::path contained_path = path.lexically_relative(mArtifactDir);
            if (contained_path.empty() || *contained_path.begin() == "..")
            {
                throw LabError("capture_path", "capture path must stay beneath the scenario artifact directory");
            }
        }
        else
        {
            std::string name = command["name"].asString();
            if (name.empty()) name = "frame";
            if (name == "." || name == ".." || name.find_first_of("/\\:") != std::string::npos)
            {
                throw LabError("capture_name", "capture name must not create subdirectories");
            }
            path = mArtifactDir / (name + ".png");
        }
        std::filesystem::create_directories(path.parent_path());

        renderFrame(false);
        std::string highlighted_path;
        if (command["includeOverlay"].asBoolean())
        {
            LLView* highlighted = resolveTarget(command["highlight"]);
            highlighted_path = highlighted->getPathname();
            drawHighlight(highlighted);
        }
        LLPointer<LLImageRaw> raw = new LLImageRaw(mWidth, mHeight, 4);
        glReadPixels(0, 0, mWidth, mHeight, GL_RGBA, GL_UNSIGNED_BYTE, raw->getData());
        LLPointer<LLImagePNG> png = new LLImagePNG();
        if (!png->encode(raw, 0.f) || !png->save(path.string()))
        {
            throw LabError("capture", "failed to save the rendered frame");
        }
        mWindow->get()->swapBuffers();

        const LLSD metadata = LLSDMap("fork", std::string(kFork))
            ("forkCommit", std::string(kForkCommit))
            ("subject", std::string(subjectName()))
            ("fixture", mFixtureId)
            ("viewport", LLSDMap("width", mWidth)("height", mHeight)("uiScale", mUIScale));
        std::ofstream sidecar(path.string() + ".json");
        sidecar << LlsdToJson(metadata) << '\n';
        return LLSDMap("path", path.string())("metadata", metadata)("highlightedPath", highlighted_path);
    }

    void requireInitialized() const
    {
        if (!mInitialized) throw LabError("not_initialized", "initialize must be the first command");
    }

    void shutdown()
    {
        if (!mInitialized) return;
        postEventApi(
            "LLFloaterReg",
            LLSDMap("op", "hideInstance")("name", std::string(subjectName())));
        mWindowListener.reset();
        LLUI::getInstance()->setRootView(nullptr);
        delete mRoot;
        mRoot = nullptr;
        gFloaterView = nullptr;
        gMenuHolder = nullptr;
        LLMenuGL::sMenuContainer = nullptr;
        if (mSubject == Subject::InventoryExplorer)
        {
            gInventory.cleanupInventory();
            gAgentID.setNull();
            gAgentSessionID.setNull();
            gAgentUsername.clear();
            LLAvatarNameCache::deleteSingleton();
        }
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

    std::unique_ptr<LabWindow> mWindow;
    std::unique_ptr<LLWindowListener> mWindowListener;
    std::unique_ptr<LabShaderMgr> mShaderMgr;
    std::unique_ptr<LabImageProvider> mImages;
    LLPanel* mRoot = nullptr;
    LLFloater* mFloater = nullptr;
    std::filesystem::path mResourceRoot;
    std::filesystem::path mArtifactDir;
    std::string mFixtureId;
    LLSD mFixture;
    std::vector<LLUUID> mFixtureObjectIds;
    S32 mWidth = 0;
    S32 mHeight = 0;
    S32 mFrameCount = 0;
    F64 mUIScale = 1.0;
    bool mInitialized = false;
    bool mDone = false;
    std::set<std::string> mCapabilities;
    Subject mSubject = Subject::TestWidgets;
};

LLSD failure(const std::string& code, const std::string& message)
{
    return LLSDMap("ok", false)("error", LLSDMap("code", code)("message", message));
}

int scenarioMain()
{
    Runtime runtime;
    std::string line;
    while (!runtime.done() && std::getline(std::cin, line))
    {
        LLSD command;
        std::string parse_error;
        if (!LlsdFromJsonString(line, command, &parse_error) || !command.isMap())
        {
            std::cout << LlsdToJson(failure("json", parse_error)) << std::endl;
            continue;
        }
        try
        {
            std::cout << LlsdToJson(
                LLSDMap("ok", true)("result", callEventApi("XUILab", command))) << std::endl;
        }
        catch (const LabError& error)
        {
            std::cout << LlsdToJson(failure(error.code(), error.what())) << std::endl;
        }
        catch (const std::exception& error)
        {
            std::cout << LlsdToJson(failure("internal", error.what())) << std::endl;
        }
    }
    return 0;
}
} // namespace

int main(int argc, char** argv)
{
    LLError::initForApplication(".", ".");
    LLError::setDefaultLevel(LLError::LEVEL_WARN);
    if (argc == 2 && std::string_view(argv[1]) == "--metadata")
    {
        std::cout << LlsdToJson(LLSDMap("fork", std::string(kFork))
            ("forkCommit", std::string(kForkCommit))("protocolVersion", 1)) << '\n';
        return 0;
    }
    if (argc == 2 && std::string_view(argv[1]) == "--scenario") return scenarioMain();
    std::cerr << "usage: xui-lab --metadata | --scenario\n";
    return 2;
}
