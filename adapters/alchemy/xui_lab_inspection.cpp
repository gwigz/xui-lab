#include "llviewerprecompiledheaders.h"

#include "xui_lab_inspection.h"

#include "xui_lab_error.h"
#include "xui_lab_event_api.h"

#include "llfolderviewitem.h"
#include "llfolderviewmodelinventory.h"
#include "llinventorymodel.h"
#include "llinventorypanel.h"
#include "lldraghandle.h"
#include "llmenugl.h"
#include "llpanel.h"
#include "llresizebar.h"
#include "llresizehandle.h"
#include "llui.h"
#include "lluictrl.h"
#include "llview.h"
#include "llviewermenu.h"

#include <array>
#include <functional>
#include <string>
#include <string_view>
#include <unordered_map>

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

using ControlIds = std::unordered_map<LLView*, std::string>;

const std::string& requireControlId(const ControlIds& control_ids, LLView* view)
{
    const auto found = control_ids.find(view);
    if (found == control_ids.end())
        throw xui_lab::Error("control_id", "view is missing its structural control identity");
    return found->second;
}

// Open menus reparent out of the indexed subtree.
std::string optionalControlId(const ControlIds& control_ids, LLView* view)
{
    const auto found = control_ids.find(view);
    return found == control_ids.end() ? std::string() : found->second;
}

// Closed, filtered, and scrolled-away rows still exist in the panel.
std::string unusableForInput(const LLFolderViewItem& item)
{
    if (!item.isInVisibleChain())
        return "not in the visible chain";
    const LLRect clipped = xui_lab::Inspection::clippedScreenRect(item);
    if (clipped.getWidth() <= 0 || clipped.getHeight() <= 0)
        return "clipped to an empty rectangle";
    return {};
}

LLSD describeMenuEntry(LLMenuItemGL& item, const std::string& menu_path, const ControlIds& control_ids)
{
    const LLSD info        = item.getInfo();
    LLSD       entry       = LLSD::emptyMap();
    entry["label"]         = item.getLabel();
    entry["menu"]          = menu_path;
    entry["path"]          = info["path"];
    entry["control_id"]    = optionalControlId(control_ids, &item);
    entry["class"]         = info["class"];
    entry["enabled"]       = item.getEnabled();
    entry["enabled_chain"] = info["enabled_chain"];
    entry["visible"]       = item.getVisible();
    entry["separator"]     = dynamic_cast<LLMenuItemSeparatorGL*>(&item) != nullptr;
    entry["source_file"]   = info["source_file"];
    entry["source_line"]   = info["source_line"];
    return entry;
}

void collectMenuEntries(LLMenuGL& menu, LLSD& entries, const ControlIds& control_ids)
{
    const std::string menu_path = menu.getPathname();
    const S32         count     = static_cast<S32>(menu.getItemCount());
    for (S32 index = 0; index < count; ++index)
    {
        LLMenuItemGL* item = menu.getItem(index);
        if (!item || !item->getVisible())
            continue;
        entries.append(describeMenuEntry(*item, menu_path, control_ids));
        auto*     branch  = dynamic_cast<LLMenuItemBranchGL*>(item);
        LLMenuGL* submenu = branch ? branch->getBranch() : nullptr;
        if (submenu && submenu->getVisible())
            collectMenuEntries(*submenu, entries, control_ids);
    }
}

LLSD describeMenu(LLMenuGL& menu, const ControlIds& control_ids)
{
    const LLSD info        = menu.getInfo();
    LLSD       summary     = LLSD::emptyMap();
    summary["label"]       = menu.getLabel();
    summary["path"]        = info["path"];
    summary["control_id"]  = optionalControlId(control_ids, &menu);
    summary["class"]       = info["class"];
    summary["visible"]     = menu.getVisible();
    summary["itemCount"]   = static_cast<S32>(menu.getItemCount());
    summary["source_file"] = info["source_file"];
    summary["source_line"] = info["source_line"];
    return summary;
}

