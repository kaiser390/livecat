"""NDI receive via ctypes - direct C API call to bypass cyndilib issues."""
import ctypes
import ctypes.wintypes
import os
import sys
import time
import struct

# Force NDI DLL path
NDI_DLL = r"C:\Users\Computer\AppData\Roaming\Python\Python314\site-packages\cyndilib\wrapper\bin\Processing.NDI.Lib.x64.dll"

os.environ['NDILIB_EXTRA_IPS'] = '192.168.123.108'

# Load NDI library
ndi = ctypes.cdll.LoadLibrary(NDI_DLL)

# NDI types
class NDIlib_source_t(ctypes.Structure):
    _fields_ = [
        ("p_ndi_name", ctypes.c_char_p),
        ("p_url_address", ctypes.c_char_p),
    ]

class NDIlib_find_create_t(ctypes.Structure):
    _fields_ = [
        ("show_local_sources", ctypes.c_bool),
        ("p_groups", ctypes.c_char_p),
        ("p_extra_ips", ctypes.c_char_p),
    ]

class NDIlib_recv_create_v3_t(ctypes.Structure):
    _fields_ = [
        ("source_to_connect_to", NDIlib_source_t),
        ("color_format", ctypes.c_int),  # NDIlib_recv_color_format_e
        ("bandwidth", ctypes.c_int),     # NDIlib_recv_bandwidth_e
        ("allow_video_fields", ctypes.c_bool),
        ("p_ndi_recv_name", ctypes.c_char_p),
    ]

class NDIlib_video_frame_v2_t(ctypes.Structure):
    _fields_ = [
        ("xres", ctypes.c_int),
        ("yres", ctypes.c_int),
        ("FourCC", ctypes.c_int),
        ("frame_rate_N", ctypes.c_int),
        ("frame_rate_D", ctypes.c_int),
        ("picture_aspect_ratio", ctypes.c_float),
        ("frame_format_type", ctypes.c_int),
        ("timecode", ctypes.c_int64),
        ("p_data", ctypes.c_void_p),
        ("line_stride_in_bytes", ctypes.c_int),
        ("p_metadata", ctypes.c_char_p),
        ("timestamp", ctypes.c_int64),
    ]

class NDIlib_audio_frame_v3_t(ctypes.Structure):
    _fields_ = [
        ("sample_rate", ctypes.c_int),
        ("no_channels", ctypes.c_int),
        ("no_samples", ctypes.c_int),
        ("timecode", ctypes.c_int64),
        ("FourCC", ctypes.c_int),
        ("p_data", ctypes.c_void_p),
        ("channel_stride_in_bytes", ctypes.c_int),
        ("p_metadata", ctypes.c_char_p),
        ("timestamp", ctypes.c_int64),
    ]

class NDIlib_metadata_frame_t(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_int),
        ("timecode", ctypes.c_int64),
        ("p_data", ctypes.c_char_p),
    ]

# Frame types
NDIlib_frame_type_none = 0
NDIlib_frame_type_video = 1
NDIlib_frame_type_audio = 2
NDIlib_frame_type_metadata = 3
NDIlib_frame_type_error = 4
NDIlib_frame_type_status_change = 100

# Color formats
NDIlib_recv_color_format_BGRX_BGRA = 0
NDIlib_recv_color_format_UYVY_BGRA = 1
NDIlib_recv_color_format_RGBX_RGBA = 2
NDIlib_recv_color_format_best = 101

# Bandwidth
NDIlib_recv_bandwidth_highest = 100

