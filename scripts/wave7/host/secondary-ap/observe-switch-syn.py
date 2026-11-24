#!/usr/bin/env -S uv run --no-project python
"""Passive, boot-bound IPv4 TCP handshake checksum witness for the lab.

Only management SYN and SYN-ACK headers are captured. Locally transmitted
checksums can be incomplete because of host offload, so only AP-originated
frames received by Asus are classified as good or bad.
"""
import argparse
from collections import Counter
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import runpy
import struct
import subprocess

probe = runpy.run_path(str(Path(__file__).with_name("probe-mib-freshness.py")))
ROUTER = probe["ROUTER"]


def checksum(data):
    if len(data) % 2:
        data += b"\0"
    total = sum(word[0] for word in struct.iter_unpack("!H", data))
    while total >> 16:
        total = (total & 65535) + (total >> 16)
    return total ^ 65535


def frame(data, peer):
    if len(data) < 14 or data[12:14] != b"\x08\x00":
        raise ValueError("expected Ethernet IPv4 handshake")
    ip = data[14:]
    ihl = (ip[0] & 15) * 4
    length = int.from_bytes(ip[2:4], "big")
    if ip[0] >> 4 != 4 or ihl < 20 or length < ihl + 20 or length > len(ip) or ip[9] != 6:
        raise ValueError("invalid or truncated IPv4 frame")
    if int.from_bytes(ip[6:8], "big") & 0x3fff:
        raise ValueError("unexpected fragmented handshake")
    src, dst = map(str, (ipaddress.IPv4Address(ip[12:16]), ipaddress.IPv4Address(ip[16:20])))
    tcp = ip[ihl:length]
    sport, dport, seq, ack = struct.unpack_from("!HHII", tcp)
    flags = tcp[13]
    if not flags & 2 or (src,dst,sport == 22,dport == 22) not in (
        (ROUTER,peer,True,False), (peer,ROUTER,False,True)
    ):
        raise ValueError("unexpected handshake endpoints")
    header = (tcp[12] >> 4) * 4
    if header < 20 or header != len(tcp):
        raise ValueError("unexpected SYN payload or invalid TCP header")
    pseudo = ip[12:20] + struct.pack("!BBH", 0, 6, len(tcp))
    return {"src": src, "dst": dst, "sport": sport, "dport": dport,
            "seq": seq, "ack": ack, "flags": flags,
            "ipv4_checksum_ok": checksum(ip[:ihl]) == 0,
            "tcp_checksum_ok": checksum(pseudo + tcp) == 0}


def read_pcap(path, peer):
    data = path.read_bytes()
    magic = data[:4]
    formats = {b"\xd4\xc3\xb2\xa1": ("<", 1e6), b"\xa1\xb2\xc3\xd4": (">", 1e6),
               b"\x4d\x3c\xb2\xa1": ("<", 1e9), b"\xa1\xb2\x3c\x4d": (">", 1e9)}
    if magic not in formats or len(data) < 24:
        raise ValueError("invalid classic pcap")
    endian, unit = formats[magic]
    major, minor, _, _, snaplen, link = struct.unpack_from(endian+"HHIIII", data, 4)
    if (major, minor, link) != (2, 4, 1) or snaplen < 128:
        raise ValueError("unexpected capture format")
    offset = 24
    rows = []
    while offset < len(data):
        sec, frac, caplen, origlen = struct.unpack_from(endian+"IIII", data, offset)
        offset += 16
        if caplen != origlen or caplen > snaplen or offset+caplen > len(data):
            raise ValueError("truncated capture record")
        row = frame(data[offset:offset+caplen], peer)
        row["wall_epoch"] = sec + frac/unit
        rows.append(row)
        offset += caplen
    return rows


def summary(rows):
    syns = {(r["sport"], (r["seq"]+1) & 0xffffffff)
            for r in rows if r["src"] != ROUTER and not r["flags"] & 16}
    replies = [r for r in rows if r["src"] == ROUTER and r["flags"] & 16]
    matched = [r for r in replies if (r["dport"], r["ack"]) in syns]
    return {"outgoing_unique_syns":len(syns), "incoming_synacks":len(replies),
            "matched_synacks":len(matched),
            "matched_unique_requests":len({(r["dport"], r["ack"]) for r in matched}),
            "incoming_checksum_classes":dict(Counter(
                "valid" if r["ipv4_checksum_ok"] and r["tcp_checksum_ok"] else "invalid"
                for r in replies)),
            "matched_checksum_classes":dict(Counter(
                "valid" if r["ipv4_checksum_ok"] and r["tcp_checksum_ok"] else "invalid"
                for r in matched))}


def capture(out, boot, path, seconds):
    if not 10 <= seconds <= 60 or not re.fullmatch(r"[0-9a-f-]{36}", boot):
        raise ValueError("invalid duration or boot")
    peer, dev, *_ = probe["PATHS"][path]
    if probe["remote"]("cat /proc/sys/kernel/random/boot_id").strip() != boot:
        raise ValueError("wrong initial boot")
    out.mkdir(parents=True, exist_ok=False)
    pcap = out/"handshakes.pcap"
    filt = f"ip and host {ROUTER} and host {peer} and tcp port 22 and (tcp[13] & 2 != 0)"
    result = subprocess.run(["dumpcap","-P","-p","-i",dev,"-s","128","-f",filt,
                             "-a",f"duration:{seconds}","-w",str(pcap)],
                            text=True,capture_output=True,timeout=seconds+10)
    (out/"dumpcap.log").write_text(result.stdout+result.stderr)
    result.check_returncode()
    if probe["remote"]("cat /proc/sys/kernel/random/boot_id").strip() != boot:
        raise ValueError("boot changed during capture")
    rows = read_pcap(pcap,peer)
    report = {"boot":boot,"path":path,"interface":dev,"seconds":seconds,
              **summary(rows),"frames":rows}
    (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    (out/"SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
        for p in sorted(out.iterdir()) if p.name != "SHA256SUMS"))
    print(json.dumps({k:v for k,v in report.items() if k!="frames"}))


def selftest():
    peer="192.168.76.250"
    src=ipaddress.IPv4Address(ROUTER).packed
    dst=ipaddress.IPv4Address(peer).packed
    ip=bytearray(struct.pack("!BBHHHBBH4s4s",0x45,0,40,1,0,64,6,0,src,dst))
    ip[10:12]=struct.pack("!H",checksum(ip))
    tcp=bytearray(struct.pack("!HHIIBBHHH",22,50000,10,21,0x50,0x12,1024,0,0))
    tcp[16:18]=struct.pack("!H",checksum(src+dst+struct.pack("!BBH",0,6,len(tcp))+tcp))
    packet=b"\0"*12+b"\x08\x00"+ip+tcp
    row=frame(packet,peer)
    assert row["ipv4_checksum_ok"] and row["tcp_checksum_ok"]
    bad=bytearray(packet);bad[-4]^=1
    assert not frame(bytes(bad),peer)["tcp_checksum_ok"]
    assert summary([row])["incoming_checksum_classes"]=={"valid":1}
    print("SWITCH_SYN_CHECKSUM_SELFTEST_PASS")


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("selftest")
    c=sub.add_parser("capture")
    c.add_argument("out",type=Path)
    c.add_argument("boot")
    c.add_argument("path",choices=probe["PATHS"])
    c.add_argument("--seconds",type=int,default=30)
    args=parser.parse_args()
    if args.command=="selftest":
        selftest()
    else:
        capture(args.out,args.boot,args.path,args.seconds)
