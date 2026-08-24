cmake_minimum_required(VERSION 3.15)
project(recorder_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_WINDOWS_EXPORT_ALL_SYMBOLS OFF)

# Use static CRT (/MT) so the DLL has no external VCRUNTIME140.dll dependency.
# This prevents "DLL not found" crashes when bundled in PyInstaller EXE.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded")

# Build as shared library (DLL) for ctypes
add_library(recorder SHARED recorder.cpp)

# Link Windows libraries
target_link_libraries(recorder PRIVATE
    ole32
    mmdevapi
    dxgi
    d3d11
    winmm
)

# Output to bin/ directory
set_target_properties(recorder PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/../bin"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/../bin"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/../bin"
    OUTPUT_NAME "recorder"
    PREFIX ""
)

# Release build optimizations
# Note: /arch:AVX2 removed — caused access violation on some machines due to
# stack alignment issues with ctypes interop. /O2 is sufficient.
target_compile_options(recorder PRIVATE
    $<$<CONFIG:Release>:/O2>
)

# Include directory
target_include_directories(recorder PRIVATE ${CMAKE_SOURCE_DIR})

# Suppress CRT secure warnings
target_compile_definitions(recorder PRIVATE
    _CRT_SECURE_NO_WARNINGS
    NOMINMAX
    WIN32_LEAN_AND_MEAN
    UNICODE
    _UNICODE
)
