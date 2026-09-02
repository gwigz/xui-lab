#include "llviewerprecompiledheaders.h"

#include "xui_lab_inspection.h"

#include "xui_lab_error.h"
#include "xui_lab_event_api.h"

#include "llfolderviewitem.h"
#include "llfolderviewmodelinventory.h"
#include "llinventorymodel.h"
#include "llinventorypanel.h"
#include "llmenugl.h"
#include "llpanel.h"
#include "llui.h"
#include "lluictrl.h"
#include "llview.h"
#include "llviewermenu.h"

#include <array>
#include <string>
#include <string_view>

namespace
{
constexpr std::array<std::string_view, 7> inventoryPanelNames()
{
    return { "all_items_tree",
             "all_items_list",
             "recent_collection_view",
             "worn_collection_view",
             "favorites_collection_view",
             "type_filter_collection_view",
             "all_items_grid" };
}

void addFolderState(LLSD& node, LLFolderViewItem* item)
{
    node["label"]    = wstring_to_utf8str(item->getLabel());
    node["selected"] = item->isSelected();
    node["open"]     = item->isOpen();
    if (auto* model_item = dynamic_cast<LLFolderViewModelItemInventory*>(item->getViewModelItem()))
    {
        node["model_id"] = model_item->getUUID();
    }
}

LLSD buildFolderTree(LLFolderViewItem* item, const std::string& parent_path)
{
    LLSD node = item->getInfo();
    addFolderState(node, item);
    const std::string segment = node.has("model_id") ? "@" + node["model_id"].asString() : item->getName();
    node["path"]              = parent_path + "/" + segment;

    LLSD children  = LLSD::emptyArray();
    S32  hit_order = 0;
    if (auto* folder = dynamic_cast<LLFolderViewFolder*>(item))
    {
        for (auto iterator = folder->getFoldersBegin(); iterator != folder->getFoldersEnd(); ++iterator)
        {
            LLSD child              = buildFolderTree(*iterator, node["path"].asString());
            child["hit_test_order"] = hit_order++;
            children.append(child);
        }
        for (auto iterator = folder->getItemsBegin(); iterator != folder->getItemsEnd(); ++iterator)
        {
            LLSD child              = buildFolderTree(*iterator, node["path"].asString());
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
    if (auto* control = dynamic_cast<LLUICtrl*>(view))
        node["value"] = control->getValue();
    if (auto* menu_item = dynamic_cast<LLMenuItemGL*>(view))
        node["label"] = menu_item->getLabel();
    if (auto* folder_item = dynamic_cast<LLFolderViewItem*>(view))
        addFolderState(node, folder_item);
    LLSD children  = LLSD::emptyArray();
    S32  hit_order = 0;
    if (auto* folder = dynamic_cast<LLFolderViewFolder*>(view))
    {
        for (auto iterator = folder->getFoldersBegin(); iterator != folder->getFoldersEnd(); ++iterator)
        {
            LLSD child_node              = buildFolderTree(*iterator, node["path"].asString());
            child_node["hit_test_order"] = hit_order++;
            children.append(child_node);
        }
        for (auto iterator = folder->getItemsBegin(); iterator != folder->getItemsEnd(); ++iterator)
        {
            LLSD child_node              = buildFolderTree(*iterator, node["path"].asString());
            child_node["hit_test_order"] = hit_order++;
            children.append(child_node);
        }
    }
    else
    {
        for (auto* child : *view->getChildList())
        {
            LLSD child_node              = buildTree(child);
            child_node["hit_test_order"] = hit_order++;
            children.append(child_node);
        }
    }
    node["children"] = children;
    return node;
}
} // namespace

namespace xui_lab
{
Inspection::Inspection(LLPanel& root) noexcept : mRoot(root)
{
}

LLSD Inspection::menus() const
{
    LLSD result = LLSDMap("visible", gMenuHolder && gMenuHolder->hasVisibleMenu());
    LLSD menus  = LLSD::emptyArray();
    if (gMenuHolder)
    {
        for (LLView* child : *gMenuHolder->getChildList())
        {
            if (dynamic_cast<LLMenuGL*>(child))
                menus.append(buildTree(child));
        }
    }
    result["menus"] = menus;
    if (gMenuHolder && gMenuHolder->getVisibleMenu())
    {
        result["tree"] = buildTree(gMenuHolder->getVisibleMenu());
    }
    return result;
}

LLSD Inspection::inventory(const std::vector<LLUUID>& fixture_object_ids) const
{
    LLSD objects = LLSD::emptyArray();
    for (const LLUUID& id : fixture_object_ids)
    {
        const LLInventoryObject* object = gInventory.getObject(id);
        LLSD                     entry  = LLSDMap("id", id)("present", object != nullptr);
        if (object)
        {
            entry["name"]     = object->getName();
            entry["parentId"] = object->getParentUUID();
        }
        LLSD views = LLSD::emptyMap();
        for (const std::string_view panel_name : inventoryPanelNames())
        {
            if (LLInventoryPanel* panel = mRoot.findChild<LLInventoryPanel>(panel_name))
            {
                if (LLFolderViewItem* item = panel->getItemByID(id))
                {
                    views[std::string(panel_name)] =
                        LLSDMap("present", true)("visibleChain", panel->isInVisibleChain())("rect", item->getInfo()["screen_rect"]);
                }
            }
        }
        entry["views"] = views;
        objects.append(entry);
    }
    return LLSDMap("usable", gInventory.isInventoryUsable())("rootId", gInventory.getRootFolderID())(
        "itemCount", gInventory.getItemCount())("objects", objects);
}

LLSD Inspection::value(std::string_view path) const
{ return callEventApi("UI", LLSDMap("op", "getValue")("path", std::string(path))); }

LLSD Inspection::tree(const LLSD& command) const
{
    LLSD request = LLSDMap("op", "getSubtree");
    if (command.has("path"))
        request["under"] = command["path"];
    return callEventApi("LLWindow", request);
}

LLView* Inspection::resolvePath(std::string_view requested_path) const
{
    const std::string path(requested_path);
    if (path.empty() || path.front() != '/')
        throw Error("path", "target path must be absolute");
    LLView* target = LLUI::getInstance()->resolvePath(&mRoot, path);
    if (!target || target->getPathname() != path)
        throw Error("path", "view not found: " + path);
    return target;
}

LLView* Inspection::resolveModelId(const LLUUID& id) const
{
    LLFolderViewItem* fallback = nullptr;
    for (const std::string_view panel_name : inventoryPanelNames())
    {
        LLInventoryPanel* panel = mRoot.findChild<LLInventoryPanel>(panel_name);
        LLFolderViewItem* item  = panel ? panel->getItemByID(id) : nullptr;
        if (!item)
            continue;
        if (panel->isInVisibleChain())
            return item;
        if (!fallback)
            fallback = item;
    }
    if (fallback)
        return fallback;
    throw Error("model_id", "inventory view item not found: " + id.asString());
}
} // namespace xui_lab
