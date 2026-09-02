cmake_minimum_required(VERSION 3.21)

if (NOT TARGET alchemy_newview_ui)
  message(FATAL_ERROR "The Alchemy production UI target is required")
endif ()

string(LENGTH "${XUI_LAB_FORK_COMMIT}" XUI_LAB_FORK_COMMIT_LENGTH)
if (NOT XUI_LAB_FORK_COMMIT_LENGTH EQUAL 40 OR NOT XUI_LAB_FORK_COMMIT MATCHES "^[0-9a-f]+$")
  message(FATAL_ERROR "XUI_LAB_FORK_COMMIT must be the selected viewer commit")
endif ()

add_executable(xui-lab
  xui_lab_event_api.cpp
  xui_lab_inspection.cpp
  xui_lab_inventory_fixture.cpp
  xui_lab_main.cpp
  xui_lab_runtime.cpp
  xui_lab_ui_host.cpp
  )
target_compile_features(xui-lab PRIVATE cxx_std_20)
target_compile_definitions(xui-lab PRIVATE
  XUI_LAB_FORK="alchemy"
  XUI_LAB_FORK_COMMIT="${XUI_LAB_FORK_COMMIT}"
  )
target_include_directories(xui-lab PRIVATE
  "${CMAKE_SOURCE_DIR}/newview"
  "${CMAKE_BINARY_DIR}/newview"
  )
target_link_libraries(xui-lab PRIVATE alchemy_newview_ui)
if (APPLE)
  target_link_options(xui-lab PRIVATE "LINKER:-force_load,$<TARGET_FILE:llui>")
endif ()
set_target_properties(xui-lab PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${VIEWER_STAGING_DIR}"
  )
