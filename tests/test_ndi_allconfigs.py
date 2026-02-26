"""Try ALL possible NDI receiver configurations to receive HX stream."""
import ctypes
import os
import struct
import time

NDI_RUNTIME = r"C:\Program Files\NDI\NDI 6 Runtime\v6\Processing.NDI.Lib.x64.dll"
os.environ['NDILIB_EXTRA_IPS'] = '192.168.123.108'

print(f"Loading: {NDI_RUNTIME}", flush=True)
ndi = ctypes.cdll.LoadLibrary(NDI_RUNTIME)

H = ctypes.c_void_p

class S(ctypes.Structure):
    _fields_ = [("p_ndi_name", ctypes.c_char_p), ("p_url_address", ctypes.c_char_p)]

class FC(ctypes.Structure):
    _fields_ = [("show_local", ctypes.c_bool), ("groups", ctypes.c_char_p), ("extra_ips", ctypes.c_char_p)]

class RC(ctypes.Structure):
    _fields_ = [("source", S), ("color", ctypes.c_int), ("bw", ctypes.c_int),
                ("fields", ctypes.c_bool), ("name", ctypes.c_char_p)]

class VF(ctypes.Structure):
    _fields_ = [("xres", ctypes.c_int), ("yres", ctypes.c_int), ("FourCC", ctypes.c_int),
                ("frN", ctypes.c_int), ("frD", ctypes.c_int), ("ar", ctypes.c_float),
                ("fmt", ctypes.c_int), ("tc", ctypes.c_int64), ("data", ctypes.c_void_p),
                ("stride", ctypes.c_int), ("meta", ctypes.c_char_p), ("ts", ctypes.c_int64)]

class AF(ctypes.Structure):
    _fields_ = [("sr", ctypes.c_int), ("ch", ctypes.c_int), ("ns", ctypes.c_int),
                ("tc", ctypes.c_int64), ("fc", ctypes.c_int), ("data", ctypes.c_void_p),
                ("cs", ctypes.c_int), ("meta", ctypes.c_char_p), ("ts", ctypes.c_int64)]

class MF(ctypes.Structure):
    _fields_ = [("length", ctypes.c_int), ("tc", ctypes.c_int64), ("data", ctypes.c_char_p)]

class Tally(ctypes.Structure):
    _fields_ = [("on_program", ctypes.c_bool), ("on_preview", ctypes.c_bool)]

# Function signatures
ndi.NDIlib_initialize.restype = ctypes.c_bool
ndi.NDIlib_destroy.restype = None
ndi.NDIlib_find_create_v2.restype = H
ndi.NDIlib_find_create_v2.argtypes = [ctypes.POINTER(FC)]
ndi.NDIlib_find_destroy.restype = None
ndi.NDIlib_find_destroy.argtypes = [H]
ndi.NDIlib_find_wait_for_sources.restype = ctypes.c_bool
ndi.NDIlib_find_wait_for_sources.argtypes = [H, ctypes.c_uint32]
ndi.NDIlib_find_get_current_sources.restype = ctypes.POINTER(S)
ndi.NDIlib_find_get_current_sources.argtypes = [H, ctypes.POINTER(ctypes.c_uint32)]
ndi.NDIlib_recv_create_v3.restype = H
ndi.NDIlib_recv_create_v3.argtypes = [ctypes.POINTER(RC)]
ndi.NDIlib_recv_destroy.restype = None
ndi.NDIlib_recv_destroy.argtypes = [H]
ndi.NDIlib_recv_connect.restype = None
ndi.NDIlib_recv_connect.argtypes = [H, ctypes.POINTER(S)]
ndi.NDIlib_recv_capture_v3.restype = ctypes.c_int
ndi.NDIlib_recv_capture_v3.argtypes = [H, ctypes.POINTER(VF), ctypes.POINTER(AF), ctypes.POINTER(MF), ctypes.c_uint32]
ndi.NDIlib_recv_free_video_v2.restype = None
ndi.NDIlib_recv_free_video_v2.argtypes = [H, ctypes.POINTER(VF)]
ndi.NDIlib_recv_free_audio_v3.restype = None
ndi.NDIlib_recv_free_audio_v3.argtypes = [H, ctypes.POINTER(AF)]
ndi.NDIlib_recv_free_metadata.restype = None
ndi.NDIlib_recv_free_metadata.argtypes = [H, ctypes.POINTER(MF)]
ndi.NDIlib_recv_get_no_connections.restype = ctypes.c_int
ndi.NDIlib_recv_get_no_connections.argtypes = [H]
ndi.NDIlib_recv_set_tally.restype = ctypes.c_bool
ndi.NDIlib_recv_set_tally.argtypes = [H, ctypes.POINTER(Tally)]

# Color format options
COLOR_FORMATS = {
    0: "BGRX_BGRA",
    1: "UYVY_BGRA",
    2: "RGBX_RGBA",
    3: "UYVY_RGBA",
    100: "fastest",
    101: "best",
}

# Bandwidth options
BANDWIDTHS = {
    100: "highest",
    0: "lowest",
    -10: "audio_only",
}


