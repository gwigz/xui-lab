include_guard(GLOBAL)

# Keep LLView's inspection-only layout consistent across every Alchemy target.
add_compile_definitions(LLUI_ENABLE_VIEW_INSPECTION=1)

# The project include runs before Alchemy defines its targets. Load the adapter
# at the end of the root directory, when the production viewer target exists.
set(xui_lab_alchemy_adapter_file "${CMAKE_CURRENT_LIST_DIR}/CMakeLists.txt")
cmake_language(EVAL CODE "
  cmake_language(
    DEFER ID xui_lab_alchemy_adapter
    CALL include [[${xui_lab_alchemy_adapter_file}]]
  )
")
