"""
MPEG-TS over UDP Packet Analyzer
Captures UDP packets from iPhone and analyzes MPEG-TS + H.264 structure.
Diagnoses SPS/PPS issues.

Usage: python tests/udp_analyzer.py [--port 9000] [--count 100]
"""
import socket
import sys
import struct
import time

def parse_ts_packet(data, offset=0):
    """Parse a single 188-byte MPEG-TS packet"""
    if len(data) < offset + 188:
        return None

    pkt = data[offset:offset+188]

    # Sync byte
    sync = pkt[0]
    if sync != 0x47:
        return {"error": f"Bad sync byte: 0x{sync:02x}"}

    # Header bytes 1-2
    b1 = pkt[1]
    b2 = pkt[2]

    tei = (b1 >> 7) & 1
    pusi = (b1 >> 6) & 1  # Payload Unit Start Indicator
    pid = ((b1 & 0x1F) << 8) | b2

    # Byte 3
    b3 = pkt[3]
    scrambling = (b3 >> 6) & 3
    adaptation = (b3 >> 4) & 3
    cc = b3 & 0xF

    payload_offset = 4
    adaptation_info = {}

    if adaptation & 0x2:  # Adaptation field present
        adapt_len = pkt[4]
        if adapt_len > 0:
            adapt_flags = pkt[5]
            adaptation_info = {
                "length": adapt_len,
                "discontinuity": bool(adapt_flags & 0x80),
                "random_access": bool(adapt_flags & 0x40),  # Important for keyframes
                "pcr_flag": bool(adapt_flags & 0x10),
            }
        payload_offset = 5 + adapt_len

    payload = pkt[payload_offset:] if (adaptation & 0x1) else b""

    return {
        "pid": pid,
        "pusi": pusi,
        "cc": cc,
        "adaptation": adaptation_info,
        "payload_offset": payload_offset,
        "payload_len": len(payload),
        "payload": payload,
    }

def find_nal_units(data):
    """Find NAL unit types in H.264 data"""
    nals = []
    i = 0
    while i < len(data) - 3:
        # Look for start codes: 00 00 01 or 00 00 00 01
        if data[i] == 0 and data[i+1] == 0:
            if data[i+2] == 1:
                nal_type = data[i+3] & 0x1F
                nals.append({"offset": i, "start_code": 3, "type": nal_type, "type_name": NAL_TYPES.get(nal_type, f"unknown({nal_type})")})
                i += 4
                continue
            elif data[i+2] == 0 and i+3 < len(data) and data[i+3] == 1:
                if i+4 < len(data):
                    nal_type = data[i+4] & 0x1F
                    nals.append({"offset": i, "start_code": 4, "type": nal_type, "type_name": NAL_TYPES.get(nal_type, f"unknown({nal_type})")})
                i += 5
                continue
        i += 1
    return nals

NAL_TYPES = {
    1: "SLICE (non-IDR)",
    2: "SLICE_DPA",
    3: "SLICE_DPB",
    4: "SLICE_DPC",
    5: "IDR_SLICE (keyframe)",
    6: "SEI",
    7: "SPS",          # <-- This is what we need!
    8: "PPS",          # <-- And this!
    9: "AUD",
    10: "END_SEQ",
    11: "END_STREAM",
    12: "FILLER",
}

def analyze_pes_header(payload):
    """Check PES header for PTS"""
    if len(payload) < 9:
        return {}

    # PES start code: 00 00 01
    if payload[0] != 0 or payload[1] != 0 or payload[2] != 1:
        return {"error": "No PES start code"}

    stream_id = payload[3]
    pes_length = (payload[4] << 8) | payload[5]

    if stream_id < 0xBC:
        return {"stream_id": f"0x{stream_id:02x}", "note": "not PES"}

    flags = payload[7]
    pts_flag = bool(flags & 0x80)
    dts_flag = bool(flags & 0x40)
    pes_header_len = payload[8]

    result = {
        "stream_id": f"0x{stream_id:02x}",
        "pes_length": pes_length,
        "pts_flag": pts_flag,
        "dts_flag": dts_flag,
        "header_len": pes_header_len,
    }

    if pts_flag and len(payload) >= 14:
        # Parse PTS (33 bits across 5 bytes)
        b = payload[9:14]
        pts = ((b[0] >> 1) & 0x07) << 30
        pts |= (b[1] << 22)
        pts |= ((b[2] >> 1) << 15)
        pts |= (b[3] << 7)
        pts |= (b[4] >> 1)
        result["pts"] = pts
        result["pts_sec"] = pts / 90000.0

    return result

