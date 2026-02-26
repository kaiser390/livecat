"""NDI receive via ctypes with proper function signatures."""
import ctypes
import os
import sys
import time
import struct

NDI_DLL = r"C:\Users\Computer\AppData\Roaming\Python\Python314\site-packages\cyndilib\wrapper\bin\Processing.NDI.Lib.x64.dll"

os.environ['NDILIB_EXTRA_IPS'] = '192.168.123.108'

ndi = ctypes.cdll.LoadLibrary(NDI_DLL)

# Opaque handle type
NDI_HANDLE = ctypes.c_void_p


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
        ("color_format", ctypes.c_int),
        ("bandwidth", ctypes.c_int),
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
FRAME_TYPE_NONE = 0
FRAME_TYPE_VIDEO = 1
FRAME_TYPE_AUDIO = 2
FRAME_TYPE_METADATA = 3
FRAME_TYPE_ERROR = 4
FRAME_TYPE_STATUS_CHANGE = 100

# Set function signatures
ndi.NDIlib_initialize.restype = ctypes.c_bool
ndi.NDIlib_initialize.argtypes = []

ndi.NDIlib_destroy.restype = None
ndi.NDIlib_destroy.argtypes = []

ndi.NDIlib_find_create_v2.restype = NDI_HANDLE
ndi.NDIlib_find_create_v2.argtypes = [ctypes.POINTER(NDIlib_find_create_t)]

ndi.NDIlib_find_destroy.restype = None
ndi.NDIlib_find_destroy.argtypes = [NDI_HANDLE]

ndi.NDIlib_find_wait_for_sources.restype = ctypes.c_bool
ndi.NDIlib_find_wait_for_sources.argtypes = [NDI_HANDLE, ctypes.c_uint32]

ndi.NDIlib_find_get_current_sources.restype = ctypes.POINTER(NDIlib_source_t)
ndi.NDIlib_find_get_current_sources.argtypes = [NDI_HANDLE, ctypes.POINTER(ctypes.c_uint32)]

ndi.NDIlib_recv_create_v3.restype = NDI_HANDLE
ndi.NDIlib_recv_create_v3.argtypes = [ctypes.POINTER(NDIlib_recv_create_v3_t)]

ndi.NDIlib_recv_destroy.restype = None
ndi.NDIlib_recv_destroy.argtypes = [NDI_HANDLE]

ndi.NDIlib_recv_connect.restype = None
ndi.NDIlib_recv_connect.argtypes = [NDI_HANDLE, ctypes.POINTER(NDIlib_source_t)]

ndi.NDIlib_recv_capture_v3.restype = ctypes.c_int
ndi.NDIlib_recv_capture_v3.argtypes = [
    NDI_HANDLE,
    ctypes.POINTER(NDIlib_video_frame_v2_t),
    ctypes.POINTER(NDIlib_audio_frame_v3_t),
    ctypes.POINTER(NDIlib_metadata_frame_t),
    ctypes.c_uint32,
]

ndi.NDIlib_recv_free_video_v2.restype = None
ndi.NDIlib_recv_free_video_v2.argtypes = [NDI_HANDLE, ctypes.POINTER(NDIlib_video_frame_v2_t)]

ndi.NDIlib_recv_free_audio_v3.restype = None
ndi.NDIlib_recv_free_audio_v3.argtypes = [NDI_HANDLE, ctypes.POINTER(NDIlib_audio_frame_v3_t)]

ndi.NDIlib_recv_free_metadata.restype = None
ndi.NDIlib_recv_free_metadata.argtypes = [NDI_HANDLE, ctypes.POINTER(NDIlib_metadata_frame_t)]

ndi.NDIlib_recv_get_no_connections.restype = ctypes.c_int
ndi.NDIlib_recv_get_no_connections.argtypes = [NDI_HANDLE]


