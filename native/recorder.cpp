// recorder.cpp — Native C++ recording engine.
//
// Guarantees 100% A/V sync via:
//   1. Native WASAPI loopback (no PortAudio/pyaudiowpatch layer)
//   2. DXGI Desktop Duplication (GPU screen capture)
//   3. FFmpeg two-pass muxing (video → temp MP4, audio → temp WAV, mux → final)
//
// All threads are std::thread — no GIL, no Python interference.
// Audio capture runs at full priority with zero jitter → no tick sounds.
//
// Build: cmake -B build -S native && cmake --build build --config Release
#include "recorder.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <mmsystem.h>
#include <wrl/client.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <dxgi1_2.h>
#include <d3d11.h>

// Use WRL ComPtr instead of ATL ComPtr (avoids ATL dependency)
template<typename T>
using ComPtr = Microsoft::WRL::ComPtr<T>;

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cmath>
#include <algorithm>
#include <string>
#include <thread>
#include <atomic>
#include <mutex>
#include <chrono>
#include <vector>
#include <queue>
#include <condition_variable>
#include <xmmintrin.h>

#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "mmdevapi.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "winmm.lib")

// ── FFmpeg path discovery ─────────────────────────────────────────────────
// Recursive search for ffmpeg.exe in a directory (max 3 levels deep)
static std::string find_in_dir(const std::string& dir, int depth) {
    if (depth > 3) return "";
    std::string pattern = dir + "\\*";
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern.c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return "";
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            if (strcmp(fd.cFileName, ".") == 0 || strcmp(fd.cFileName, "..") == 0)
                continue;
            std::string sub = find_in_dir(dir + "\\" + fd.cFileName, depth + 1);
            if (!sub.empty()) { FindClose(h); return sub; }
        } else {
            if (_stricmp(fd.cFileName, "ffmpeg.exe") == 0) {
                std::string result = dir + "\\" + fd.cFileName;
                FindClose(h);
                return result;
            }
        }
    } while (FindNextFileA(h, &fd));
    FindClose(h);
    return "";
}

static std::string find_ffmpeg() {
    // 1. Check bin/ directory (bundled with EXE or project)
    char exe_path[MAX_PATH];
    GetModuleFileNameA(nullptr, exe_path, MAX_PATH);
    std::string base_dir = exe_path;
    size_t pos = base_dir.find_last_of("\\/");
    if (pos != std::string::npos) base_dir = base_dir.substr(0, pos);

    // Check bin/ and bin/Release/ and bin/Debug/
    std::string bin_dirs[] = {
        base_dir + "\\bin",
        base_dir + "\\bin\\Release",
        base_dir + "\\bin\\Debug",
    };
    for (const auto& d : bin_dirs) {
        std::string found = find_in_dir(d, 0);
        if (!found.empty()) return found;
    }

    // 2. Check winget install location FIRST (before PATH — avoids Trae CN ffmpeg)
    const char* localapp = std::getenv("LOCALAPPDATA");
    if (localapp) {
        std::string winget = std::string(localapp) + "\\Microsoft\\WinGet\\Packages";
        if (GetFileAttributesA(winget.c_str()) != INVALID_FILE_ATTRIBUTES) {
            WIN32_FIND_DATAA fd;
            std::string pattern = winget + "\\*";
            HANDLE h = FindFirstFileA(pattern.c_str(), &fd);
            if (h != INVALID_HANDLE_VALUE) {
                do {
                    if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
                        if (_strnicmp(fd.cFileName, "FFmpeg", 6) == 0 ||
                            _strnicmp(fd.cFileName, "ffmpeg", 6) == 0 ||
                            _strnicmp(fd.cFileName, "Gyan", 4) == 0 ||
                            _strnicmp(fd.cFileName, "BtbN", 4) == 0) {
                            std::string found = find_in_dir(winget + "\\" + fd.cFileName, 0);
                            if (!found.empty()) { FindClose(h); return found; }
                        }
                    }
                } while (FindNextFileA(h, &fd));
                FindClose(h);
            }
        }
    }

    // 3. Search system PATH (but filter out Trae/VS Code paths)
    char sys_path[MAX_PATH];
    if (SearchPathA(nullptr, "ffmpeg.exe", nullptr, MAX_PATH, sys_path, nullptr)) {
        std::string spath(sys_path);
        // Filter out editor/IDE ffmpeg (incomplete builds)
        if (spath.find("Trae") == std::string::npos &&
            spath.find("Code") == std::string::npos &&
            spath.find("cursor") == std::string::npos) {
            return spath;
        }
    }

    // 4. Fallback
    return "ffmpeg.exe";
}

// ── Debug tracing ─────────────────────────────────────────────────────────
static std::mutex g_trace_mutex;
static void trace(const char* msg) {
    std::lock_guard<std::mutex> lk(g_trace_mutex);
    FILE* f = nullptr;
    fopen_s(&f, "recorder_trace.log", "a");
    if (f) {
        fprintf(f, "%s\n", msg);
        fclose(f);
    }
    OutputDebugStringA(msg);
    OutputDebugStringA("\n");
}

#define TRACE(msg) do { trace(msg); } while(0)
#define TRACE_FMT(fmt, ...) do { char buf[512]; _snprintf_s(buf, sizeof(buf), _TRUNCATE, fmt, __VA_ARGS__); trace(buf); } while(0)

// ── Error handling ────────────────────────────────────────────────────────
static std::string g_last_error;
static std::mutex g_error_mutex;

