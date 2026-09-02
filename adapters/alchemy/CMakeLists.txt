cmake_minimum_required(VERSION 3.21)

set(alchemy_xui_subject_sources
  alfloaterinventoryexplorer.cpp
  alpanelinventoryexplorer.cpp
  alpanelinventoryholdingtray.cpp
  alpanelinventoryinspector.cpp
  )
list(TRANSFORM alchemy_xui_subject_sources PREPEND "${ALCHEMY_NEWVIEW_SOURCE_DIR}/")

set(alchemy_xui_support_sources)
foreach (source IN LISTS viewer_SOURCE_FILES)
  if (source MATCHES "\\.(c|cc|cpp|cxx|m|mm)$")
    if (IS_ABSOLUTE "${source}")
      list(APPEND alchemy_xui_support_sources "${source}")
    else ()
      list(APPEND alchemy_xui_support_sources "${ALCHEMY_NEWVIEW_SOURCE_DIR}/${source}")
    endif ()
  endif ()
endforeach ()
list(REMOVE_ITEM alchemy_xui_support_sources
  "${ALCHEMY_NEWVIEW_SOURCE_DIR}/llappviewersdl.cpp"
  "${ALCHEMY_NEWVIEW_SOURCE_DIR}/llvoicewebrtc.cpp"
  ${alchemy_xui_subject_sources}
  )

get_target_property(alchemy_viewer_link_libraries ${VIEWER_BINARY_NAME} LINK_LIBRARIES)
list(FILTER alchemy_viewer_link_libraries EXCLUDE REGEX "llwebrtc")

add_library(alchemy_xui_subjects OBJECT ${alchemy_xui_subject_sources})
add_library(alchemy_xui_support STATIC ${alchemy_xui_support_sources})
foreach (target alchemy_xui_subjects alchemy_xui_support)
  target_include_directories(${target} PUBLIC
    "${ALCHEMY_NEWVIEW_SOURCE_DIR}"
    "${ALCHEMY_NEWVIEW_BINARY_DIR}"
    )
  target_precompile_headers(${target} PRIVATE "${ALCHEMY_NEWVIEW_SOURCE_DIR}/llviewerprecompiledheaders.h")
  target_link_libraries(${target} PUBLIC ${alchemy_viewer_link_libraries})
endforeach ()
target_compile_definitions(alchemy_xui_support PRIVATE DISABLE_WEBRTC=1)

add_library(alchemy_newview_ui INTERFACE)
target_include_directories(alchemy_newview_ui INTERFACE
  "${ALCHEMY_NEWVIEW_SOURCE_DIR}"
  "${ALCHEMY_NEWVIEW_BINARY_DIR}"
  )
target_sources(alchemy_newview_ui INTERFACE $<TARGET_OBJECTS:alchemy_xui_subjects>)
target_link_libraries(alchemy_newview_ui INTERFACE
  alchemy_xui_support
  ${alchemy_viewer_link_libraries}
  )

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
