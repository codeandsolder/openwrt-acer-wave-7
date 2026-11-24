#!/usr/bin/env -S uv run --no-project python
"""Verify deterministic TCP/UDP payloads on an exact sealed Wave7 boot."""
import argparse
from contextlib import contextmanager
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import runpy
import select
import shlex
import socket
import struct
import subprocess
import time

HERE = Path(__file__).resolve().parent
bench = runpy.run_path(str(HERE / "bench-ordering.py"))
probe, cohort = bench["probe"], bench["cohort"]
require, remote = probe["require"], probe["remote"]
PATHS = probe["PATHS"]
PORT = 52228
LENGTH = 4 * 1024**2 + 123
DATAGRAMS = 96
MASK = (1 << 64) - 1
PEER_SHA = "97a8a28db713c2a8264ae5b903ed924f0c716699eeaefb2f40383da0adf9f4c5"


def pattern(start, size):
    def byte(pos):
        x = (pos + 0x9e3779b97f4a7c15) & MASK
        x = ((x ^ (x >> 30)) * 0xbf58476d1ce4e5b9) & MASK
        x = ((x ^ (x >> 27)) * 0x94d049bb133111eb) & MASK
        return (x ^ (x >> 31)) & 255
    return bytes(byte(pos) for pos in range(start, start + size))


def addresses(path, family):
    ip, dev, *_ = PATHS[path]
    if family == socket.AF_INET:
        return (probe["ROUTER"], PORT), (ip, 0), f'{probe["ROUTER"]}:{PORT}', ip, dev
    # Use stable link-local addresses and explicit scope identifiers; no
    # dependence on temporary SLAAC addresses or DNS.
    host = json.loads(probe["run"](["ip", "-6", "-j", "addr", "show", "dev", dev]))
    require(len(host) == 1, "unexpected host interface")
    local = [row["local"] for row in host[0]["addr_info"] if row["scope"] == "link"]
    require(len(local) == 1, "expected one host link-local address")
    scope = host[0]["ifindex"]
    router = remote("ip -6 addr show dev br-lan; cat /sys/class/net/br-lan/ifindex")
    links = re.findall(r"inet6 ([0-9a-f:]+)/64 scope link", router)
    require(len(links) == 1 and router.splitlines()[-1].isdigit(), "router IPv6 scope")
    router_scope = int(router.splitlines()[-1])
    src, dst = str(ipaddress.IPv6Address(local[0])), str(ipaddress.IPv6Address(links[0]))
    return (dst, PORT, 0, scope), (src, 0, 0, scope), f"[{dst}%{router_scope}]:{PORT}", src, dev


@contextmanager
def remote_peer(out, boot, binary):
    require(hashlib.sha256(binary.read_bytes()).hexdigest() == PEER_SHA, "unexpected peer binary")
    path = f"/tmp/wave7-payload-{boot}"
    remote(f'test "$(cat /proc/sys/kernel/random/boot_id)" = {boot} && test ! -e {path}')
    opts = probe["ssh_args"]("true")[2:-2]
    try:
        probe["run"](["scp", "-q", "-O", *opts, str(binary), f"root@{probe['ROUTER']}:{path}"])
        require(remote(f"sha256sum {path}").split()[0] == PEER_SHA, "remote peer binary digest")
        remote(f"chmod 700 {path}")
        (out / "peer.sha256").write_text(PEER_SHA+"\n")
        yield path
    finally:
        remote(f'test "$(cat /proc/sys/kernel/random/boot_id)" = {boot} && rm -f {path}')


def exact_read(sock, size):
    data = bytearray(size)
    view = memoryview(data)
    offset = 0
    while offset < size:
        n = sock.recv_into(view[offset:])
        require(n > 0, "unexpected TCP EOF")
        offset += n
    return data