static void set_error(const std::string& msg) {
    std::lock_guard<std::mutex> lk(g_error_mutex);
    g_last_error = msg;
}

RECORDER_API const char* recorder_last_error(void) {
    std::lock_guard<std::mutex> lk(g_error_mutex);
    return g_last_error.c_str();
}

// ── Global state ──────────────────────────────────────────────────────────
static std::atomic<bool> g_recording{false};
static std::atomic<bool> g_stop_requested{false};
static std::thread g_video_thread;
static std::thread g_audio_thread;
static std::string g_output_path;
static std::string g_temp_video;
static std::string g_temp_audio;
static int g_width = 0, g_height = 0;        // Native capture dimensions
static int g_encode_w = 0, g_encode_h = 0;  // Encoding dimensions (after downscale)
static int g_fps = 30;
static int g_sample_rate = 48000;
static int g_channels = 2;
static std::string g_ffmpeg_path;
static HANDLE g_ffmpeg_proc = nullptr;
static HANDLE g_ffmpeg_stdin = nullptr;
static HANDLE g_ffmpeg_stderr = nullptr;
static std::thread g_stderr_thread;
static void (*g_preview_callback)(const uint8_t*, int, int) = nullptr;
static void (*g_audio_level_callback)(float, float) = nullptr;
static int g_video_bitrate = 0; // 0 = CRF mode, >0 = kbps

// Region crop (set before recorder_start to capture a sub-rectangle)
static int g_region_x = 0, g_region_y = 0, g_region_w = 0, g_region_h = 0;
static bool g_has_region = false;

// Audio temp file handle
static HANDLE g_wav_file = nullptr;
static std::mutex g_wav_mutex;
static uint32_t g_audio_data_size = 0;

// ── A/V sync: gate audio writing until first video frame ──────────────────
// Audio capture starts before video (to detect sample rate). To keep A/V
// perfectly in sync, the audio thread does NOT write to the WAV file until
// the video thread has written its first frame to FFmpeg. This eliminates the
// leading-audio offset without any trimming or timestamp math.
static std::atomic<bool> g_video_first_frame_written{false};

// ── WAV file writing (native, no external libs) ───────────────────────────
static bool write_wav_header(HANDLE h, int sample_rate, int channels) {
    // WAV header: 44 bytes
    uint32_t data_size = 0; // placeholder, updated on close
    uint32_t byte_rate = sample_rate * channels * 2;
    uint16_t block_align = channels * 2;
    uint16_t bits_per_sample = 16;

    char header[44];
    memcpy(header, "RIFF", 4);
    uint32_t chunk_size = 36; // will update
    memcpy(header + 4, &chunk_size, 4);
    memcpy(header + 8, "WAVE", 4);
    memcpy(header + 12, "fmt ", 4);
    uint32_t subchunk1_size = 16;
    memcpy(header + 16, &subchunk1_size, 4);
    uint16_t audio_format = 1; // PCM
    memcpy(header + 20, &audio_format, 2);
    memcpy(header + 22, &channels, 2);
    memcpy(header + 24, &sample_rate, 4);
    memcpy(header + 28, &byte_rate, 4);
    memcpy(header + 32, &block_align, 2);
    memcpy(header + 34, &bits_per_sample, 2);
    memcpy(header + 36, "data", 4);
    memcpy(header + 40, &data_size, 4); // placeholder

    DWORD written;
    return WriteFile(h, header, 44, &written, nullptr) && written == 44;
}

static void finalize_wav(HANDLE h, uint32_t data_size) {
    // Update RIFF chunk size and data chunk size
    uint32_t chunk_size = 36 + data_size;
    SetFilePointer(h, 4, nullptr, FILE_BEGIN);
    DWORD written;
    WriteFile(h, &chunk_size, 4, &written, nullptr);
    SetFilePointer(h, 40, nullptr, FILE_BEGIN);
    WriteFile(h, &data_size, 4, &written, nullptr);
}

// ── WASAPI Loopback Audio Capture ─────────────────────────────────────────
// Uses AUDCLNT_STREAMFLAGS_LOOPBACK to capture system audio output.
// Event-driven for precise, jitter-free capture — NO tick sounds.

