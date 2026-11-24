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


def parse_xmit_trace(raw):
    """The tracepoint observes skb state at ndo_start_xmit, not at queue entry."""
    counts={}
    entries=re.search(r"entries-in-buffer/entries-written:\s*(\d+)/(\d+)",raw)
    require(entries and entries[1]==entries[2],"trace ring lost events")
    rows=0
    for line in raw.splitlines():
        if "net_dev_start_xmit: " not in line:
            continue
        fields=dict(re.findall(r"(\w+)=([^ ]+)",line.split("net_dev_start_xmit: ",1)[1]))
        dev=fields["dev"]
        require(dev in ("lan1","switch","lan"),"unexpected traced device")
        gso,csum,length,offset=map(int,(fields["gso_size"],fields["ip_summed"],fields["len"],fields["network_offset"]))
        row=counts.setdefault(dev,{"packets":0,"gso":0,"checksum_partial":0,
                                   "max_len":0,"network_offsets":{},"protocols":{}})
        row["packets"]+=1
        row["gso"]+=gso>0
        row["checksum_partial"]+=csum==3
        row["max_len"]=max(row["max_len"],length)
        for key,value in (("network_offsets",str(offset)),("protocols",fields["protocol"])):
            row[key][value]=row[key].get(value,0)+1
        rows+=1
    require(rows==int(entries[1]),"unparsed trace events")
    return counts


@contextmanager
def trace_instance(out,boot,enabled):
    if not enabled:
        yield None
        return
    require(re.fullmatch(r"[a-f0-9-]{36}",boot),"invalid boot")
    root=f"/sys/kernel/tracing/instances/wave7-payload-{boot}"
    check=f'test "$(cat /proc/sys/kernel/random/boot_id)" = {boot}'
    remote(f"set -e; {check}; test ! -e {root}; mkdir {root}")
    try:
        remote(f"""set -e; {check}
echo 0 > {root}/tracing_on
echo 2048 > {root}/buffer_size_kb
echo 'name == "lan1" || name == "switch" || name == "lan"' > {root}/events/net/net_dev_start_xmit/filter
echo 1 > {root}/events/net/net_dev_start_xmit/enable
""")
        (out/"trace-format.txt").write_text(remote(f"cat {root}/events/net/net_dev_start_xmit/format"))
        def trace_case(tag,call):
            remote(f"set -e; {check}; echo 0 > {root}/tracing_on; : > {root}/trace; echo 1 > {root}/tracing_on")
            try:
                record=call()
            finally:
                raw=remote(f"set -e; {check}; echo 0 > {root}/tracing_on; cat {root}/trace",timeout=30)
                (out/f"{tag}-xmit.trace").write_text(raw)
            record["xmit_trace"]=parse_xmit_trace(raw)
            return record
        yield trace_case
    finally:
        remote(f"set -e; {check}; echo 0 > {root}/tracing_on; echo 0 > {root}/events/net/net_dev_start_xmit/enable; rmdir {root}")


