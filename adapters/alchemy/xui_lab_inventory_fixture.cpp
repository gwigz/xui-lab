#include "llviewerprecompiledheaders.h"

#include "xui_lab_inventory_fixture.h"

#include "xui_lab_error.h"

#include "llagentdata.h"
#include "llavatarname.h"
#include "llavatarnamecache.h"
#include "llinventorymodel.h"
#include "llsdjson.h"
#include "llsdutil.h"
#include "llviewerfoldertype.h"
#include "llviewerinventory.h"

#include <map>
#include <set>
#include <string>
#include <utility>
#include <variant>

class XUILabInventoryFixtureLoader final
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
                .kind      = kind == "root" ? InventoryCategoryKind::Root : InventoryCategoryKind::Folder,
                .id        = id,
                .parent_id = parent_id,
                .name      = name,
            });
        }
        else if (kind == "notecard")
        {
            result.inventory.emplace_back(InventoryNotecardFixture{
                .id        = id,
                .parent_id = parent_id,
                .name      = name,
            });
        }
        else
        {
            throw Error("fixture", "unsupported inventory kind: " + kind);
        }
    }
    if (root_id.isNull())
        throw Error("fixture", "fixture.inventory must contain one root");
    for (const auto& object : result.inventory)
    {
        if (const auto* item = std::get_if<InventoryNotecardFixture>(&object); item && !category_ids.contains(item->parent_id))
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
            XUILabInventoryFixtureLoader::addCategory(gInventory, category);
        }

        for (const auto& object : fixture.inventory)
        {
            const auto* item_fixture = std::get_if<InventoryNotecardFixture>(&object);
            if (!item_fixture)
                continue;
            mObjectIds.push_back(item_fixture->id);
            LLPermissions permissions;
            permissions.init(fixture.agent.id, fixture.agent.id, LLUUID::null, LLUUID::null);
            permissions.initMasks(PERM_ALL, PERM_ALL, PERM_NONE, PERM_NONE, PERM_MOVE | PERM_TRANSFER);
            LLPointer<LLViewerInventoryItem> item = new LLViewerInventoryItem(
                item_fixture->id, item_fixture->parent_id, permissions, item_fixture->id.combine(fixture.agent.id),
                LLAssetType::AT_NOTECARD, LLInventoryType::IT_NOTECARD, item_fixture->name, "xui-lab deterministic notecard", LLSaleInfo(),
                0, 1700000000);
            item->setComplete(true);
            XUILabInventoryFixtureLoader::addItem(gInventory, item);
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
        XUILabInventoryFixtureLoader::addCategory(gInventory, library_root);

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
            throw Error("inventory_model",
                        "production inventory model rejected the fixture: " +
                            LlsdToJson(XUILabInventoryFixtureLoader::validate(gInventory)));
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