def main():
    print("=== NDI Raw C API Test ===", flush=True)

    if not ndi.NDIlib_initialize():
        print("NDI init failed!")
        return

    print("NDI initialized.", flush=True)

    # Create finder
    fc = NDIlib_find_create_t()
    fc.show_local_sources = True
    fc.p_groups = None
    fc.p_extra_ips = b"192.168.123.108"

    finder = ndi.NDIlib_find_create_v2(ctypes.byref(fc))
    if not finder:
        print("Finder creation failed!")
        ndi.NDIlib_destroy()
        return

    print("Searching for sources...", flush=True)

    num = ctypes.c_uint32(0)
    sources_ptr = None

    for i in range(6):
        ndi.NDIlib_find_wait_for_sources(finder, 5000)
        sources_ptr = ndi.NDIlib_find_get_current_sources(finder, ctypes.byref(num))
        n = num.value
        print(f"  [{(i+1)*5}s] Found {n} sources", flush=True)
        if n > 0:
            for j in range(n):
                s = sources_ptr[j]
                name = s.p_ndi_name.decode('utf-8', errors='replace') if s.p_ndi_name else 'N/A'
                url = s.p_url_address.decode('utf-8', errors='replace') if s.p_url_address else 'N/A'
                print(f"    [{j}] name='{name}' url='{url}'", flush=True)
            break

    if num.value == 0:
        print("No sources!")
        ndi.NDIlib_find_destroy(finder)
        ndi.NDIlib_destroy()
        return

    # Get source info
    src = sources_ptr[0]
    src_name = src.p_ndi_name.decode('utf-8', errors='replace') if src.p_ndi_name else ''
    src_url = src.p_url_address.decode('utf-8', errors='replace') if src.p_url_address else ''
    print(f"\nSource: name='{src_name}' url='{src_url}'", flush=True)

    # Fix LOCALHOST URL
    original_url = src_url
    if src_url and ('localhost' in src_url.lower() or 'LOCALHOST' in src_url):
        fixed = src_url.replace('LOCALHOST', '192.168.123.108').replace('localhost', '192.168.123.108')
        print(f"  Fixing URL: '{src_url}' -> '{fixed}'", flush=True)
        src.p_url_address = fixed.encode('utf-8')
        src_url = fixed

    # Create receiver
    rc = NDIlib_recv_create_v3_t()
    rc.source_to_connect_to = src
    rc.color_format = 0  # BGRX_BGRA
    rc.bandwidth = 100   # highest
    rc.allow_video_fields = True
    rc.p_ndi_recv_name = b"LiveCat"

    recv = ndi.NDIlib_recv_create_v3(ctypes.byref(rc))
    if not recv:
        print("Receiver creation failed!")
        ndi.NDIlib_find_destroy(finder)
        ndi.NDIlib_destroy()
        return

    # Connect
    ndi.NDIlib_recv_connect(recv, ctypes.byref(src))
    ndi.NDIlib_find_destroy(finder)

    time.sleep(1)
    nconn = ndi.NDIlib_recv_get_no_connections(recv)
    print(f"Receiver created. Connections: {nconn}", flush=True)
    print("Receiving frames (30s)...", flush=True)

    # Receive
    video = NDIlib_video_frame_v2_t()
    audio = NDIlib_audio_frame_v3_t()
    meta = NDIlib_metadata_frame_t()

    frame_count = 0
    audio_count = 0
    start = time.time()

    while time.time() - start < 30:
        elapsed = time.time() - start

        ft = ndi.NDIlib_recv_capture_v3(
            recv, ctypes.byref(video), ctypes.byref(audio),
            ctypes.byref(meta), 1000
        )

        if ft == FRAME_TYPE_VIDEO:
            frame_count += 1
            fps = frame_count / elapsed if elapsed > 0 else 0
            try:
                fourcc_bytes = struct.pack('<I', video.FourCC).decode('ascii', errors='replace')
            except:
                fourcc_bytes = f"0x{video.FourCC:08x}"
            print(f"  VIDEO #{frame_count}: {video.xres}x{video.yres} "
                  f"fourcc={fourcc_bytes} stride={video.line_stride_in_bytes} "
                  f"data={'YES' if video.p_data else 'NULL'} {fps:.1f}fps", flush=True)
            ndi.NDIlib_recv_free_video_v2(recv, ctypes.byref(video))

            if frame_count >= 10:
                break

        elif ft == FRAME_TYPE_AUDIO:
            audio_count += 1
            if audio_count <= 3 or audio_count % 50 == 0:
                print(f"  AUDIO #{audio_count}: {audio.sample_rate}Hz {audio.no_channels}ch "
                      f"{audio.no_samples}smp", flush=True)
            ndi.NDIlib_recv_free_audio_v3(recv, ctypes.byref(audio))

        elif ft == FRAME_TYPE_METADATA:
            md = meta.p_data.decode('utf-8', errors='replace') if meta.p_data else ''
            print(f"  META: {md[:200]}", flush=True)
            ndi.NDIlib_recv_free_metadata(recv, ctypes.byref(meta))

        elif ft == FRAME_TYPE_STATUS_CHANGE:
            nconn = ndi.NDIlib_recv_get_no_connections(recv)
            print(f"  STATUS_CHANGE: connections={nconn}", flush=True)

        elif ft == FRAME_TYPE_NONE:
            if int(elapsed) % 5 == 0 and frame_count == 0:
                nconn = ndi.NDIlib_recv_get_no_connections(recv)
                print(f"  [{elapsed:.0f}s] Waiting... connections={nconn}", flush=True)
                time.sleep(1)

    ndi.NDIlib_recv_destroy(recv)
    ndi.NDIlib_destroy()
    total = time.time() - start
    print(f"\n=== Result: {frame_count} video, {audio_count} audio in {total:.1f}s ===", flush=True)


if __name__ == "__main__":
    main()