LLSD buildFolderTree(LLFolderViewItem* item, const std::string& parent_path, const ControlIds& control_ids)
{
    LLSD node          = item->getInfo();
    node["control_id"] = requireControlId(control_ids, item);
    addFolderState(node, item);
    const std::string segment = node.has("model_id") ? "@" + node["model_id"].asString() : item->getName();
    node["path"]              = parent_path + "/" + segment;

    LLSD children  = LLSD::emptyArray();
    S32  hit_order = 0;
    if (auto* folder = dynamic_cast<LLFolderViewFolder*>(item))
    {
        for (auto iterator = folder->getFoldersBegin(); iterator != folder->getFoldersEnd(); ++iterator)
        {
            LLSD child              = buildFolderTree(*iterator, node["path"].asString(), control_ids);
            child["hit_test_order"] = hit_order++;
            children.append(child);
        }
        for (auto iterator = folder->getItemsBegin(); iterator != folder->getItemsEnd(); ++iterator)
        {
            LLSD child              = buildFolderTree(*iterator, node["path"].asString(), control_ids);
            child["hit_test_order"] = hit_order++;
            children.append(child);
        }
    }
    node["children"] = children;
    return node;
}

LLSD buildTree(LLView* view, const ControlIds& control_ids)
{
    LLSD node          = view->getInfo();
    node["control_id"] = requireControlId(control_ids, view);
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
            LLSD child_node              = buildFolderTree(*iterator, node["path"].asString(), control_ids);
            child_node["hit_test_order"] = hit_order++;
            children.append(child_node);
        }
        for (auto iterator = folder->getItemsBegin(); iterator != folder->getItemsEnd(); ++iterator)
        {
            LLSD child_node              = buildFolderTree(*iterator, node["path"].asString(), control_ids);
            child_node["hit_test_order"] = hit_order++;
            children.append(child_node);
        }
    }
    else
    {
        for (auto* child : *view->getChildList())
        {
            if (!child)
                continue;
            LLSD child_node              = buildTree(child, control_ids);
            child_node["hit_test_order"] = hit_order++;
            children.append(child_node);
        }
    }
    node["children"] = children;
    return node;
}

void collectHitViews(LLView* view, S32 screen_x, S32 screen_y, std::vector<LLView*>& hits)
{
    if (!view->isInVisibleChain())
        return;

    S32 local_x = 0;
    S32 local_y = 0;
    view->screenPointToLocal(screen_x, screen_y, &local_x, &local_y);
    if (!view->pointInView(local_x, local_y, LLView::HIT_TEST_IGNORE_BOUNDING_RECT))
        return;

    for (LLView* child : *view->getChildList())
    {
        if (child)
            collectHitViews(child, screen_x, screen_y, hits);
    }
    // Inspection follows interactive production views, not only LLUICtrl.
    // Floater drag and resize surfaces deliberately derive directly from
    // LLView but still handle pointer events and capture the mouse.
    const bool pointer_surface =
        dynamic_cast<LLDragHandle*>(view) || dynamic_cast<LLResizeBar*>(view) || dynamic_cast<LLResizeHandle*>(view);
    const bool inactive_menu_holder = view == gMenuHolder && !gMenuHolder->hasVisibleMenu();
    if (!inactive_menu_holder && (dynamic_cast<LLUICtrl*>(view) || pointer_surface))
        hits.push_back(view);
}

void indexView(LLView* view, const std::string& control_id, std::unordered_map<std::string, LLView*>& views_by_id, ControlIds& ids_by_view)
{
    if (!view)
        return;
    views_by_id.emplace(control_id, view);
    ids_by_view.emplace(view, control_id);

    S32         child_index = 0;
    const auto* children    = view->getChildList();
    const auto  index_child = [&](LLView* child)
    {
        if (!child)
            return;
        indexView(child, control_id + "." + std::to_string(child_index++), views_by_id, ids_by_view);
    };
    if (auto* folder = dynamic_cast<LLFolderViewFolder*>(view))
    {
        for (auto iterator = folder->getFoldersBegin(); iterator != folder->getFoldersEnd(); ++iterator)
            index_child(*iterator);
        for (auto iterator = folder->getItemsBegin(); iterator != folder->getItemsEnd(); ++iterator)
            index_child(*iterator);
        return;
    }
    if (!children)
        return;
    for (LLView* child : *children)
        index_child(child);
}

LLSD describePick(LLView* target, const std::vector<LLView*>& hits, S32 x, S32 y, const ControlIds& control_ids)
{
    LLSD result = target ? target->getInfo() : LLSD::emptyMap();
    if (target)
        result["control_id"] = requireControlId(control_ids, target);
    result["x"] = x;
    result["y"] = y;
    LLSD order  = LLSD::emptyArray();
    for (std::size_t index = 0; index < hits.size(); ++index)
    {
        LLView* view = hits[index];
        order.append(LLSDMap("order", static_cast<S32>(index))("control_id", requireControlId(control_ids, view))(
            "path",
            view->getPathname())("class", view->getInfo()["class"])("source_file", view->getInfo()["source_file"])(
            "source_line",
            view->getInfo()["source_line"])("screen_rect", view->getInfo()["screen_rect"]));
    }
    result["hit_test_order"] = order;
    return result;
}
} // namespace