def main():
    port = 9000
    max_count = 200

    for i, a in enumerate(sys.argv):
        if a == "--port" and i+1 < len(sys.argv):
            port = int(sys.argv[i+1])
        if a == "--count" and i+1 < len(sys.argv):
            max_count = int(sys.argv[i+1])

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(30)

    print(f"=== MPEG-TS UDP Analyzer on port {port} ===")
    print(f"Waiting for packets (timeout 30s)...")
    print()

    pkt_count = 0
    ts_count = 0
    pid_stats = {}
    found_sps = False
    found_pps = False
    found_idr = False
    found_pts = False
    nal_type_counts = {}
    errors = []
    first_packet_hex = None

    try:
        while pkt_count < max_count:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                if pkt_count == 0:
                    print("TIMEOUT - no packets received")
                break

            pkt_count += 1

            if pkt_count == 1:
                print(f"First packet from {addr}: {len(data)} bytes")
                first_packet_hex = data[:60].hex()
                print(f"Hex (first 60 bytes): {first_packet_hex}")
                print()

            # Parse TS packets within this UDP packet
            offset = 0
            while offset + 188 <= len(data):
                ts = parse_ts_packet(data, offset)
                if ts is None:
                    break

                if "error" in ts:
                    # Try to find sync byte
                    found = False
                    for scan in range(offset+1, min(offset+188, len(data))):
                        if data[scan] == 0x47:
                            offset = scan
                            found = True
                            break
                    if not found:
                        break
                    continue

                ts_count += 1
                pid = ts["pid"]
                pid_stats[pid] = pid_stats.get(pid, 0) + 1

                # Check for PES start on video PID (usually 0x100 = 256)
                if ts["pusi"] and pid not in (0, 1) and pid != 0x1FFF:
                    pes = analyze_pes_header(ts["payload"])
                    if pes.get("pts_flag"):
                        found_pts = True

                    # Look for NAL units in PES payload
                    pes_header_len = pes.get("header_len", 0)
                    nal_start = 9 + pes_header_len if pes_header_len else 0
                    if nal_start < len(ts["payload"]):
                        nals = find_nal_units(ts["payload"][nal_start:])
                        for nal in nals:
                            nt = nal["type"]
                            nal_type_counts[nt] = nal_type_counts.get(nt, 0) + 1
                            if nt == 7:
                                found_sps = True
                                if pkt_count <= 10:
                                    print(f"  ** SPS found in UDP pkt #{pkt_count}, TS PID=0x{pid:04x}")
                            elif nt == 8:
                                found_pps = True
                                if pkt_count <= 10:
                                    print(f"  ** PPS found in UDP pkt #{pkt_count}, TS PID=0x{pid:04x}")
                            elif nt == 5:
                                found_idr = True
                                if pkt_count <= 10:
                                    print(f"  ** IDR keyframe in UDP pkt #{pkt_count}, TS PID=0x{pid:04x}")

                # Also check raw payload for NAL start codes (in case PES parsing misses them)
                if pid not in (0, 1) and pid != 0x1FFF:
                    raw_nals = find_nal_units(ts["payload"])
                    for nal in raw_nals:
                        nt = nal["type"]
                        if nt == 7 and not found_sps:
                            found_sps = True
                            print(f"  ** SPS in raw payload! UDP pkt #{pkt_count}, PID=0x{pid:04x}")
                        elif nt == 8 and not found_pps:
                            found_pps = True
                            print(f"  ** PPS in raw payload! UDP pkt #{pkt_count}, PID=0x{pid:04x}")

                offset += 188

            # Progress every 50 packets
            if pkt_count % 50 == 0:
                print(f"  ... {pkt_count} UDP packets ({ts_count} TS packets)")

    except KeyboardInterrupt:
        pass

    sock.close()

    # Summary
    print()
    print("=" * 50)
    print(f"ANALYSIS SUMMARY")
    print("=" * 50)
    print(f"UDP packets received: {pkt_count}")
    print(f"TS packets parsed:    {ts_count}")
    print()

    print("PID distribution:")
    for pid, count in sorted(pid_stats.items()):
        name = {0: "PAT", 1: "CAT", 0x1FFF: "NULL"}.get(pid, f"PID")
        print(f"  0x{pid:04x} ({name}): {count} packets")
    print()

    print("H.264 NAL types found:")
    if nal_type_counts:
        for nt, count in sorted(nal_type_counts.items()):
            name = NAL_TYPES.get(nt, f"type {nt}")
            print(f"  Type {nt} ({name}): {count}")
    else:
        print("  NONE - no NAL units detected!")
    print()

    print("Critical checks:")
    print(f"  SPS (type 7): {'YES' if found_sps else 'NO  *** MISSING! This causes decoder failure ***'}")
    print(f"  PPS (type 8): {'YES' if found_pps else 'NO  *** MISSING! This causes decoder failure ***'}")
    print(f"  IDR (type 5): {'YES' if found_idr else 'NO  (no keyframes detected)'}")
    print(f"  PTS timestamps: {'YES' if found_pts else 'NO  *** MISSING! Causes timing issues ***'}")
    print(f"  PAT (PID 0):   {'YES' if 0 in pid_stats else 'NO  *** MISSING! ***'}")
    print()

    if not found_sps or not found_pps:
        print("DIAGNOSIS: SPS/PPS are NOT being sent in the MPEG-TS stream.")
        print("The iOS app needs to extract SPS/PPS from CMFormatDescription")
        print("and include them as NAL units before each IDR frame.")
        print()
        if first_packet_hex:
            print(f"First packet hex: {first_packet_hex}")

if __name__ == "__main__":
    main()
