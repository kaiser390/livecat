"""Check network traffic during NDI receive attempt."""
import ctypes
import os
import subprocess
import sys
import time
import struct
import threading

NDI_DLL = r"C:\Users\Computer\AppData\Roaming\Python\Python314\site-packages\cyndilib\wrapper\bin\Processing.NDI.Lib.x64.dll"
os.environ['NDILIB_EXTRA_IPS'] = '192.168.123.108'

ndi = ctypes.cdll.LoadLibrary(NDI_DLL)

NDI_HANDLE = ctypes.c_void_p

class NDIlib_source_t(ctypes.Structure):
    _fields_ = [("p_ndi_name", ctypes.c_char_p), ("p_url_address", ctypes.c_char_p)]

class NDIlib_find_create_t(ctypes.Structure):
    _fields_ = [("show_local_sources", ctypes.c_bool), ("p_groups", ctypes.c_char_p), ("p_extra_ips", ctypes.c_char_p)]

class NDIlib_recv_create_v3_t(ctypes.Structure):
    _fields_ = [
        ("source_to_connect_to", NDIlib_source_t), ("color_format", ctypes.c_int),
        ("bandwidth", ctypes.c_int), ("allow_video_fields", ctypes.c_bool),
        ("p_ndi_recv_name", ctypes.c_char_p),
    ]

class NDIlib_video_frame_v2_t(ctypes.Structure):
    _fields_ = [
        ("xres", ctypes.c_int), ("yres", ctypes.c_int), ("FourCC", ctypes.c_int),
        ("frame_rate_N", ctypes.c_int), ("frame_rate_D", ctypes.c_int),
        ("picture_aspect_ratio", ctypes.c_float), ("frame_format_type", ctypes.c_int),
        ("timecode", ctypes.c_int64), ("p_data", ctypes.c_void_p),
        ("line_stride_in_bytes", ctypes.c_int), ("p_metadata", ctypes.c_char_p),
        ("timestamp", ctypes.c_int64),
    ]

class NDIlib_audio_frame_v3_t(ctypes.Structure):
    _fields_ = [
        ("sample_rate", ctypes.c_int), ("no_channels", ctypes.c_int),
        ("no_samples", ctypes.c_int), ("timecode", ctypes.c_int64),
        ("FourCC", ctypes.c_int), ("p_data", ctypes.c_void_p),
        ("channel_stride_in_bytes", ctypes.c_int), ("p_metadata", ctypes.c_char_p),
        ("timestamp", ctypes.c_int64),
    ]

class NDIlib_metadata_frame_t(ctypes.Structure):
    _fields_ = [("length", ctypes.c_int), ("timecode", ctypes.c_int64), ("p_data", ctypes.c_char_p)]

# Function signatures
ndi.NDIlib_initialize.restype = ctypes.c_bool
ndi.NDIlib_initialize.argtypes = []
ndi.NDIlib_destroy.restype = None
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
ndi.NDIlib_recv_capture_v3.argtypes = [NDI_HANDLE, ctypes.POINTER(NDIlib_video_frame_v2_t), ctypes.POINTER(NDIlib_audio_frame_v3_t), ctypes.POINTER(NDIlib_metadata_frame_t), ctypes.c_uint32]
ndi.NDIlib_recv_free_video_v2.restype = None
ndi.NDIlib_recv_free_video_v2.argtypes = [NDI_HANDLE, ctypes.POINTER(NDIlib_video_frame_v2_t)]
ndi.NDIlib_recv_free_audio_v3.restype = None
ndi.NDIlib_recv_free_audio_v3.argtypes = [NDI_HANDLE, ctypes.POINTER(NDIlib_audio_frame_v3_t)]
ndi.NDIlib_recv_free_metadata.restype = None
ndi.NDIlib_recv_free_metadata.argtypes = [NDI_HANDLE, ctypes.POINTER(NDIlib_metadata_frame_t)]
ndi.NDIlib_recv_get_no_connections.restype = ctypes.c_int
ndi.NDIlib_recv_get_no_connections.argtypes = [NDI_HANDLE]