namespace xui_lab
{
Inspection::Inspection(LLPanel& root) noexcept : mRoot(root)
{
}

LLRect Inspection::clippedScreenRect(const LLView& view)
{
    LLRect rect = view.calcScreenRect();
    for (const LLView* ancestor = view.getParent(); ancestor; ancestor = ancestor->getParent())
        rect.intersectWith(ancestor->calcScreenRect());
    return rect;
}

LLSD Inspection::menus() const
{
    rebuildControlIndex();
    LLMenuGL* visible = gMenuHolder ? dynamic_cast<LLMenuGL*>(gMenuHolder->getVisibleMenu()) : nullptr;
    LLSD      result  = LLSDMap("visible", visible != nullptr);
    LLSD      menus   = LLSD::emptyArray();
    if (gMenuHolder)
    {
        for (LLView* child : *gMenuHolder->getChildList())
        {
            if (auto* menu = dynamic_cast<LLMenuGL*>(child))
                menus.append(describeMenu(*menu, mControlIdsByView));
        }
    }
    result["menus"] = menus;

    LLSD entries = LLSD::emptyArray();
    if (visible)
    {
        collectMenuEntries(*visible, entries, mControlIdsByView);
        result["tree"] = buildTree(visible, mControlIdsByView);
    }
    result["entries"] = entries;
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
    return LLSDMap("usable", gInventory.isInventoryUsable())("rootId", gInventory.getRootFolderID())("itemCount",
                                                                                                     gInventory.getItemCount())("objects",
                                                                                                                                objects);
}

LLSD Inspection::value(std::string_view path) const
{ return callEventApi("UI", LLSDMap("op", "getValue")("path", std::string(path))); }

LLSD Inspection::tree(const LLSD& command) const
{
    rebuildControlIndex();
    LLView* root = command.has("path") ? resolvePath(command["path"].asString()) : &mRoot;
    return buildTree(root, mControlIdsByView);
}

LLView* Inspection::pickView(S32 x, S32 y) const
{
    std::vector<LLView*> hits;
    collectHitViews(&mRoot, x, y, hits);
    return hits.empty() ? nullptr : hits.front();
}

LLSD Inspection::pick(S32 x, S32 y) const
{
    if (!mRoot.getLocalRect().pointInRect(x, y))
        throw Error("pick", "screen position is outside the LLUI viewport");
    std::vector<LLView*> hits;
    collectHitViews(&mRoot, x, y, hits);
    LLView* target = hits.empty() ? nullptr : hits.front();
    rebuildControlIndex();
    return describePick(target, hits, x, y, mControlIdsByView);
}

void Inspection::rebuildControlIndex() const
{
    mViewsByControlId.clear();
    mControlIdsByView.clear();
    indexView(&mRoot, "control:0", mViewsByControlId, mControlIdsByView);
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

LLView* Inspection::resolveControlId(std::string_view requested_control_id) const
{
    if (requested_control_id.empty())
        throw Error("control_id", "controlId must not be empty");
    rebuildControlIndex();
    const auto found = mViewsByControlId.find(std::string(requested_control_id));
    if (found == mViewsByControlId.end())
        throw Error("control_id", "view not found: " + std::string(requested_control_id));
    return found->second;
}

std::string Inspection::controlId(LLView* view) const
{
    if (!view)
        return {};
    rebuildControlIndex();
    const auto found = mControlIdsByView.find(view);
    return found == mControlIdsByView.end() ? std::string() : found->second;
}

LLView* Inspection::resolveModelId(const LLUUID& id) const
{
    std::string rejected;
    for (const std::string_view panel_name : inventoryPanelNames())
    {
        LLInventoryPanel* panel = mRoot.findChild<LLInventoryPanel>(panel_name);
        LLFolderViewItem* item  = panel ? panel->getItemByID(id) : nullptr;
        if (!item)
            continue;
        const std::string reason = unusableForInput(*item);
        if (reason.empty())
            return item;
        if (!rejected.empty())
            rejected += "; ";
        rejected += std::string(panel_name) + " " + reason;
    }
    if (!rejected.empty())
        throw Error("model_id", "inventory view item is not usable for input: " + id.asString() + " (" + rejected + ")");
    throw Error("model_id", "inventory view item not found: " + id.asString());
}
} // namespace xui_lab