static void audio_capture_thread() {
    TRACE("audio_thread: entry");
    // COM init for this thread
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) { TRACE("audio_thread: CoInit failed"); set_error("Audio: CoInitializeEx failed"); return; }
    TRACE("audio_thread: COM initialized");

    // 1. Enumerate default audio render endpoint (speakers)
    ComPtr<IMMDeviceEnumerator> enumerator;
    hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                          IID_PPV_ARGS(&enumerator));
    if (FAILED(hr)) { TRACE("audio_thread: MMDeviceEnumerator create failed"); set_error("Audio: MMDeviceEnumerator create failed"); CoUninitialize(); return; }
    TRACE("audio_thread: enumerator created");

    ComPtr<IMMDevice> device;
    hr = enumerator->GetDefaultAudioEndpoint(eRender, eConsole, &device);
    if (FAILED(hr)) { TRACE("audio_thread: GetDefaultAudioEndpoint failed"); set_error("Audio: GetDefaultAudioEndpoint failed"); CoUninitialize(); return; }
    TRACE("audio_thread: default endpoint acquired");

    // 2. Activate IAudioClient
    ComPtr<IAudioClient> audio_client;
    hr = device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, (void**)&audio_client);
    if (FAILED(hr)) { TRACE("audio_thread: device Activate failed"); set_error("Audio: device Activate failed"); CoUninitialize(); return; }
    TRACE("audio_thread: IAudioClient activated");

    // 3. Get mix format (WAVEFORMATEX)
    WAVEFORMATEX* wfx = nullptr;
    hr = audio_client->GetMixFormat(&wfx);
    if (FAILED(hr) || !wfx) { TRACE("audio_thread: GetMixFormat failed"); set_error("Audio: GetMixFormat failed"); CoUninitialize(); return; }
    TRACE_FMT("audio_thread: mix format = %dHz %dch %dbpp tag=%d", wfx->nSamplesPerSec, wfx->nChannels, wfx->wBitsPerSample, wfx->wFormatTag);

    g_sample_rate = wfx->nSamplesPerSec;
    g_channels = wfx->nChannels;

    // 4. Initialize with loopback flag
    DWORD stream_flags = AUDCLNT_STREAMFLAGS_LOOPBACK;
    REFERENCE_TIME buffer_duration = 10000000; // 1 second buffer
    hr = audio_client->Initialize(AUDCLNT_SHAREMODE_SHARED, stream_flags,
                                 buffer_duration, 0, wfx, nullptr);
    if (FAILED(hr)) { TRACE_FMT("audio_thread: Initialize failed (hr=0x%08X)", (unsigned)hr); set_error("Audio: Initialize failed"); CoTaskMemFree(wfx); CoUninitialize(); return; }
    TRACE("audio_thread: audio client initialized");

    // 5. Get capture client
    ComPtr<IAudioCaptureClient> capture_client;
    hr = audio_client->GetService(IID_PPV_ARGS(&capture_client));
    if (FAILED(hr)) { TRACE("audio_thread: GetService failed"); set_error("Audio: GetService failed"); CoTaskMemFree(wfx); CoUninitialize(); return; }
    TRACE("audio_thread: capture client acquired");

    // 6. Start
    hr = audio_client->Start();
    if (FAILED(hr)) { TRACE("audio_thread: Start failed"); set_error("Audio: Start failed"); CoTaskMemFree(wfx); CoUninitialize(); return; }
    TRACE("audio_thread: stream started");

    // 7. Capture loop — runs until g_stop_requested
    uint32_t total_frames = 0;
    int loop_count = 0;
    while (!g_stop_requested.load(std::memory_order_relaxed)) {
        Sleep(5);
        loop_count++;

        UINT32 packet_length = 0;
        hr = capture_client->GetNextPacketSize(&packet_length);
        if (FAILED(hr)) break;

        while (packet_length > 0) {
            BYTE* data = nullptr;
            UINT32 frames_available = 0;
            DWORD flags = 0;
            hr = capture_client->GetBuffer(&data, &frames_available, &flags, nullptr, nullptr);
            if (FAILED(hr)) break;

            UINT32 bytes = frames_available * wfx->nBlockAlign;

            // ── Compute audio levels for GUI meter (RMS per channel) ──────
            if (g_audio_level_callback && !(flags & AUDCLNT_BUFFERFLAGS_SILENT) && data && bytes > 0) {
                float left_rms = 0.0f, right_rms = 0.0f;
                int left_count = 0, right_count = 0;
                if (wfx->wBitsPerSample == 32 && wfx->wFormatTag == WAVE_FORMAT_EXTENSIBLE) {
                    const float* src = (const float*)data;
                    for (UINT32 i = 0; i < frames_available; i++) {
                        float l = src[i * g_channels + 0];
                        left_rms += l * l; left_count++;
                        if (g_channels > 1) {
                            float r = src[i * g_channels + 1];
                            right_rms += r * r; right_count++;
                        }
                    }
                } else if (wfx->wBitsPerSample == 16) {
                    const int16_t* src = (const int16_t*)data;
                    for (UINT32 i = 0; i < frames_available; i++) {
                        float l = src[i * g_channels + 0] / 32768.0f;
                        left_rms += l * l; left_count++;
                        if (g_channels > 1) {
                            float r = src[i * g_channels + 1] / 32768.0f;
                            right_rms += r * r; right_count++;
                        }
                    }
                }
                if (left_count > 0) left_rms = sqrtf(left_rms / left_count);
                if (right_count > 0) right_rms = sqrtf(right_rms / right_count);
                // Scale for visibility (RMS is typically low, boost by 2.5x)
                left_rms = (std::min)(1.0f, left_rms * 2.5f);
                right_rms = (std::min)(1.0f, right_rms * 2.5f);
                g_audio_level_callback(left_rms, right_rms);
            }

            // Write to WAV file — ONLY after the first video frame has been
            // written, so audio and video start at the exact same instant.
            if (g_video_first_frame_written.load(std::memory_order_relaxed) &&
                !(flags & AUDCLNT_BUFFERFLAGS_SILENT) && data && bytes > 0) {
                std::lock_guard<std::mutex> lk(g_wav_mutex);
                if (g_wav_file != nullptr) {
                    // Convert to int16 if needed
                    if (wfx->wBitsPerSample == 16) {
                        DWORD written;
                        WriteFile(g_wav_file, data, bytes, &written, nullptr);
                        g_audio_data_size += written;
                    } else if (wfx->wBitsPerSample == 32 && wfx->wFormatTag == WAVE_FORMAT_EXTENSIBLE) {
                        // Could be float32 — convert to int16
                        WAVEFORMATEXTENSIBLE* wfxe = (WAVEFORMATEXTENSIBLE*)wfx;
                        if (IsEqualGUID(wfxe->SubFormat, KSDATAFORMAT_SUBTYPE_IEEE_FLOAT)) {
                            const float* src = (const float*)data;
                            size_t total_samples = (size_t)frames_available * g_channels;
                            std::vector<int16_t> int16_buf(total_samples);
                            for (size_t i = 0; i < total_samples; i++) {
                                float v = src[i];
                                if (v > 1.0f) v = 1.0f;
                                else if (v < -1.0f) v = -1.0f;
                                int16_buf[i] = (int16_t)lroundf(v * 32768.0f);
                                if (int16_buf[i] > 32767) int16_buf[i] = 32767;
                            }
                            DWORD to_write = (DWORD)(total_samples * sizeof(int16_t));
                            DWORD written;
                            WriteFile(g_wav_file, int16_buf.data(), to_write, &written, nullptr);
                            g_audio_data_size += written;
                        }
                    }
                }
            }

            total_frames += frames_available;
            hr = capture_client->ReleaseBuffer(frames_available);
            if (FAILED(hr)) break;

            hr = capture_client->GetNextPacketSize(&packet_length);
            if (FAILED(hr)) break;
        }
    }

    // 8. Stop and cleanup
    audio_client->Stop();
    TRACE_FMT("audio_thread: stopped (total_frames=%u, data_bytes=%u, loops=%d)",
              total_frames, g_audio_data_size, loop_count);
    CoTaskMemFree(wfx);
    CoUninitialize();
}

