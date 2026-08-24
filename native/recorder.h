// recorder.h — Native C++ recording engine for guaranteed A/V sync.
//
// Exports a C ABI (extern "C") so it can be called from Python via ctypes.
//
// Architecture:
//   - WASAPI loopback capture (direct COM API, no PortAudio layer)
//   - DXGI Desktop Duplication for screen capture (GPU)
//   - FFmpeg subprocess encodes rawvideo from stdin → temp_video.mp4
//   - Audio written to temp_audio.wav (native, no queue drops)
//   - FFmpeg muxes both → final output.mp4
//
// All threads are native C++ std::thread — NO GIL, NO Python interference.
// This eliminates audio tick-tick spikes caused by Python's GIL starvation.
#pragma once

#include <stdint.h>

#ifdef _WIN32
#  define RECORDER_API __declspec(dllexport)
#else
#  define RECORDER_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

/// Start recording.
/// @param output_path    Full path for final MP4 output (UTF-8).
/// @param fps            Target frame rate (e.g. 30).
/// @param monitor_idx    Monitor index (0 = primary).
/// @param video_bitrate  Video bitrate in kbps. 0 = use CRF (constant quality).
/// @returns 0 on success, negative on error.
RECORDER_API int recorder_start(const char* output_path, int fps, int monitor_idx, int video_bitrate);

/// Stop recording and mux audio+video into final output.
/// Blocking — waits for FFmpeg to finish.
/// @returns 0 on success, negative on error.
RECORDER_API int recorder_stop(void);

/// Check if recording is active.
/// @returns 1 if recording, 0 otherwise.
RECORDER_API int recorder_is_recording(void);

/// Get the last error message (UTF-8, thread-local buffer).
/// @returns Pointer to a static string describing the last error.
RECORDER_API const char* recorder_last_error(void);

/// Get the actual capture width/height (set after recorder_start).
RECORDER_API int recorder_get_width(void);
RECORDER_API int recorder_get_height(void);
RECORDER_API int recorder_get_sample_rate(void);
RECORDER_API int recorder_get_channels(void);

/// Set a callback for preview frames (called from video thread at ~10 Hz).
/// @param cb  Function pointer: void cb(const uint8_t* rgb_data, int width, int height)
///            Called with a downscaled RGB frame. Data is valid only during the call.
///            Pass NULL to disable preview.
RECORDER_API void recorder_set_preview_callback(void (*cb)(const uint8_t*, int, int));

/// Set a callback for audio level updates (called from audio thread at ~20 Hz).
/// @param cb  Function pointer: void cb(float left, float right)
///            Called with RMS levels (0.0–1.0) for left and right channels.
///            Pass NULL to disable.
RECORDER_API void recorder_set_audio_level_callback(void (*cb)(float, float));

/// Set the capture region (crop rectangle) before calling recorder_start.
/// Call with w=0 and h=0 to reset to fullscreen capture.
/// @param x  Region left edge (screen coords, pixels)
/// @param y  Region top edge (screen coords, pixels)
/// @param w  Region width (pixels)
/// @param h  Region height (pixels)
RECORDER_API void recorder_set_region(int x, int y, int w, int h);

#ifdef __cplusplus
} // extern "C"
#endif