def selftest():
    header="# entries-in-buffer/entries-written: 2/2   #P:4\n"
    def row(dev,gso,csum,length,offset):
        return f"foo [001] 123.4: net_dev_start_xmit: dev={dev} gso_size={gso} ip_summed={csum} len={length} network_offset={offset} protocol=0x0800\n"
    raw=header+row("lan1",1460,3,6000,14)+row("switch",0,0,1522,22)
    result=parse_xmit_trace(raw)
    assert result["lan1"]["gso"]==1 and result["switch"]["gso"]==0
    assert result["switch"]["network_offsets"]=={"22":1}
    for invalid in (raw.replace("2/2","2/3"),raw.replace("dev=lan1","dev=other"),raw.replace("2/2","3/3")):
        try:parse_xmit_trace(invalid)
        except ValueError:pass
        else:raise AssertionError("invalid trace accepted")
    print("PAYLOAD_XMIT_TRACE_SELFTEST_PASS")


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
    failure = None
    transferred = {}
    try:
        require(bool(select.select([server.stdout], [], [], 8)[0]), "peer readiness timeout")
        stdout = server.stdout.readline()
        require(stdout == "READY\n", "peer did not become ready")
        transferred = transfer(mode, addr, bind, dev, family, mss, payload)
        tail, stderr = server.communicate(timeout=12)
        stdout += tail
        require(server.returncode == 0 and stdout.splitlines()[-1].startswith("PASS "),
                "remote peer did not verify transfer")
    except Exception as exc:
        failure = exc
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
    record = {"case": tag, "payload_verified": failure is None, "payload_bytes": transferred}
    def offload(raw, section):
        chunk = raw.split("=== " + section + " ===\n", 1)[1]
        chunk = chunk.split("=== ", 1)[0]
        fields = {}
        for key in ("tx_tso_packets", "tx_tso_drop_packets", "tx_gso_packets", "tx_gso_drop_packets"):
            matches = re.findall(rf"^\s*{key}:\s+(\d+)$", chunk, re.M)
            require(len(matches) == 1, "missing or duplicate EDMA offload counter")
            fields[key] = int(matches[0])
        return fields
    section = "CPU" if path == "switch" else "DIRECT"
    old = offload((out / (tag+"-before.txt")).read_text(), section)
    new = offload((out / (tag+"-after.txt")).read_text(), section)
    record["edma_delta"] = {key:new[key]-old[key] for key in old}
    require(all(v >= 0 for v in record["edma_delta"].values()), "EDMA counter reset")
    if failure is not None:
        record.update(qualification="FAILED", error=str(failure))
    else:
        # Physical witnesses are mandatory even when payload is correct.
        try:
            record.update(bench["assess"](before, after, path, transferred))
            record["qualification"] = "PASS"
        except ValueError as exc:
            record.update(qualification="FAILED", error=str(exc))
    print(json.dumps({"case":tag,"payload_bytes":transferred,
                      "qualification":record["qualification"],"edma_delta":record["edma_delta"]}), flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, nargs="?")
    parser.add_argument("binary", type=Path, nargs="?")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--peer", choices=tuple(PATHS), action="append")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return
    require(args.run and args.binary,"run and binary required")
    record = cohort["load_run"](args.run.resolve())
    require(record and record["variant"] in ("force-order", "stock-order", "edma-feature-init", "edma-sg-inheritance", "edma-dsa-feature-check") and
            record["outcome"] == "clean", "requires sealed clean EDMA or ordering boot")
    variant, boot = record["variant"], record["boot"]
    peers = tuple(args.peer or PATHS)
    require(len(set(peers)) == len(peers) and args.repeat > 0, "invalid peer/repeat")
    out = args.run.resolve() / ("payload-" + "-".join(peers) + ("-trace" if args.trace else "") + f"-r{args.repeat}")
    payload = pattern(0, LENGTH)
    report = {"boot": boot, "variant": variant, "tcp_payload_sha256": hashlib.sha256(payload).hexdigest(),
              "tcp_length": LENGTH, "udp_datagrams": DATAGRAMS, "cases": []}
    failure = None
    with probe["lab_session"](out):
        try:
            bench["sample"](out, "initial", variant, boot)
            (out / "features.txt").write_text(remote(
                'for d in switch lan1 lan br-lan; do echo "=== $d ==="; ethtool -k "$d"; done'))
            with remote_peer(out, boot, args.binary.resolve()) as binary, trace_instance(out,boot,args.trace) as trace:
                def execute(peer,family,mode,mss):
                    def call():
                        return run_case(out,peer,family,mode,mss,binary,variant,boot,payload)
                    tag=f'{peer}-v{4 if family==socket.AF_INET else 6}-{mode}-mss{mss or "default"}'
                    return trace(tag,call) if trace and mode=="tcp-send" else call()
                for peer in peers:
                    for family in (socket.AF_INET, socket.AF_INET6):
                        for mss in (0, 512):
                            for mode in ("tcp-send", "tcp-receive"):
                                report["cases"].append(execute(peer,family,mode,mss))
                        report["cases"].append(execute(peer,family,"udp",0))
            report["status"] = "PASS" if all(c["qualification"] == "PASS" for c in report["cases"]) else "FAILED"
            if report["status"] == "FAILED":
                failure = ValueError("one or more payload qualification cases failed")
        except Exception as exc:
            report.update(status="FAILED", error=str(exc))
            failure = exc
        (out / "report.json").write_text(json.dumps(report, indent=2)+"\n")
    if failure:
        raise failure


if __name__ == "__main__":
    main()