def try_receive(recv, label, duration=8):
    """Try receiving frames for given duration."""
    v = VF()
    a = AF()
    m = MF()
    vc = ac = mc = 0
    ftypes = {}
    start = time.time()

    while time.time() - start < duration:
        ft = ndi.NDIlib_recv_capture_v3(recv, ctypes.byref(v), ctypes.byref(a), ctypes.byref(m), 500)
        ftypes[ft] = ftypes.get(ft, 0) + 1

        if ft == 1:  # video
            vc += 1
            try:
                fourcc = struct.pack("<I", v.FourCC).decode("ascii", errors="replace")
            except:
                fourcc = f"0x{v.FourCC:08x}"
            print(f"    VIDEO! {v.xres}x{v.yres} FourCC={fourcc} stride={v.stride}", flush=True)
            ndi.NDIlib_recv_free_video_v2(recv, ctypes.byref(v))
        elif ft == 2:  # audio
            ac += 1
            if ac <= 2:
                print(f"    AUDIO! {a.sr}Hz {a.ch}ch {a.ns}smp", flush=True)
            ndi.NDIlib_recv_free_audio_v3(recv, ctypes.byref(a))
        elif ft == 3:  # metadata
            mc += 1
            md = m.data.decode("utf-8", errors="replace")[:80] if m.data else ""
            print(f"    META: {md}", flush=True)
            ndi.NDIlib_recv_free_metadata(recv, ctypes.byref(m))

    elapsed = time.time() - start
    print(f"  [{label}] {elapsed:.1f}s: video={vc} audio={ac} meta={mc} types={ftypes}", flush=True)
    return vc, ac


def main():
    print("=== NDI All-Config Test ===\n", flush=True)

    if not ndi.NDIlib_initialize():
        print("NDI init failed!")
        return

    # Find source
    fc = FC()
    fc.show_local = True
    fc.extra_ips = b"192.168.123.108"
    finder = ndi.NDIlib_find_create_v2(ctypes.byref(fc))

    print("Finding sources...", flush=True)
    for i in range(3):
        ndi.NDIlib_find_wait_for_sources(finder, 5000)
        num = ctypes.c_uint32(0)
        sp = ndi.NDIlib_find_get_current_sources(finder, ctypes.byref(num))
        if num.value > 0:
            for j in range(num.value):
                name = sp[j].p_ndi_name.decode("utf-8", errors="replace") if sp[j].p_ndi_name else "?"
                url = sp[j].p_url_address.decode("utf-8", errors="replace") if sp[j].p_url_address else "?"
                print(f"  [{j}] {name} @ {url}", flush=True)
            break

    if num.value == 0:
        print("No sources found!")
        ndi.NDIlib_find_destroy(finder)
        ndi.NDIlib_destroy()
        return

    # Save source info
    src_name = sp[0].p_ndi_name
    src_url = sp[0].p_url_address
    ndi.NDIlib_find_destroy(finder)

    # Test configurations
    configs = [
        # (color_format, bandwidth, description)
        (101, 100, "best/highest"),       # Let NDI choose best format, highest bandwidth
        (100, 100, "fastest/highest"),     # Fastest decode, highest bandwidth
        (0, 100, "BGRX_BGRA/highest"),    # Standard BGRA
        (101, 0, "best/lowest"),           # Best format, lowest bandwidth (proxy)
        (0, 0, "BGRX_BGRA/lowest"),       # BGRA with low bandwidth
        (1, 100, "UYVY_BGRA/highest"),    # UYVY format
    ]

    total_video = 0
    total_audio = 0

    for color, bw, desc in configs:
        print(f"\n--- Config: color={color}({COLOR_FORMATS.get(color, '?')}), "
              f"bw={bw}({BANDWIDTHS.get(bw, '?')}) [{desc}] ---", flush=True)

        # Create source struct fresh each time
        src = S()
        src.p_ndi_name = src_name
        src.p_url_address = src_url

        # Create receiver with NULL source (connect separately)
        rc = RC()
        rc.source = S()  # empty source
        rc.color = color
        rc.bw = bw
        rc.fields = True
        rc.name = b"LiveCat Test"
        recv = ndi.NDIlib_recv_create_v3(ctypes.byref(rc))

        if not recv:
            print("  Receiver creation FAILED!", flush=True)
            continue

        # Connect to source
        ndi.NDIlib_recv_connect(recv, ctypes.byref(src))

        # Set tally
        tally = Tally()
        tally.on_program = True
        tally.on_preview = False
        ndi.NDIlib_recv_set_tally(recv, ctypes.byref(tally))

        time.sleep(1)
        nconn = ndi.NDIlib_recv_get_no_connections(recv)
        print(f"  Connections: {nconn}", flush=True)

        vc, ac = try_receive(recv, desc, duration=8)
        total_video += vc
        total_audio += ac

        ndi.NDIlib_recv_destroy(recv)

        if vc > 0:
            print(f"\n  *** SUCCESS with {desc}! ***", flush=True)
            break

        time.sleep(1)

    print(f"\n{'='*50}", flush=True)
    print(f"TOTAL: {total_video} video, {total_audio} audio across all configs", flush=True)

    if total_video == 0 and total_audio == 0:
        print("\nAll configs failed to receive video/audio.", flush=True)
        print("Possible causes:", flush=True)
        print("  1. NDI HX Camera free version may not send video (subscription needed)", flush=True)
        print("  2. NDI|HX codec not available in runtime", flush=True)
        print("  3. App is not actively streaming", flush=True)
        print("\nRecommended: Test with OBS Studio + DistroAV plugin", flush=True)
        print("  1. Open OBS Studio", flush=True)
        print("  2. Add Source -> NDI(TM) Source", flush=True)
        print("  3. Select the iPhone source", flush=True)

    ndi.NDIlib_destroy()


if __name__ == "__main__":
    main()
