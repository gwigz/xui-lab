# Emit xui_lab_fork_identity.cpp from a 40-character hex SHA stamp.

if(NOT DEFINED COMMIT_FILE OR NOT DEFINED OUTPUT_FILE)
  message(FATAL_ERROR "COMMIT_FILE and OUTPUT_FILE are required")
endif()
if(NOT EXISTS "${COMMIT_FILE}")
  message(FATAL_ERROR "fork commit stamp is missing: ${COMMIT_FILE}")
endif()

file(READ "${COMMIT_FILE}" _commit)
string(STRIP "${_commit}" _commit)
string(LENGTH "${_commit}" _len)
if(NOT _len EQUAL 40 OR NOT _commit MATCHES "^[0-9a-f]+$")
  message(FATAL_ERROR "fork commit stamp must be a 40-character lowercase hex SHA: ${COMMIT_FILE}")
endif()

configure_file("${CMAKE_CURRENT_LIST_DIR}/xui_lab_fork_identity.cpp.in" "${OUTPUT_FILE}" @ONLY)