def main():
    # Initialize NDI
    print("Initializing NDI...", flush=True)
    if not ndi.NDIlib_initialize():
        print("NDI init failed!")
        return

    print(f"NDI initialized OK", flush=True)

    # Create finder
    find_create = NDIlib_find_create_t()
    find_create.show_local_sources = True
    find_create.p_groups = None
    find_create.p_extra_ips = b"192.168.123.108"

    finder = ndi.NDIlib_find_create_v2(ctypes.byref(find_create))
    if not finder:
        print("Failed to create finder")
        ndi.NDIlib_destroy()
        return

    print("Finder created. Searching...", flush=True)

    # Wait for sources
    sources = None
    num_sources = ctypes.c_uint32(0)

    for i in range(6):
        ndi.NDIlib_find_wait_for_sources(finder, 5000)
        ndi.NDIlib_find_get_current_sources.restype = ctypes.POINTER(NDIlib_source_t)
        sources_ptr = ndi.NDIlib_find_get_current_sources(finder, ctypes.byref(num_sources))
        n = num_sources.value
        print(f"  [{(i+1)*5}s] Found {n} sources", flush=True)

        if n > 0:
            for j in range(n):
                src = sources_ptr[j]
                name = src.p_ndi_name.decode('utf-8') if src.p_ndi_name else 'N/A'
                url = src.p_url_address.decode('utf-8') if src.p_url_address else 'N/A'
                print(f"    [{j}] name={name}, url={url}", flush=True)
            break

    if num_sources.value == 0:
        print("No sources found!")
        ndi.NDIlib_find_destroy(finder)
        ndi.NDIlib_destroy()
        return

    # Get first source
    source = sources_ptr[0]
    src_name = source.p_ndi_name.decode('utf-8') if source.p_ndi_name else ''
    src_url = source.p_url_address.decode('utf-8') if source.p_url_address else ''
    print(f"\nConnecting to: {src_name} @ {src_url}", flush=True)

    # If URL is localhost, try to fix it
    if 'localhost' in src_url.lower() or '127.0.0.1' in src_url:
        # Replace localhost with actual iPhone IP
        fixed_url = src_url.replace('localhost', '192.168.123.108').replace('127.0.0.1', '192.168.123.108').replace('LOCALHOST', '192.168.123.108')
        print(f"  Fixing URL: {src_url} -> {fixed_url}", flush=True)
        source.p_url_address = fixed_url.encode('utf-8')

    # Create receiver
    recv_create = NDIlib_recv_create_v3_t()
    recv_create.source_to_connect_to = source
    recv_create.color_format = NDIlib_recv_color_format_BGRX_BGRA
    recv_create.bandwidth = NDIlib_recv_bandwidth_highest
    recv_create.allow_video_fields = True
    recv_create.p_ndi_recv_name = b"LiveCat Receiver"

    recv = ndi.NDIlib_recv_create_v3(ctypes.byref(recv_create))
    if not recv:
        print("Failed to create receiver")
        ndi.NDIlib_find_destroy(finder)
        ndi.NDIlib_destroy()
        return

    print("Receiver created!", flush=True)

    # Connect
    ndi.NDIlib_recv_connect(recv, ctypes.byref(source))
    print("Connected. Receiving frames...", flush=True)

    ndi.NDIlib_find_destroy(finder)

    # Receive frames
    video = NDIlib_video_frame_v2_t()
    audio = NDIlib_audio_frame_v3_t()
    meta = NDIlib_metadata_frame_t()

    frame_count = 0
    start = time.time()
    max_time = 30

    while time.time() - start < max_time:
        elapsed = time.time() - start

        frame_type = ndi.NDIlib_recv_capture_v3(
            recv,
            ctypes.byref(video),
            ctypes.byref(audio),
            ctypes.byref(meta),
            1000  # timeout ms
        )

        if frame_type == NDIlib_frame_type_video:
            frame_count += 1
            fps = frame_count / elapsed if elapsed > 0 else 0
            fourcc_bytes = struct.pack('<I', video.FourCC)
            print(f"  VIDEO #{frame_count}: {video.xres}x{video.yres} "
                  f"FourCC={fourcc_bytes} stride={video.line_stride_in_bytes} "
                  f"{fps:.1f}fps", flush=True)

            # Free the video frame
            ndi.NDIlib_recv_free_video_v2(recv, ctypes.byref(video))

            if frame_count >= 10:
                import numpy as np
                # Get frame data as numpy array
                buf_size = video.yres * video.line_stride_in_bytes
                if video.p_data and buf_size > 0:
                    arr = np.ctypeslib.as_array(
                        ctypes.cast(video.p_data, ctypes.POINTER(ctypes.c_uint8)),
                        shape=(video.yres, video.line_stride_in_bytes)
                    )
                    print(f"  -> numpy shape={arr.shape}", flush=True)
                break

        elif frame_type == NDIlib_frame_type_audio:
            if frame_count == 0 and int(elapsed) % 5 == 0:
                print(f"  [{elapsed:.0f}s] Audio: {audio.sample_rate}Hz, "
                      f"{audio.no_channels}ch, {audio.no_samples} samples", flush=True)
            ndi.NDIlib_recv_free_audio_v3(recv, ctypes.byref(audio))

        elif frame_type == NDIlib_frame_type_metadata:
            meta_str = meta.p_data.decode('utf-8') if meta.p_data else ''
            print(f"  [{elapsed:.0f}s] Metadata: {meta_str[:100]}", flush=True)
            ndi.NDIlib_recv_free_metadata(recv, ctypes.byref(meta))

        elif frame_type == NDIlib_frame_type_status_change:
            print(f"  [{elapsed:.0f}s] Status change", flush=True)

        elif frame_type == NDIlib_frame_type_error:
            print(f"  [{elapsed:.0f}s] ERROR frame", flush=True)

        elif frame_type == NDIlib_frame_type_none:
            if int(elapsed) % 5 == 0 and frame_count == 0:
                nconn = ndi.NDIlib_recv_get_no_connections(recv)
                print(f"  [{elapsed:.0f}s] No frame. Connections: {nconn}", flush=True)
                time.sleep(1)

    ndi.NDIlib_recv_destroy(recv)
    ndi.NDIlib_destroy()
    total = time.time() - start
    print(f"\nDone: {frame_count} video frames in {total:.1f}s", flush=True)


if __name__ == "__main__":
    main()
