#pragma once

#include "llsd.h"
#include "lluuid.h"

#include <string>
#include <variant>
#include <vector>

namespace xui_lab
{
struct AgentFixture
{
    LLUUID      id;
    std::string name;
};

struct AvatarNameFixture
{
    LLUUID      id;
    std::string user_name;
    std::string display_name;
};

enum class InventoryCategoryKind
{
    Root,
    Folder
};

struct InventoryCategoryFixture
{
    InventoryCategoryKind kind;
    LLUUID                id;
    LLUUID                parent_id;
    std::string           name;
};

struct InventoryNotecardFixture
{
    LLUUID      id;
    LLUUID      parent_id;
    std::string name;
};

using InventoryObjectFixture = std::variant<InventoryCategoryFixture, InventoryNotecardFixture>;

struct InventoryFixtureData
{
    std::string                         id;
    AgentFixture                        agent;
    std::vector<AvatarNameFixture>      avatar_names;
    std::vector<InventoryObjectFixture> inventory;
};

[[nodiscard]] InventoryFixtureData parseInventoryFixture(const LLSD& fixture);

class InventoryFixture final
{
public:
    explicit InventoryFixture(InventoryFixtureData fixture);
    ~InventoryFixture();

    InventoryFixture(const InventoryFixture&)            = delete;
    InventoryFixture& operator=(const InventoryFixture&) = delete;

    [[nodiscard]] const std::string&         id() const noexcept { return mId; }
    [[nodiscard]] const std::vector<LLUUID>& objectIds() const noexcept { return mObjectIds; }

private:
    void cleanup() noexcept;

    std::string         mId;
    std::vector<LLUUID> mObjectIds;
    bool                mActive = false;
};
} // namespace xui_lab
