#include "llviewerprecompiledheaders.h"

#include "xui_lab_inventory_fixture.h"

#include "xui_lab_error.h"

#include "llappearancemgr.h"
#include "llagentdata.h"
#include "llavatarname.h"
#include "llavatarnamecache.h"
#include "llinventorymodel.h"
#include "llsdjson.h"
#include "llsdutil.h"
#include "llviewerfoldertype.h"
#include "llviewerinventory.h"
#include "llwearabletype.h"

#include <map>
#include <set>
#include <string>
#include <utility>
#include <variant>

class LLInventoryModelTestAccess final
{
public:
    static void addCategory(LLInventoryModel& inventory, LLViewerInventoryCategory* category) { inventory.addCategory(category); }

    static void addItem(LLInventoryModel& inventory, LLViewerInventoryItem* item) { inventory.addItem(item); }

    static LLSD validate(const LLInventoryModel& inventory)
    {
        LLSD result;
        inventory.validate()->asLLSD(result);
        return result;
    }
};

namespace
{
std::string requireString(const LLSD& object, const std::string& key, const std::string& label)
{
    if (!object.isMap() || !object[key].isString() || object[key].asString().empty())
    {
        throw xui_lab::Error("fixture", label + "." + key + " must be a non-empty string");
    }
    return object[key].asString();
}

LLUUID requireUuid(const LLSD& object, const std::string& key, const std::string& label, bool allow_null = false)
{
    const std::string value = requireString(object, key, label);
    if (!LLUUID::validate(value))
    {
        throw xui_lab::Error("fixture", label + "." + key + " must be a UUID");
    }
    LLUUID id(value);
    if (!allow_null && id.isNull())
    {
        throw xui_lab::Error("fixture", label + "." + key + " must not be null");
    }
    return id;
}

LLUUID optionalUuid(const LLSD& object, const std::string& key, const std::string& label)
{ return object.has(key) ? requireUuid(object, key, label) : LLUUID::null; }

bool optionalBoolean(const LLSD& object, const std::string& key, const std::string& label)
{
    if (!object.has(key))
        return false;
    if (!object[key].isBoolean())
        throw xui_lab::Error("fixture", label + "." + key + " must be a boolean");
    return object[key].asBoolean();
}

xui_lab::InventoryItemKind requireItemKind(const std::string& kind)
{
    static const std::map<std::string, xui_lab::InventoryItemKind, std::less<>> kinds{
        { "animation", xui_lab::InventoryItemKind::Animation }, { "gesture", xui_lab::InventoryItemKind::Gesture },
        { "landmark", xui_lab::InventoryItemKind::Landmark },   { "material", xui_lab::InventoryItemKind::Material },
        { "notecard", xui_lab::InventoryItemKind::Notecard },   { "object", xui_lab::InventoryItemKind::Object },
        { "script", xui_lab::InventoryItemKind::Script },       { "sound", xui_lab::InventoryItemKind::Sound },
        { "texture", xui_lab::InventoryItemKind::Texture },     { "wearable", xui_lab::InventoryItemKind::Wearable },
    };
    const auto found = kinds.find(kind);
    if (found == kinds.end())
        throw xui_lab::Error("fixture", "unsupported inventory kind: " + kind);
    return found->second;
}

std::pair<LLAssetType::EType, LLInventoryType::EType> itemTypes(xui_lab::InventoryItemKind kind)
{
    using enum xui_lab::InventoryItemKind;
    switch (kind)
    {
        case Animation:
            return { LLAssetType::AT_ANIMATION, LLInventoryType::IT_ANIMATION };
        case Gesture:
            return { LLAssetType::AT_GESTURE, LLInventoryType::IT_GESTURE };
        case Landmark:
            return { LLAssetType::AT_LANDMARK, LLInventoryType::IT_LANDMARK };
        case Material:
            return { LLAssetType::AT_MATERIAL, LLInventoryType::IT_MATERIAL };
        case Notecard:
            return { LLAssetType::AT_NOTECARD, LLInventoryType::IT_NOTECARD };
        case Object:
            return { LLAssetType::AT_OBJECT, LLInventoryType::IT_OBJECT };
        case Script:
            return { LLAssetType::AT_LSL_TEXT, LLInventoryType::IT_LSL };
        case Sound:
            return { LLAssetType::AT_SOUND, LLInventoryType::IT_SOUND };
        case Texture:
            return { LLAssetType::AT_TEXTURE, LLInventoryType::IT_TEXTURE };
        case Wearable:
            return { LLAssetType::AT_CLOTHING, LLInventoryType::IT_WEARABLE };
    }
    llassert(false);
    return { LLAssetType::AT_NONE, LLInventoryType::IT_NONE };
}
} // namespace