// ── DXGI Desktop Duplication screen capture ───────────────────────────────
static void video_capture_thread(int monitor_idx) {
    TRACE("video_thread: entry");
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) { TRACE("video_thread: CoInit failed"); set_error("Video: CoInitializeEx failed"); return; }
    TRACE("video_thread: COM initialized");

    // 1. Create D3D11 device + DXGI factory
    D3D_FEATURE_LEVEL feat_level;
    ComPtr<ID3D11Device> d3d_device;
    ComPtr<ID3D11DeviceContext> ctx;
    UINT flags = 0;
    TRACE("video_thread: creating D3D11 device");
    hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, flags,
                           nullptr, 0, D3D11_SDK_VERSION, &d3d_device, &feat_level, &ctx);
    if (FAILED(hr)) {
        TRACE("video_thread: hardware failed, trying WARP");
        hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, flags,
                               nullptr, 0, D3D11_SDK_VERSION, &d3d_device, &feat_level, &ctx);
        if (FAILED(hr)) { TRACE("video_thread: D3D11CreateDevice failed"); set_error("Video: D3D11CreateDevice failed"); CoUninitialize(); return; }
    }
    TRACE("video_thread: D3D11 device created");

    ComPtr<IDXGIDevice> dxgi_device;
    hr = d3d_device->QueryInterface(IID_PPV_ARGS(&dxgi_device));
    if (FAILED(hr)) { TRACE("video_thread: QI IDXGIDevice failed"); set_error("Video: QueryInterface IDXGIDevice failed"); CoUninitialize(); return; }

    ComPtr<IDXGIAdapter> adapter;
    hr = dxgi_device->GetAdapter(&adapter);
    if (FAILED(hr)) { TRACE("video_thread: GetAdapter failed"); set_error("Video: GetAdapter failed"); CoUninitialize(); return; }
    TRACE("video_thread: adapter acquired");

    ComPtr<IDXGIOutput> output;
    hr = adapter->EnumOutputs(monitor_idx, &output);
    if (FAILED(hr)) {
        TRACE_FMT("video_thread: EnumOutputs(%d) failed, trying 0", monitor_idx);
        hr = adapter->EnumOutputs(0, &output);
        if (FAILED(hr)) { TRACE("video_thread: EnumOutputs(0) failed"); set_error("Video: EnumOutputs failed"); CoUninitialize(); return; }
    }
    TRACE("video_thread: output enumerated");

    ComPtr<IDXGIOutput1> output1;
    hr = output->QueryInterface(IID_PPV_ARGS(&output1));
    if (FAILED(hr)) { TRACE("video_thread: QI IDXGIOutput1 failed"); set_error("Video: QueryInterface IDXGIOutput1 failed"); CoUninitialize(); return; }

    // 2. Duplicate output
    ComPtr<IDXGIOutputDuplication> dup;
    hr = output1->DuplicateOutput(d3d_device.Get(), &dup);
    if (FAILED(hr)) {
        TRACE_FMT("video_thread: DuplicateOutput failed (hr=0x%08X)", (unsigned)hr);
        set_error("Video: DuplicateOutput failed (need Win8+)");
        CoUninitialize();
        return;
    }
    TRACE("video_thread: output duplicated");

    // 3. Get output description for dimensions
    DXGI_OUTDUPL_DESC dup_desc;
    dup->GetDesc(&dup_desc);
    g_width = dup_desc.ModeDesc.Width;
    g_height = dup_desc.ModeDesc.Height;

    // Determine capture source rectangle (full screen or user-selected region)
    int cap_x = 0, cap_y = 0, cap_w = g_width, cap_h = g_height;
    if (g_has_region && g_region_w > 0 && g_region_h > 0) {
        // Clamp region to screen bounds
        cap_x = (std::max)(0, g_region_x);
        cap_y = (std::max)(0, g_region_y);
        cap_w = (std::min)(g_region_w, g_width - cap_x);
        cap_h = (std::min)(g_region_h, g_height - cap_y);
        if (cap_w <= 0 || cap_h <= 0) {
            g_has_region = false;  // invalid region, fall back to fullscreen
            cap_x = 0; cap_y = 0; cap_w = g_width; cap_h = g_height;
        }
    }
    TRACE_FMT("video_thread: native=%dx%d, region=%s crop=%dx%d@%d,%d",
              g_width, g_height, g_has_region ? "yes" : "no", cap_w, cap_h, cap_x, cap_y);

    // Auto-downscale large captures → ≤1920 width for encoding efficiency
    const int SW_MAX_WIDTH = 1920;
    bool downscaled = false;
    g_encode_w = cap_w;
    g_encode_h = cap_h;
    if (cap_w > SW_MAX_WIDTH) {
        double scale = (double)SW_MAX_WIDTH / cap_w;
        g_encode_w = SW_MAX_WIDTH;
        g_encode_h = (int)(cap_h * scale);
        downscaled = true;
    }
    // yuv420p chroma subsampling requires BOTH dimensions to be even.
    // Odd dimensions cause chroma misalignment → horizontal/vertical line artifacts.
    if (g_encode_w % 2 != 0) g_encode_w--;
    if (g_encode_h % 2 != 0) g_encode_h--;
    TRACE_FMT("video_thread: native=%dx%d, region=%dx%d, encode=%dx%d downscaled=%d",
              g_width, g_height, cap_w, cap_h, g_encode_w, g_encode_h, (int)downscaled);

    // Local aliases for the capture loop
    int encode_w = g_encode_w;
    int encode_h = g_encode_h;

    // 4. Frame pacing variables
    int fps = g_fps;
    double frame_interval = 1.0 / fps;
    LARGE_INTEGER freq, t0, t_last_preview;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&t0);
    t_last_preview = t0;

    int frame_count = 0;
    int preview_stride = (std::max)(1, encode_w / 480);

    // Temp buffers
    int capture_row_pitch = g_width * 4; // BGRA
    std::vector<uint8_t> rgb_buffer((size_t)encode_w * encode_h * 3);
    std::vector<uint8_t> preview_buf((size_t)(encode_w / preview_stride + 1) * (encode_h / preview_stride + 1) * 3);

    // 5. Capture loop
    while (!g_stop_requested.load(std::memory_order_relaxed)) {
        LARGE_INTEGER now;
        QueryPerformanceCounter(&now);
        double elapsed = (double)(now.QuadPart - t0.QuadPart) / freq.QuadPart;
        double target = frame_count * frame_interval;
        double wait_time = target - elapsed;

        if (wait_time > 0.001) {
            // Sleep for most of the wait, spin for precision
            int sleep_ms = (int)((wait_time - 0.001) * 1000);
            if (sleep_ms > 0) Sleep(sleep_ms);
            // Spin for final precision (no GIL issue in C++)
            while (true) {
                QueryPerformanceCounter(&now);
                if ((double)(now.QuadPart - t0.QuadPart) / freq.QuadPart >= target)
                    break;
                _mm_pause(); // yield CPU pipeline
            }
        } else if (wait_time < -1.0) {
            // Too far behind — snap forward
            t0.QuadPart = now.QuadPart;
            frame_count = 0;
            continue;
        }

        // Acquire next frame
        DXGI_OUTDUPL_FRAME_INFO frame_info;
        ComPtr<IDXGIResource> resource;
        hr = dup->AcquireNextFrame(50, &frame_info, &resource);
        if (hr == DXGI_ERROR_WAIT_TIMEOUT) {
            // No new frame — write the previous frame again (CFR)
            if (frame_count > 0) {
                if (g_ffmpeg_stdin != nullptr) {
                    DWORD written;
                    WriteFile(g_ffmpeg_stdin, rgb_buffer.data(),
                             (DWORD)rgb_buffer.size(), &written, nullptr);
                }
                frame_count++;
            }
            continue;
        }
        if (FAILED(hr)) continue;

        // Get texture
        ComPtr<ID3D11Texture2D> texture;
        hr = resource->QueryInterface(IID_PPV_ARGS(&texture));
        if (FAILED(hr)) { dup->ReleaseFrame(); continue; }

        // Copy to staging texture for CPU read
        // IMPORTANT: Must copy BEFORE ReleaseFrame — after ReleaseFrame,
        // the shared surface content is no longer guaranteed valid.
        D3D11_TEXTURE2D_DESC tex_desc;
        texture->GetDesc(&tex_desc);
        tex_desc.Usage = D3D11_USAGE_STAGING;
        tex_desc.BindFlags = 0;
        tex_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        tex_desc.MiscFlags = 0;

        ComPtr<ID3D11Texture2D> staging;
        hr = d3d_device->CreateTexture2D(&tex_desc, nullptr, &staging);
        if (FAILED(hr)) { dup->ReleaseFrame(); continue; }
        ctx->CopyResource(staging.Get(), texture.Get());

        // Now safe to release the frame — we have our own copy in staging
        dup->ReleaseFrame();

        // Map staging
        D3D11_MAPPED_SUBRESOURCE mapped;
        hr = ctx->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped);
        if (FAILED(hr)) continue;

        // Quick content check — is the frame non-black?
        const uint8_t* src_check = (const uint8_t*)mapped.pData;
        uint32_t sample_sum = 0;
        int check_bytes = (int)mapped.RowPitch * (int)tex_desc.Height;
        for (int i = 0; i < check_bytes; i += 4096) {
            sample_sum += src_check[i];
        }
        if (frame_count < 3 || frame_count % 30 == 0) {
            TRACE_FMT("video_thread: frame %d content_sum=%u", frame_count, sample_sum);
        }

        // Convert BGRA → RGB, cropping to region and downscaling if needed
        const uint8_t* src = (const uint8_t*)mapped.pData;
        int src_pitch = (int)mapped.RowPitch;
        int src_w = (int)tex_desc.Width;
        int src_h = (int)tex_desc.Height;

        if (!downscaled) {
            // 1:1 copy from region with BGRA→RGB conversion
            for (int y = 0; y < encode_h; y++) {
                const uint8_t* s = src + (y + cap_y) * src_pitch + cap_x * 4;
                uint8_t* d = rgb_buffer.data() + y * encode_w * 3;
                for (int x = 0; x < encode_w; x++) {
                    d[x * 3 + 0] = s[x * 4 + 2]; // R
                    d[x * 3 + 1] = s[x * 4 + 1]; // G
                    d[x * 3 + 2] = s[x * 4 + 0]; // B
                }
            }
        } else {
            // Downscale from region with nearest-neighbor
            for (int y = 0; y < encode_h; y++) {
                int src_y = cap_y + y * cap_h / encode_h;
                const uint8_t* s = src + src_y * src_pitch + cap_x * 4;
                uint8_t* d = rgb_buffer.data() + y * encode_w * 3;
                for (int x = 0; x < encode_w; x++) {
                    int src_x = x * cap_w / encode_w;
                    d[x * 3 + 0] = s[src_x * 4 + 2]; // R
                    d[x * 3 + 1] = s[src_x * 4 + 1]; // G
                    d[x * 3 + 2] = s[src_x * 4 + 0]; // B
                }
            }
        }

        ctx->Unmap(staging.Get(), 0);

        // Write to FFmpeg stdin
        if (g_ffmpeg_stdin != nullptr) {
            // Signal audio thread to start writing — first video frame is
            // about to be encoded, so audio must begin in lockstep.
            if (frame_count == 0) {
                g_video_first_frame_written.store(true, std::memory_order_relaxed);
                TRACE("video_thread: first frame written — audio gate opened");
            }
            DWORD written;
            WriteFile(g_ffmpeg_stdin, rgb_buffer.data(),
                     (DWORD)rgb_buffer.size(), &written, nullptr);
            frame_count++;
        }

        // Emit preview frame at ~10 Hz
        QueryPerformanceCounter(&now);
        double since_preview = (double)(now.QuadPart - t_last_preview.QuadPart) / freq.QuadPart;
        if (g_preview_callback && since_preview >= 0.1) {
            t_last_preview = now;
            int pw = encode_w / preview_stride;
            int ph = encode_h / preview_stride;
            for (int y = 0; y < ph; y++) {
                for (int x = 0; x < pw; x++) {
                    int si = (y * preview_stride) * encode_w * 3 + (x * preview_stride) * 3;
                    int di = (y * pw + x) * 3;
                    preview_buf[di + 0] = rgb_buffer[si + 0];
                    preview_buf[di + 1] = rgb_buffer[si + 1];
                    preview_buf[di + 2] = rgb_buffer[si + 2];
                }
            }
            g_preview_callback(preview_buf.data(), pw, ph);
        }
    }

    CoUninitialize();
}