def transfer(mode, addr, bind, dev, family, mss, payload):
    socktype = socket.SOCK_DGRAM if mode == "udp" else socket.SOCK_STREAM
    with socket.socket(family, socktype) as sock:
        sock.settimeout(10)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, dev.encode()+b"\0")
        if mss:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG, mss)
        sock.bind(bind)
        sock.connect(addr)
        if mode == "tcp-receive":
            sock.sendall(payload)
            sock.shutdown(socket.SHUT_WR)
            require(exact_read(sock, 8) == struct.pack("!Q", len(payload)), "router did not verify payload")
            require(not sock.recv(1), "extra TCP acknowledgement data")
            return {"rx": len(payload)}
        if mode == "tcp-send":
            require(exact_read(sock, len(payload)) == payload, "router payload mismatch")
            require(not sock.recv(1), "unexpected extra TCP payload")
            sock.sendall(struct.pack("!Q", len(payload)))
            return {"tx": len(payload)}
        lengths = (8, 64, 257, 512, 1200, 1472 if family == socket.AF_INET else 1452)
        total = 0
        for seq in range(DATAGRAMS):
            size = lengths[seq % len(lengths)]
            data = struct.pack("!Q", seq) + pattern(seq*2048, size-8)
            require(sock.send(data) == size, "short UDP send")
            require(sock.recv(2048) == data, f"UDP echo mismatch seq={seq}")
            total += size
        return {"rx": total, "tx": total}


def run_case(out, path, family, mode, mss, binary, variant, boot, payload):
    tag = f'{path}-v{4 if family == socket.AF_INET else 6}-{mode}-mss{mss or "default"}'
    addr, bind, listen, peer, dev = addresses(path, family)
    before = bench["sample"](out, tag+"-before", variant, boot)
    count = DATAGRAMS if mode == "udp" else len(payload)
    cmd = " ".join(map(shlex.quote, ["timeout", "25", binary, mode, listen, peer, str(count)]))
    server = subprocess.Popen(probe["ssh_args"](cmd), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
    stdout, stderr = "", ""
    try:
        require(bool(select.select([server.stdout], [], [], 8)[0]), "peer readiness timeout")
        stdout = server.stdout.readline()
        require(stdout == "READY\n", "peer did not become ready")
        transferred = transfer(mode, addr, bind, dev, family, mss, payload)
        tail, stderr = server.communicate(timeout=12)
        stdout += tail
        require(server.returncode == 0 and stdout.splitlines()[-1].startswith("PASS "),
                "remote peer did not verify transfer")
    finally:
        if server.poll() is None:
            try:
                tail, stderr = server.communicate(timeout=27)
                stdout += tail
            except subprocess.TimeoutExpired:
                server.terminate()
                tail, stderr = server.communicate(timeout=5)
                stdout += tail
        (out / (tag+"-peer.log")).write_text(stdout)
        (out / (tag+"-peer.err")).write_text(stderr)
    after = bench["sample"](out, tag+"-after", variant, boot)
    record = {"case": tag, "payload_verified": True, "payload_bytes": transferred}
    # Direct and switched physical byte witnesses remain mandatory even
    # when the application payload is correct.
    record.update(bench["assess"](before, after, path, transferred))
    print(json.dumps({"case":tag,"payload_bytes":transferred}), flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--peer", choices=tuple(PATHS), action="append")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    record = cohort["load_run"](args.run.resolve())
    require(record and record["variant"] in ("force-order", "stock-order") and
            record["outcome"] == "clean", "requires sealed clean ordering boot")
    variant, boot = record["variant"], record["boot"]
    peers = tuple(args.peer or PATHS)
    require(len(set(peers)) == len(peers) and args.repeat > 0, "invalid peer/repeat")
    out = args.run.resolve() / ("payload-" + "-".join(peers) + f"-r{args.repeat}")
    payload = pattern(0, LENGTH)
    report = {"boot": boot, "variant": variant, "tcp_payload_sha256": hashlib.sha256(payload).hexdigest(),
              "tcp_length": LENGTH, "udp_datagrams": DATAGRAMS, "cases": []}
    failure = None
    with probe["lab_session"](out):
        try:
            bench["sample"](out, "initial", variant, boot)
            with remote_peer(out, boot, args.binary.resolve()) as binary:
                for peer in peers:
                    for family in (socket.AF_INET, socket.AF_INET6):
                        for mss in (0, 512):
                            for mode in ("tcp-send", "tcp-receive"):
                                report["cases"].append(run_case(out, peer, family, mode, mss,
                                                                binary, variant, boot, payload))
                        report["cases"].append(run_case(out, peer, family, "udp", 0,
                                                        binary, variant, boot, payload))
            report["status"] = "PASS"
        except Exception as exc:
            report.update(status="FAILED", error=str(exc))
            failure = exc
        (out / "report.json").write_text(json.dumps(report, indent=2)+"\n")
    if failure:
        raise failure


if __name__ == "__main__":
    main()