namespace xui_lab
{
InventoryFixtureData parseInventoryFixture(const LLSD& fixture)
{
    if (!fixture.isMap())
    {
        throw Error("missing_capability", "inventory_model requires a deterministic fixture");
    }

    InventoryFixtureData result{
        .id = requireString(fixture, "id", "fixture"),
        .agent =
            AgentFixture{
                .id   = requireUuid(fixture["agent"], "id", "fixture.agent"),
                .name = requireString(fixture["agent"], "name", "fixture.agent"),
            },
    };

    const LLSD& avatar_names = fixture["avatarNames"];
    if (!avatar_names.isArray())
    {
        throw Error("fixture", "fixture.avatarNames must be an array");
    }
    for (const LLSD& entry : llsd::inArray(avatar_names))
    {
        result.avatar_names.push_back(AvatarNameFixture{
            .id           = requireUuid(entry, "id", "fixture.avatarNames entry"),
            .user_name    = requireString(entry, "userName", "fixture.avatarNames entry"),
            .display_name = requireString(entry, "displayName", "fixture.avatarNames entry"),
        });
    }

    const LLSD& inventory = fixture["inventory"];
    if (!inventory.isArray() || inventory.size() == 0)
    {
        throw Error("fixture", "fixture.inventory must be a non-empty array");
    }

    std::set<LLUUID> category_ids;
    LLUUID           root_id;
    for (const LLSD& entry : llsd::inArray(inventory))
    {
        const std::string kind      = requireString(entry, "kind", "fixture.inventory entry");
        const LLUUID      id        = requireUuid(entry, "id", "fixture.inventory entry");
        const LLUUID      parent_id = requireUuid(entry, "parentId", "fixture.inventory entry", kind == "root" || kind == "folder");
        const std::string name      = requireString(entry, "name", "fixture.inventory entry");
        if (kind == "root" || kind == "folder")
        {
            if (!category_ids.insert(id).second)
            {
                throw Error("fixture", "duplicate inventory UUID: " + id.asString());
            }
            if (kind == "root")
            {
                if (root_id.notNull())
                {
                    throw Error("fixture", "fixture.inventory must contain exactly one root");
                }
                if (parent_id.notNull())
                {
                    throw Error("fixture", "inventory root parentId must be null");
                }
                root_id = id;
            }
            result.inventory.emplace_back(InventoryCategoryFixture{
                .kind         = kind == "root" ? InventoryCategoryKind::Root : InventoryCategoryKind::Folder,
                .id           = id,
                .parent_id    = parent_id,
                .name         = name,
                .thumbnail_id = optionalUuid(entry, "thumbnailId", "fixture.inventory entry"),
                .favorite     = optionalBoolean(entry, "favorite", "fixture.inventory entry"),
            });
        }
        else
        {
            result.inventory.emplace_back(InventoryItemFixture{
                .kind         = requireItemKind(kind),
                .id           = id,
                .parent_id    = parent_id,
                .name         = name,
                .thumbnail_id = optionalUuid(entry, "thumbnailId", "fixture.inventory entry"),
                .favorite     = optionalBoolean(entry, "favorite", "fixture.inventory entry"),
                .worn         = optionalBoolean(entry, "worn", "fixture.inventory entry"),
            });
        }
    }
    if (root_id.isNull())
        throw Error("fixture", "fixture.inventory must contain one root");
    for (const auto& object : result.inventory)
    {
        if (const auto* item = std::get_if<InventoryItemFixture>(&object); item && !category_ids.contains(item->parent_id))
        {
            throw Error("fixture", "inventory item parent is not a fixture folder: " + item->parent_id.asString());
        }
    }
    return result;
}

InventoryFixture::InventoryFixture(InventoryFixtureData fixture) : mId(std::move(fixture.id)), mActive(true)
{
    try
    {
        gAgentID       = fixture.agent.id;
        gAgentUsername = fixture.agent.name;

        LLAvatarNameCache::initializeOffline();
        for (const AvatarNameFixture& entry : fixture.avatar_names)
        {
            LLSD record;
            record["username"]                 = entry.user_name;
            record["display_name"]             = entry.display_name;
            record["legacy_first_name"]        = entry.display_name;
            record["legacy_last_name"]         = "Resident";
            record["is_display_name_default"]  = false;
            record["display_name_expires"]     = "2100-01-01T00:00:00Z";
            record["display_name_next_update"] = "2100-01-01T00:00:00Z";
            LLAvatarName avatar_name;
            avatar_name.fromLLSD(record);
            LLAvatarNameCache::getInstance()->insert(entry.id, avatar_name);
        }

        std::set<LLUUID>      category_ids;
        std::map<LLUUID, S32> descendant_counts;
        LLUUID                root_id;
        for (const auto& object : fixture.inventory)
        {
            if (const auto* category = std::get_if<InventoryCategoryFixture>(&object))
            {
                category_ids.insert(category->id);
                mObjectIds.push_back(category->id);
                if (category->kind == InventoryCategoryKind::Root)
                    root_id = category->id;
                else
                    ++descendant_counts[category->parent_id];
            }
        }

        gInventory.setRootFolderID(root_id);
        for (const auto& object : fixture.inventory)
        {
            const auto* category_fixture = std::get_if<InventoryCategoryFixture>(&object);
            if (!category_fixture)
                continue;
            LLPointer<LLViewerInventoryCategory> category = new LLViewerInventoryCategory(
                category_fixture->id, category_fixture->parent_id,
                category_fixture->kind == InventoryCategoryKind::Root ? LLFolderType::FT_ROOT_INVENTORY : LLFolderType::FT_NONE,
                category_fixture->name, fixture.agent.id);
            category->setVersion(LLViewerInventoryCategory::VERSION_INITIAL);
            category->setDescendentCount(descendant_counts[category_fixture->id]);
            category->setThumbnailUUID(category_fixture->thumbnail_id);
            category->setFavorite(category_fixture->favorite);
            LLInventoryModelTestAccess::addCategory(gInventory, category);
        }

        for (const auto& object : fixture.inventory)
        {
            const auto* item_fixture = std::get_if<InventoryItemFixture>(&object);
            if (!item_fixture)
                continue;
            const auto [asset_type, inventory_type] = itemTypes(item_fixture->kind);
            mObjectIds.push_back(item_fixture->id);
            LLPermissions permissions;
            permissions.init(fixture.agent.id, fixture.agent.id, LLUUID::null, LLUUID::null);
            permissions.initMasks(PERM_ALL, PERM_ALL, PERM_NONE, PERM_NONE, PERM_MOVE | PERM_TRANSFER);
            LLPointer<LLViewerInventoryItem> item = new LLViewerInventoryItem(
                item_fixture->id, item_fixture->parent_id, permissions, item_fixture->id.combine(fixture.agent.id), asset_type,
                inventory_type, item_fixture->name, "xui-lab deterministic inventory item", LLSaleInfo(),
                item_fixture->kind == InventoryItemKind::Wearable ? static_cast<U32>(LLWearableType::WT_JACKET) : 0, 1700000000);
            item->setThumbnailUUID(item_fixture->thumbnail_id);
            item->setFavorite(item_fixture->favorite);
            item->setComplete(true);
            LLInventoryModelTestAccess::addItem(gInventory, item);
            ++descendant_counts[item_fixture->parent_id];
        }

        const LLUUID library_owner_id = LLUUID::generateNewID(mId + ":library-owner");
        const LLUUID library_root_id  = LLUUID::generateNewID(mId + ":library-root");
        gInventory.setLibraryOwnerID(library_owner_id);
        gInventory.setLibraryRootFolderID(library_root_id);
        LLPointer<LLViewerInventoryCategory> library_root =
            new LLViewerInventoryCategory(library_root_id, LLUUID::null, LLFolderType::FT_ROOT_INVENTORY, "Library", library_owner_id);
        library_root->setVersion(LLViewerInventoryCategory::VERSION_INITIAL);
        library_root->setDescendentCount(0);
        LLInventoryModelTestAccess::addCategory(gInventory, library_root);

        LLUUID current_outfit_id;
        for (S32 value = LLFolderType::FT_TEXTURE; value < LLFolderType::FT_COUNT; ++value)
        {
            const auto folder_type = static_cast<LLFolderType::EType>(value);
            if (LLFolderType::lookup(folder_type) == LLFolderType::badLookup() || folder_type == LLFolderType::FT_ROOT_INVENTORY ||
                !LLFolderType::lookupIsSingletonType(folder_type))
            {
                continue;
            }
            const LLUUID                         id       = LLUUID::generateNewID(mId + ":system:" + std::to_string(value));
            LLPointer<LLViewerInventoryCategory> category = new LLViewerInventoryCategory(
                id, root_id, folder_type, LLViewerFolderType::lookupNewCategoryName(folder_type), fixture.agent.id);
            category->setVersion(LLViewerInventoryCategory::VERSION_INITIAL);
            category->setDescendentCount(0);
            LLInventoryModelTestAccess::addCategory(gInventory, category);
            category_ids.insert(id);
            ++descendant_counts[root_id];
            if (folder_type == LLFolderType::FT_CURRENT_OUTFIT)
                current_outfit_id = id;
        }

        for (const auto& object : fixture.inventory)
        {
            const auto* item_fixture = std::get_if<InventoryItemFixture>(&object);
            if (!item_fixture || !item_fixture->worn)
                continue;
            if (current_outfit_id.isNull())
                throw Error("inventory_model", "worn fixture items require the Current Outfit system folder");

            const LLInventoryType::EType inventory_type = itemTypes(item_fixture->kind).second;
            const LLUUID                 link_id        = LLUUID::generateNewID(mId + ":worn:" + item_fixture->id.asString());
            LLPermissions                permissions;
            permissions.init(fixture.agent.id, fixture.agent.id, LLUUID::null, LLUUID::null);
            permissions.initMasks(PERM_ALL, PERM_ALL, PERM_NONE, PERM_NONE, PERM_MOVE | PERM_TRANSFER);
            LLPointer<LLViewerInventoryItem> link = new LLViewerInventoryItem(
                link_id, current_outfit_id, permissions, item_fixture->id, LLAssetType::AT_LINK, inventory_type, item_fixture->name,
                "xui-lab deterministic worn link", LLSaleInfo(),
                item_fixture->kind == InventoryItemKind::Wearable ? static_cast<U32>(LLWearableType::WT_JACKET) : 0, 1700000000);
            link->setComplete(true);
            LLInventoryModelTestAccess::addItem(gInventory, link);
            ++descendant_counts[current_outfit_id];
        }

        for (const LLUUID& category_id : category_ids)
        {
            if (LLViewerInventoryCategory* category = gInventory.getCategory(category_id))
            {
                category->setDescendentCount(descendant_counts[category_id]);
            }
        }
        gInventory.buildParentChildMap();
        LLAppearanceMgr::instance().initCOFID();
        if (!gInventory.isInventoryUsable() || !gInventory.getCategory(root_id) || gInventory.getItemCount() == 0)
        {
            throw Error("inventory_model",
                        "production inventory model rejected the fixture: " + LlsdToJson(LLInventoryModelTestAccess::validate(gInventory)));
        }
    }
    catch (...)
    {
        cleanup();
        throw;
    }
}

InventoryFixture::~InventoryFixture()
{ cleanup(); }

void InventoryFixture::cleanup() noexcept
{
    if (!mActive)
        return;
    gInventory.cleanupInventory();
    gAgentID.setNull();
    gAgentSessionID.setNull();
    gAgentUsername.clear();
    LLAvatarNameCache::deleteSingleton();
    mActive = false;
}
} // namespace xui_lab