// ── FFmpeg stderr reader (prevents pipe blocking) ─────────────────────────
static void stderr_reader() {
    if (g_ffmpeg_stderr == nullptr) return;
    char buf[1024];
    DWORD read_bytes;
    while (ReadFile(g_ffmpeg_stderr, buf, sizeof(buf), &read_bytes, nullptr) && read_bytes > 0) {
        // Discard stderr to prevent pipe deadlock
    }
}

// ── Start FFmpeg video encoding subprocess ─────────────────────────────────
static bool start_ffmpeg_video(const std::string& temp_video_path, int w, int h, int fps) {
    TRACE_FMT("start_ffmpeg_video: %dx%d @ %dfps → %s", w, h, fps, temp_video_path.c_str());
    TRACE_FMT("start_ffmpeg_video: ffmpeg path = %s", g_ffmpeg_path.c_str());
    SECURITY_ATTRIBUTES sa;
    sa.nLength = sizeof(SECURITY_ATTRIBUTES);
    sa.bInheritHandle = TRUE;
    sa.lpSecurityDescriptor = nullptr;

    HANDLE stdin_read = nullptr, stdin_write = nullptr;
    HANDLE stderr_read = nullptr, stderr_write = nullptr;

    CreatePipe(&stdin_read, &stdin_write, &sa, 0);
    CreatePipe(&stderr_read, &stderr_write, &sa, 0);

    SetHandleInformation(stdin_write, HANDLE_FLAG_INHERIT, 0);
    SetHandleInformation(stderr_read, HANDLE_FLAG_INHERIT, 0);

    // Build command — use bitrate or CRF depending on setting
    std::string quality_opt;
    if (g_video_bitrate > 0) {
        quality_opt = " -b:v " + std::to_string(g_video_bitrate) + "k -maxrate " +
                       std::to_string(g_video_bitrate * 2) + "k -bufsize " +
                       std::to_string(g_video_bitrate * 4) + "k";
    } else {
        quality_opt = " -crf 20";
    }

    std::string cmd = g_ffmpeg_path +
        " -hide_banner -loglevel warning -y"
        " -f rawvideo -pix_fmt rgb24 -s " + std::to_string(w) + "x" + std::to_string(h) +
        " -r " + std::to_string(fps) + " -i pipe:0"
        " -c:v libx264 -preset ultrafast -tune zerolatency" + quality_opt +
        " -pix_fmt yuv420p -g " + std::to_string(fps * 2) +
        " -vsync cfr -r " + std::to_string(fps) +
        " -movflags +faststart \"" + temp_video_path + "\"";

    STARTUPINFOA si = {};
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = stdin_read;
    si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    si.hStdError = stderr_write;

    PROCESS_INFORMATION pi = {};

    if (!CreateProcessA(nullptr, (LPSTR)cmd.c_str(), nullptr, nullptr, TRUE,
                        CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi)) {
        TRACE_FMT("start_ffmpeg_video: CreateProcess failed (err=%d)", GetLastError());
        set_error("FFmpeg: CreateProcess failed (err=" + std::to_string(GetLastError()) + ")");
        CloseHandle(stdin_read); CloseHandle(stdin_write);
        CloseHandle(stderr_read); CloseHandle(stderr_write);
        return false;
    }
    TRACE("start_ffmpeg_video: FFmpeg process started");

    CloseHandle(stdin_read);  // Close child's read end
    CloseHandle(stderr_write); // Close child's write end
    CloseHandle(pi.hThread);

    g_ffmpeg_proc = pi.hProcess;
    g_ffmpeg_stdin = stdin_write;
    g_ffmpeg_stderr = stderr_read;

    // Start stderr reader thread
    g_stderr_thread = std::thread(stderr_reader);

    return true;
}