def check_netstat():
    """Check TCP connections to iPhone."""
    r = subprocess.run(['netstat', '-an'], capture_output=True, text=True, timeout=5)
    lines = [l for l in r.stdout.split('\n') if '192.168.123.108' in l]
    return lines


def main():
    print("=== NDI Traffic Monitor Test ===", flush=True)

    # Check connections before
    conns_before = check_netstat()
    print(f"Connections to iPhone BEFORE: {len(conns_before)}", flush=True)
    for c in conns_before:
        print(f"  {c.strip()}", flush=True)

    ndi.NDIlib_initialize()

    fc = NDIlib_find_create_t()
    fc.show_local_sources = True
    fc.p_extra_ips = b"192.168.123.108"
    finder = ndi.NDIlib_find_create_v2(ctypes.byref(fc))

    ndi.NDIlib_find_wait_for_sources(finder, 8000)
    num = ctypes.c_uint32(0)
    sources_ptr = ndi.NDIlib_find_get_current_sources(finder, ctypes.byref(num))

    if num.value == 0:
        print("No sources! Make sure NDI HX Camera is running on iPhone.", flush=True)
        ndi.NDIlib_find_destroy(finder)
        ndi.NDIlib_destroy()
        return

    src = sources_ptr[0]
    name = src.p_ndi_name.decode('utf-8', errors='replace') if src.p_ndi_name else ''
    url = src.p_url_address.decode('utf-8', errors='replace') if src.p_url_address else ''
    print(f"\nSource: '{name}' @ '{url}'", flush=True)

    # Create receiver
    rc = NDIlib_recv_create_v3_t()
    rc.source_to_connect_to = src
    rc.color_format = 0  # BGRX_BGRA
    rc.bandwidth = 100   # highest
    rc.allow_video_fields = True
    rc.p_ndi_recv_name = b"LiveCat"
    recv = ndi.NDIlib_recv_create_v3(ctypes.byref(rc))
    ndi.NDIlib_recv_connect(recv, ctypes.byref(src))
    ndi.NDIlib_find_destroy(finder)

    time.sleep(2)

    # Check connections AFTER NDI connect
    conns_after = check_netstat()
    print(f"\nConnections to iPhone AFTER: {len(conns_after)}", flush=True)
    for c in conns_after:
        print(f"  {c.strip()}", flush=True)

    nconn = ndi.NDIlib_recv_get_no_connections(recv)
    print(f"NDI connections: {nconn}", flush=True)

    # Now try receiving with NULL pointers for types we don't want
    # to see if maybe the struct layout is wrong
    video = NDIlib_video_frame_v2_t()
    audio = NDIlib_audio_frame_v3_t()
    meta = NDIlib_metadata_frame_t()

    print("\nReceiving (15s)...", flush=True)
    start = time.time()
    frame_types = {}

    while time.time() - start < 15:
        ft = ndi.NDIlib_recv_capture_v3(
            recv, ctypes.byref(video), ctypes.byref(audio),
            ctypes.byref(meta), 1000
        )
        frame_types[ft] = frame_types.get(ft, 0) + 1

        if ft == 1:  # video
            print(f"  VIDEO: {video.xres}x{video.yres} data={video.p_data}", flush=True)
            ndi.NDIlib_recv_free_video_v2(recv, ctypes.byref(video))
        elif ft == 2:  # audio
            ndi.NDIlib_recv_free_audio_v3(recv, ctypes.byref(audio))
        elif ft == 3:  # metadata
            md = meta.p_data.decode('utf-8', errors='replace')[:100] if meta.p_data else ''
            print(f"  META: {md}", flush=True)
            ndi.NDIlib_recv_free_metadata(recv, ctypes.byref(meta))

    print(f"\nFrame type counts: {frame_types}", flush=True)
    print(f"  0=none, 1=video, 2=audio, 3=metadata, 4=error, 100=status_change", flush=True)

    # Final connection check
    conns_final = check_netstat()
    print(f"\nFinal connections: {len(conns_final)}", flush=True)
    for c in conns_final:
        print(f"  {c.strip()}", flush=True)

    ndi.NDIlib_recv_destroy(recv)
    ndi.NDIlib_destroy()
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
