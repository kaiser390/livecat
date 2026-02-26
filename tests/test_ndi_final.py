"""NDI receive test with official NDI Runtime v6."""
import ctypes
import os
import struct
import time

# Use OFFICIAL NDI Runtime v6 (not cyndilib redistribution)
NDI_RUNTIME = r"C:\Program Files\NDI\NDI 6 Runtime\v6\Processing.NDI.Lib.x64.dll"
os.environ['NDILIB_EXTRA_IPS'] = '192.168.123.108'

print(f"Loading NDI Runtime: {NDI_RUNTIME}", flush=True)
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


def main():
    print("=== NDI Receive with Official Runtime v6 ===\n", flush=True)

    if not ndi.NDIlib_initialize():
        print("NDI init failed!")
        return

    # Find sources
    fc = FC()
    fc.show_local = True
    fc.extra_ips = b"192.168.123.108"
    finder = ndi.NDIlib_find_create_v2(ctypes.byref(fc))

    print("Searching for NDI sources...", flush=True)
    for i in range(4):
        ndi.NDIlib_find_wait_for_sources(finder, 5000)
        num = ctypes.c_uint32(0)
        sp = ndi.NDIlib_find_get_current_sources(finder, ctypes.byref(num))
        print(f"  [{(i+1)*5}s] Found {num.value} sources", flush=True)
        if num.value > 0:
            for j in range(num.value):
                name = sp[j].p_ndi_name.decode("utf-8", errors="replace") if sp[j].p_ndi_name else "?"
                url = sp[j].p_url_address.decode("utf-8", errors="replace") if sp[j].p_url_address else "?"
                print(f"    [{j}] {name} @ {url}", flush=True)
            break

    if num.value == 0:
        print("\nNo NDI sources found! Make sure NDI HX Camera is running on iPhone.", flush=True)
        ndi.NDIlib_find_destroy(finder)
        ndi.NDIlib_destroy()
        return

    src = sp[0]
    print(f"\nConnecting to: {src.p_ndi_name.decode()}", flush=True)

    # Create receiver
    rc = RC()
    rc.source = src
    rc.color = 0  # BGRX_BGRA
    rc.bw = 100   # highest
    rc.fields = True
    rc.name = b"LiveCat Server"
    recv = ndi.NDIlib_recv_create_v3(ctypes.byref(rc))

    # Connect
    ndi.NDIlib_recv_connect(recv, ctypes.byref(src))
    ndi.NDIlib_find_destroy(finder)

    # Set tally
    tally = Tally()
    tally.on_program = True
    tally.on_preview = True
    ndi.NDIlib_recv_set_tally(recv, ctypes.byref(tally))

    time.sleep(2)
    nconn = ndi.NDIlib_recv_get_no_connections(recv)
    print(f"Connections: {nconn}", flush=True)

    # Receive frames
    v = VF()
    a = AF()
    m = MF()
    vcount = 0
    acount = 0
    start = time.time()

    print("\nReceiving frames (30s max)...\n", flush=True)

    while time.time() - start < 30:
        elapsed = time.time() - start
        ft = ndi.NDIlib_recv_capture_v3(recv, ctypes.byref(v), ctypes.byref(a), ctypes.byref(m), 1000)

        if ft == 1:  # video
            vcount += 1
            fps = vcount / elapsed if elapsed > 0 else 0
            try:
                fourcc = struct.pack("<I", v.FourCC).decode("ascii", errors="replace")
            except:
                fourcc = f"0x{v.FourCC:08x}"
            print(f"  VIDEO #{vcount}: {v.xres}x{v.yres} FourCC={fourcc} "
                  f"stride={v.stride} rate={v.frN}/{v.frD} {fps:.1f}fps", flush=True)
            ndi.NDIlib_recv_free_video_v2(recv, ctypes.byref(v))

            if vcount >= 30:
                print(f"\n  30 frames received! Stream is working!", flush=True)
                break

        elif ft == 2:  # audio
            acount += 1
            if acount <= 3:
                print(f"  AUDIO #{acount}: {a.sr}Hz {a.ch}ch {a.ns} samples", flush=True)
            ndi.NDIlib_recv_free_audio_v3(recv, ctypes.byref(a))

        elif ft == 3:  # metadata
            md = m.data.decode("utf-8", errors="replace")[:100] if m.data else ""
            print(f"  META: {md}", flush=True)
            ndi.NDIlib_recv_free_metadata(recv, ctypes.byref(m))

        elif ft == 100:  # status change
            nconn = ndi.NDIlib_recv_get_no_connections(recv)
            print(f"  STATUS_CHANGE: connections={nconn}", flush=True)

        elif ft == 0:  # nothing
            if int(elapsed) % 5 == 0 and vcount == 0:
                nconn = ndi.NDIlib_recv_get_no_connections(recv)
                print(f"  [{elapsed:.0f}s] Waiting... connections={nconn}", flush=True)
                time.sleep(1)

    total = time.time() - start
    if vcount > 0:
        avg_fps = vcount / total
        print(f"\n{'='*50}", flush=True)
        print(f"SUCCESS! {vcount} video frames, {acount} audio frames", flush=True)
        print(f"Average FPS: {avg_fps:.1f}", flush=True)
        print(f"Duration: {total:.1f}s", flush=True)
        print(f"{'='*50}", flush=True)
    else:
        print(f"\nNo video frames received in {total:.1f}s", flush=True)
        print(f"Audio frames: {acount}", flush=True)

    ndi.NDIlib_recv_destroy(recv)
    ndi.NDIlib_destroy()


if __name__ == "__main__":
    main()
