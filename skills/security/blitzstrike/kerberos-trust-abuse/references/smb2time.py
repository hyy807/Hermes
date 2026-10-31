#!/usr/bin/env python3
"""smb2time.py — dependency-free SMB2 clock meter.

Measures the DC's clock against yours by sending a raw SMB2 NEGOTIATE and
reading the SystemTime / ServerStartTime fields of the response (MS-SMB2
2.2.4: SystemTime is a FILETIME the server writes at response time).

Why: Kerberos fails with KRB_AP_ERR_SKEW whenever a ticket's timestamp falls
outside the KDC's accepted window (default 5 min). DCs drift, and a pivot box
or container usually has no NTP. Meter BEFORE every chain, not once per
engagement:

    python3 references/smb2time.py dc01.corp.local dc02.corp.local
    python3 references/smb2time.py 10.10.10.5 --max-skew 120 --json skew.json
    python3 references/smb2time.py --selftest          # no network

Output per host: local UTC, DC UTC, skew in seconds (+ = DC ahead of you),
verdict. Exit 0 when every host is inside --max-skew, 1 when any host is off,
2 on usage/import errors.

No impacket, no smbprotocol, no pip. Pure socket + struct.
"""
import argparse
import json
import socket
import struct
import sys
import time

FILETIME_EPOCH_DELTA = 11644473600  # seconds between 1601-01-01 and 1970-01-01
NEGOTIATE_REQ = bytes.fromhex(
    "fe534d42"          # ProtocolId "\xfeSMB"
    "4000"              # StructureSize 64
    "0100"              # CreditCharge 1
    "00000000"          # Status / ChannelSequence
    "0000"              # Command = NEGOTIATE
    "0100"              # CreditRequest 1
    "00000000"          # Flags
    "00000000"          # NextCommand
    "0000000000000000"  # MessageId
    "00000000"          # Reserved (ProcessId)
    "00000000"          # TreeId
    "0000000000000000"  # SessionId
    "00000000000000000000000000000000"  # Signature
    # --- body ---
    "2400"              # StructureSize 36
    "0100"              # DialectCount 1
    "0100"              # SecurityMode: signing enabled
    "0000"              # Reserved
    "00000000"          # Capabilities
    "00000000000000000000000000000000"  # ClientGuid
    "0000000000000000"  # ClientStartTime
    "1002"              # Dialect 0x0210 (SMB 3.0.2)
)
SMB2_HDR = 64
# response body offsets
OFF_STRUCT = 0
OFF_DIALECT = 4
OFF_SYSTIME = 40
OFF_SERVERSTART = 48


def nbss_frame(payload: bytes) -> bytes:
    return b"\x00" + len(payload).to_bytes(3, "big") + payload


def recv_nbss(sock) -> bytes:
    hdr = recvn(sock, 4)
    if not hdr:
        raise ConnectionError("connection closed before NBSS header")
    if hdr[0] != 0:
        raise ValueError(f"unexpected NBSS type 0x{hdr[0]:02x} (SMB1 only? try port 139)")
    n = int.from_bytes(hdr[1:4], "big")
    return recvn(sock, n)


def recvn(sock, n) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def filetime_to_epoch(ft: int) -> float:
    return ft / 10_000_000.0 - FILETIME_EPOCH_DELTA


def parse_negotiate(resp: bytes) -> dict:
    """Parse an SMB2 NEGOTIATE response body. Raises ValueError on junk."""
    if len(resp) < SMB2_HDR + OFF_SERVERSTART + 8:
        raise ValueError(f"short response ({len(resp)} bytes)")
    if resp[:4] != b"\xfeSMB":
        raise ValueError("not an SMB2 response")
    cmd = struct.unpack_from("<H", resp, 12)[0]
    if cmd != 0:
        raise ValueError(f"unexpected command {cmd} (want NEGOTIATE=0)")
    status = struct.unpack_from("<I", resp, 8)[0]
    if status != 0:
        raise ValueError(f"NTSTATUS 0x{status:08x}")
    body = resp[SMB2_HDR:]
    if struct.unpack_from("<H", body, OFF_STRUCT)[0] != 65:
        raise ValueError("StructureSize != 65")
    dialect = struct.unpack_from("<H", body, OFF_DIALECT)[0]
    sys_ft = struct.unpack_from("<Q", body, OFF_SYSTIME)[0]
    start_ft = struct.unpack_from("<Q", body, OFF_SERVERSTART)[0]
    return {
        "dialect": f"0x{dialect:04x}",
        "system_time": filetime_to_epoch(sys_ft),
        "server_start": filetime_to_epoch(start_ft) if start_ft else None,
        "raw_system_filetime": sys_ft,
    }