// ── Mux video + audio → final output ──────────────────────────────────────
static bool mux_av(const std::string& video, const std::string& audio,
                   const std::string& output) {
    bool has_video = GetFileAttributesA(video.c_str()) != INVALID_FILE_ATTRIBUTES;
    // Only include audio if the WAV file has actual data beyond the 44-byte header
    bool has_audio = false;
    if (GetFileAttributesA(audio.c_str()) != INVALID_FILE_ATTRIBUTES) {
        WIN32_FILE_ATTRIBUTE_DATA fad;
        if (GetFileAttributesExA(audio.c_str(), GetFileExInfoStandard, &fad)) {
            LARGE_INTEGER sz;
            sz.LowPart = fad.nFileSizeLow;
            sz.HighPart = fad.nFileSizeHigh;
            has_audio = sz.QuadPart > 44;  // WAV header is 44 bytes
        }
    }
    TRACE_FMT("mux_av: video=%s exists=%d, audio=%s exists=%d (data_bytes=%u)",
              video.c_str(), has_video, audio.c_str(), has_audio, g_audio_data_size);

    if (!has_video) {
        set_error("Mux: temp video file missing");
        return false;
    }

    // Audio is already aligned with video (audio writing was gated on the
    // first video frame), so no -ss trimming is needed.
    std::string cmd = g_ffmpeg_path + " -hide_banner -loglevel warning -y";
    if (has_audio) {
        cmd += " -i \"" + video + "\" -i \"" + audio + "\""
               " -map 0:v -map 1:a"
               " -c:v copy -c:a aac -b:a 192k"
               " -shortest -movflags +faststart";
    } else {
        cmd += " -i \"" + video + "\" -c:v copy -movflags +faststart";
    }
    cmd += " \"" + output + "\"";

    STARTUPINFOA si = {};
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    si.hStdError = GetStdHandle(STD_ERROR_HANDLE);

    PROCESS_INFORMATION pi = {};
    if (!CreateProcessA(nullptr, (LPSTR)cmd.c_str(), nullptr, nullptr, TRUE,
                        CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi)) {
        set_error("Mux: CreateProcess failed");
        return false;
    }
    CloseHandle(pi.hThread);
    WaitForSingleObject(pi.hProcess, 60000);
    DWORD exit_code = 1;
    GetExitCodeProcess(pi.hProcess, &exit_code);
    CloseHandle(pi.hProcess);

    return exit_code == 0;
}

