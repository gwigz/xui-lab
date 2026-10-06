#include "llviewerprecompiledheaders.h"

#include "xui_lab_types.h"

#include <set>
#include <stdexcept>

namespace xui_lab
{
const std::vector<ExtensionSubject>& extensionSubjects()
{
    static const auto subjects = []
    {
        std::vector<ExtensionSubject> result;
        appendExtensionSubjects(result);
        std::set<std::string> names{ "test_widgets", "preferences", "inventory_explorer" };
        for (const auto& subject : result)
        {
            if (subject.name.empty() || !subject.makeFixture || !names.insert(subject.name).second)
                throw std::invalid_argument("invalid or duplicate extension subject: " + subject.name);
        }
        return result;
    }();
    return subjects;
}

std::string_view subjectName(const Subject& subject)
{
    if (const auto* extension = std::get_if<const ExtensionSubject*>(&subject))
        return (*extension)->name;
    switch (std::get<BuiltinSubject>(subject))
    {
        case BuiltinSubject::TestWidgets:
            return "test_widgets";
        case BuiltinSubject::InventoryExplorer:
            return "inventory_explorer";
        case BuiltinSubject::Preferences:
            return "preferences";
    }
    throw std::logic_error("unknown built-in subject");
}
} // namespace xui_lab
