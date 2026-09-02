if (NOT TARGET "${VIEWER_BINARY_NAME}")
  message(FATAL_ERROR "Alchemy production target is unavailable: ${VIEWER_BINARY_NAME}")
endif ()

set(alchemy_xui_adapter_source_dir "${CMAKE_CURRENT_LIST_DIR}")
get_target_property(alchemy_newview_sources ${VIEWER_BINARY_NAME} SOURCES)
get_target_property(alchemy_newview_source_dir ${VIEWER_BINARY_NAME} SOURCE_DIR)
get_target_property(alchemy_newview_binary_dir ${VIEWER_BINARY_NAME} BINARY_DIR)
get_target_property(alchemy_viewer_link_libraries ${VIEWER_BINARY_NAME} LINK_LIBRARIES)
get_target_property(alchemy_viewer_runtime_dir ${VIEWER_BINARY_NAME} RUNTIME_OUTPUT_DIRECTORY)

set(alchemy_xui_subject_sources
  alfloaterinventoryexplorer.cpp
  alpanelinventoryexplorer.cpp
  alpanelinventoryholdingtray.cpp
  alpanelinventoryinspector.cpp
  )
list(TRANSFORM alchemy_xui_subject_sources PREPEND "${alchemy_newview_source_dir}/")

set(alchemy_xui_support_sources)
foreach (source IN LISTS alchemy_newview_sources)
  if (source MATCHES "\\.(c|cc|cpp|cxx|m|mm)$")
    if (IS_ABSOLUTE "${source}")
      list(APPEND alchemy_xui_support_sources "${source}")
    else ()
      list(APPEND alchemy_xui_support_sources "${alchemy_newview_source_dir}/${source}")
    endif ()
  endif ()
endforeach ()
list(REMOVE_ITEM alchemy_xui_support_sources
  "${alchemy_newview_source_dir}/llappviewersdl.cpp"
  "${alchemy_newview_source_dir}/llvoicewebrtc.cpp"
  ${alchemy_xui_subject_sources}
  )

list(FILTER alchemy_viewer_link_libraries EXCLUDE REGEX "llwebrtc")

add_library(alchemy_xui_subjects OBJECT ${alchemy_xui_subject_sources})
add_library(alchemy_xui_support STATIC ${alchemy_xui_support_sources})
foreach (target alchemy_xui_subjects alchemy_xui_support)
  target_include_directories(${target} PUBLIC
    "${alchemy_newview_source_dir}"
    "${alchemy_newview_binary_dir}"
    )
  target_precompile_headers(${target} PRIVATE "${alchemy_newview_source_dir}/llviewerprecompiledheaders.h")
  target_link_libraries(${target} PUBLIC ${alchemy_viewer_link_libraries})
endforeach ()
target_compile_definitions(alchemy_xui_support PRIVATE DISABLE_WEBRTC=1)

add_library(alchemy_newview_ui INTERFACE)
target_include_directories(alchemy_newview_ui INTERFACE
  "${alchemy_newview_source_dir}"
  "${alchemy_newview_binary_dir}"
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

set(alchemy_xui_adapter_sources
  xui_lab_event_api.cpp
  xui_lab_inspection.cpp
  xui_lab_inventory_fixture.cpp
  xui_lab_main.cpp
  xui_lab_runtime.cpp
  xui_lab_ui_host.cpp
  )
list(TRANSFORM alchemy_xui_adapter_sources PREPEND "${alchemy_xui_adapter_source_dir}/")

add_executable(xui-lab ${alchemy_xui_adapter_sources})
target_compile_features(xui-lab PRIVATE cxx_std_20)
target_compile_definitions(xui-lab PRIVATE
  XUI_LAB_FORK="alchemy"
  XUI_LAB_FORK_COMMIT="${XUI_LAB_FORK_COMMIT}"
  )
target_include_directories(xui-lab PRIVATE
  "${alchemy_newview_source_dir}"
  "${alchemy_newview_binary_dir}"
  )
target_link_libraries(xui-lab PRIVATE alchemy_newview_ui)
if (APPLE)
  target_link_options(xui-lab PRIVATE "LINKER:-force_load,$<TARGET_FILE:llui>")
endif ()
set_target_properties(xui-lab PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${alchemy_viewer_runtime_dir}"
  )