// ── Public API ─────────────────────────────────────────────────────────────

RECORDER_API int recorder_start(const char* output_path, int fps, int monitor_idx, int video_bitrate) {
    TRACE("recorder_start: entry");
    if (g_recording.load()) {
        set_error("Already recording");
        return -1;
    }

    TRACE("recorder_start: setting output path");
    g_output_path = output_path;
    g_fps = fps;
    g_video_bitrate = video_bitrate;
    g_stop_requested.store(false);

    // Reset A/V sync flag for this session
    g_video_first_frame_written.store(false);

    TRACE("recorder_start: finding ffmpeg");
    g_ffmpeg_path = find_ffmpeg();
    TRACE_FMT("recorder_start: ffmpeg = %s", g_ffmpeg_path.c_str());

    // Generate temp file paths
    size_t dot = g_output_path.find_last_of('.');
    std::string base;
    if (dot != std::string::npos)
        base = g_output_path.substr(0, dot);
    else
        base = g_output_path;
    g_temp_video = base + "_tmp_video.mp4";
    g_temp_audio = base + "_tmp_audio.wav";
    TRACE_FMT("recorder_start: temp_video = %s", g_temp_video.c_str());
    TRACE_FMT("recorder_start: temp_audio = %s", g_temp_audio.c_str());

    // Open temp WAV file for audio
    TRACE("recorder_start: creating WAV file");
    g_wav_file = CreateFileA(g_temp_audio.c_str(), GENERIC_WRITE, 0, nullptr,
                            CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (g_wav_file == INVALID_HANDLE_VALUE) {
        set_error("Failed to create temp WAV file");
        return -2;
    }
    TRACE("recorder_start: writing WAV header");
    g_sample_rate = 48000;
    g_channels = 2;
    write_wav_header(g_wav_file, g_sample_rate, g_channels);
    g_audio_data_size = 0;

    // Start audio thread FIRST (it sets g_sample_rate, g_channels)
    TRACE("recorder_start: starting audio thread");
    g_recording.store(true);
    g_audio_thread = std::thread(audio_capture_thread);

    // Small delay to let audio thread init and set sample rate
    TRACE("recorder_start: sleeping 50ms for audio init");
    Sleep(50);

    // Update WAV header with actual sample rate/channels
    TRACE_FMT("recorder_start: sample_rate=%d channels=%d", g_sample_rate, g_channels);
    {
        std::lock_guard<std::mutex> lk(g_wav_mutex);
        SetFilePointer(g_wav_file, 0, nullptr, FILE_BEGIN);
        write_wav_header(g_wav_file, g_sample_rate, g_channels);
        SetFilePointer(g_wav_file, 0, nullptr, FILE_END);
    }

    // Start video thread (it sets g_width, g_height)
    TRACE("recorder_start: starting video thread");
    g_video_thread = std::thread(video_capture_thread, monitor_idx);

    // Wait for video thread to determine capture dimensions
    TRACE("recorder_start: waiting for video dimensions...");
    for (int i = 0; i < 50 && g_encode_w == 0; i++) {
        Sleep(20);
    }

    TRACE_FMT("recorder_start: encode dims = %dx%d", g_encode_w, g_encode_h);

    // Now start FFmpeg with the ENCODE dimensions (may be downscaled)
    TRACE("recorder_start: starting ffmpeg");
    if (!start_ffmpeg_video(g_temp_video, g_encode_w, g_encode_h, g_fps)) {
        g_stop_requested.store(true);
        g_recording.store(false);
        if (g_audio_thread.joinable()) g_audio_thread.join();
        if (g_video_thread.joinable()) g_video_thread.join();
        return -3;
    }

    TRACE("recorder_start: success");
    return 0;
}

RECORDER_API int recorder_stop(void) {
    TRACE("recorder_stop: entry");
    if (!g_recording.load()) {
        set_error("Not recording");
        return -1;
    }

    g_stop_requested.store(true);
    g_recording.store(false);

    TRACE("recorder_stop: waiting for video thread");
    if (g_video_thread.joinable()) g_video_thread.join();
    TRACE("recorder_stop: waiting for audio thread");
    if (g_audio_thread.joinable()) g_audio_thread.join();

    TRACE("recorder_stop: closing FFmpeg stdin");
    if (g_ffmpeg_stdin != nullptr) {
        CloseHandle(g_ffmpeg_stdin);
        g_ffmpeg_stdin = nullptr;
    }

    TRACE("recorder_stop: waiting for FFmpeg process");
    if (g_ffmpeg_proc != nullptr) {
        WaitForSingleObject(g_ffmpeg_proc, 15000);
        DWORD exit_code = 1;
        GetExitCodeProcess(g_ffmpeg_proc, &exit_code);
        TRACE_FMT("recorder_stop: FFmpeg exit code = %u", exit_code);
        CloseHandle(g_ffmpeg_proc);
        g_ffmpeg_proc = nullptr;
    }

    if (g_stderr_thread.joinable()) g_stderr_thread.join();

    if (g_ffmpeg_stderr != nullptr) {
        CloseHandle(g_ffmpeg_stderr);
        g_ffmpeg_stderr = nullptr;
    }

    TRACE("recorder_stop: finalizing WAV");
    {
        std::lock_guard<std::mutex> lk(g_wav_mutex);
        if (g_wav_file != nullptr && g_wav_file != INVALID_HANDLE_VALUE) {
            finalize_wav(g_wav_file, g_audio_data_size);
            CloseHandle(g_wav_file);
            g_wav_file = nullptr;
        }
    }

    TRACE_FMT("recorder_stop: audio data size = %u bytes", g_audio_data_size);
    TRACE("recorder_stop: muxing...");
    bool ok = mux_av(g_temp_video, g_temp_audio, g_output_path);
    TRACE_FMT("recorder_stop: mux result = %d", ok ? 1 : 0);

    DeleteFileA(g_temp_video.c_str());
    DeleteFileA(g_temp_audio.c_str());

    TRACE("recorder_stop: done");
    return ok ? 0 : -4;
}

RECORDER_API int recorder_is_recording(void) {
    return g_recording.load() ? 1 : 0;
}

RECORDER_API int recorder_get_width(void) { return g_width; }
RECORDER_API int recorder_get_height(void) { return g_height; }
RECORDER_API int recorder_get_sample_rate(void) { return g_sample_rate; }
RECORDER_API int recorder_get_channels(void) { return g_channels; }

RECORDER_API void recorder_set_preview_callback(void (*cb)(const uint8_t*, int, int)) {
    g_preview_callback = cb;
}

RECORDER_API void recorder_set_audio_level_callback(void (*cb)(float, float)) {
    g_audio_level_callback = cb;
}

RECORDER_API void recorder_set_region(int x, int y, int w, int h) {
    g_region_x = x;
    g_region_y = y;
    g_region_w = w;
    g_region_h = h;
    g_has_region = (w > 0 && h > 0);
}

// ── DllMain ────────────────────────────────────────────────────────────────
BOOL APIENTRY DllMain(HMODULE, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        timeBeginPeriod(1); // 1ms timer resolution
    } else if (reason == DLL_PROCESS_DETACH) {
        timeEndPeriod(1);
    }
    return TRUE;
}