def meter(host, port, timeout):
    t0 = time.time()
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(nbss_frame(NEGOTIATE_REQ))
        resp = recv_nbss(s)
    t1 = time.time()
    info = parse_negotiate(resp)
    # assume symmetric RTT: the server wrote SystemTime at the midpoint
    midpoint = (t0 + t1) / 2.0
    skew = info["system_time"] - midpoint
    info.update({"host": host, "port": port, "rtt": round(t1 - t0, 3),
                 "skew": round(skew, 1), "local_at_midpoint": time.strftime(
                     "%Y-%m-%dT%H:%M:%SZ", time.gmtime(midpoint))})
    if info["server_start"]:
        up = info["system_time"] - info["server_start"]
        info["uptime_days"] = round(up / 86400.0, 1)
    return info


def selftest() -> int:
    """Craft a NEGOTIATE response with a known time and check the parser."""
    now = 1_700_000_000.0
    ft = int((now + FILETIME_EPOCH_DELTA) * 10_000_000)
    hdr = bytearray(NEGOTIATE_REQ[:SMB2_HDR])
    body = bytearray(65 + 8)
    struct.pack_into("<H", body, OFF_STRUCT, 65)
    struct.pack_into("<H", body, OFF_DIALECT, 0x0210)
    struct.pack_into("<Q", body, OFF_SYSTIME, ft)
    struct.pack_into("<Q", body, OFF_SERVERSTART, ft - 86400 * 10 * 10_000_000)
    info = parse_negotiate(bytes(hdr) + bytes(body))
    assert abs(info["system_time"] - now) < 0.0001, info
    assert info["dialect"] == "0x0210", info
    assert abs(info["server_start"] - (now - 86400 * 10)) < 0.0001, info
    # skew math on a synthetic pair
    skew = info["system_time"] - (now - 7)
    assert abs(skew - 7) < 0.001, skew
    print("selftest: ok (parse + FILETIME conversion + skew math)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("hosts", nargs="*")
    ap.add_argument("--port", type=int, default=445)
    ap.add_argument("--timeout", type=float, default=5)
    ap.add_argument("--max-skew", type=float, default=300, help="seconds (Kerberos default window)")
    ap.add_argument("--json", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.hosts:
        ap.print_help()
        return 2

    results, worst, bad = [], 0.0, 0
    print(f"{'host':24s} {'skew(s)':>8s} {'rtt':>5s} {'dialect':>7s}  verdict")
    for h in a.hosts:
        try:
            r = meter(h, a.port, a.timeout)
        except Exception as e:
            print(f"{h:24s} {'-':>8s} {'-':>5s} {'-':>7s}  ERROR {type(e).__name__}: {e}")
            results.append({"host": h, "error": f"{type(e).__name__}: {e}"})
            bad += 1
            continue
        verdict = "ok" if abs(r["skew"]) <= a.max_skew else "SKEW OUT OF WINDOW"
        if abs(r["skew"]) > a.max_skew:
            bad += 1
        worst = max(worst, abs(r["skew"]))
        print(f"{h:24s} {r['skew']:>+8.1f} {r['rtt']:>5.2f} {r['dialect']:>7s}  {verdict}")
        results.append(r)

    if len(results) > 1:
        vals = [r["skew"] for r in results if "skew" in r]
        if vals:
            spread = max(vals) - min(vals)
            print(f"\nDC spread: {spread:.1f}s across {len(vals)} hosts "
                  f"({'consistent' if spread <= a.max_skew else 'DC-to-DC drift — stage from the nearest DC'})")

    print(f"\nworst |skew| = {worst:.1f}s  (limit {a.max_skew:.0f}s)")
    if bad:
        print("action: sync the pivot box (chrony/ntpdate -u <dc>, or run the chain ON the DC's subnet). "
              "Do NOT brute-force a clock: every Kerberos op fails identically and looks like bad creds.")
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"max_skew": a.max_skew, "worst": worst, "results": results}, f, indent=1)
        print(f"json: {a.json}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
