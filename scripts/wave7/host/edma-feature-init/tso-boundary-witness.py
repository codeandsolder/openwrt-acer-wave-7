#!/usr/bin/env -S uv run --no-project python
"""Exercise the EDMA lower MSS boundary using real TCP traffic and wire witnesses."""
import argparse
from collections import Counter
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import re
import socket

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("payload_witness", HERE / "payload-witness.py")
pw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pw)
probe = pw.probe
require, remote = pw.require, pw.remote
LENGTH = 512 * 1024 + 123
# TCP timestamps commonly subtract 12 bytes from the advertised MSS.
# Sweep both sides and demand actual observed GSO/segment sizes, not the
# userspace TCP_MAXSEG input alone.
REQUESTS = (128, 255, 256, 267, 268, 269, 512)
VARIANT = "edma-tso-limits"


def trace_report(raw, family, wire_mss):
    header = re.search(r"entries-in-buffer/entries-written:\s*(\d+)/(\d+)", raw)
    require(header and header[1] == header[2], "trace ring lost events")
    protocol = "0x0800" if family == socket.AF_INET else "0x86dd"
    counts = Counter()
    queue_large = 0
    events = 0
    for line in raw.splitlines():
        if "net_dev_start_xmit: " in line:
            kind, data = "xmit", line.split("net_dev_start_xmit: ", 1)[1]
        elif "net_dev_queue: " in line:
            kind, data = "queue", line.split("net_dev_queue: ", 1)[1]
        else:
            continue
        events += 1
        f = dict(re.findall(r"(\w+)=([^ ]+)", data))
        require(f["dev"] == "lan", "unexpected trace device")
        if kind == "queue":
            if re.match(r"\s*wave7-payload-.?-\d+\s+\[", line) and int(f["len"]) > 1518:
                queue_large += 1
            continue
        size = int(f["gso_size"])
        if size:
            require(256 <= size <= 10240, f"unsupported GSO size at hardware boundary: {size}")
            require(int(f["ip_summed"]) == 3, "GSO without partial checksum")
            if f["protocol"] == protocol:
                counts[size] += 1
    require(events == int(header[1]), "unparsed trace entries")
    require(queue_large > 0, "no large queued skbs; segmentation path not exercised")
    if wire_mss >= 256:
        require(counts[wire_mss] > 0, "expected wire MSS never observed as hardware GSO")
    else:
        require(not counts[wire_mss], "undersized GSO reached driver")
    return {"large_queued": queue_large, "gso_sizes": dict(counts),
            "matching_gso": counts[wire_mss], "events": events}


def wire_report(raw, other, requested, length):
    # fields: source port, destination port, SYN flag, ACK flag, tcp.len,
    # advertised MSS, relative sequence. Only one TCP flow is expected.
    syn = []
    segments = []
    for line in raw.splitlines():
        src, dst, s, a, size, mss, seq = line.split("\t")
        if int(dst) == pw.PORT and s == "True" and a == "False":
            syn.append((int(src), int(mss)))
        if int(src) == pw.PORT and int(size) > 0:
            segments.append((int(dst), int(seq), int(size)))
    require(len(set(syn)) == 1, "missing or ambiguous client SYN/MSS")
    client, advertised = syn[0]
    require(0 < advertised <= requested, "unexpected advertised MSS")
    require(segments and all(port == client for port, _, _ in segments), "mixed TCP flows")
    require(not other.strip(), "test TCP traffic on wrong physical path")
    maximum = max(size for _, _, size in segments)
    require(maximum <= advertised, "wire TCP payload exceeds advertised MSS")
    # Verify complete sequence coverage independently of userspace payload equality.
    end = 1
    for _, seq, size in sorted(segments, key=lambda row: row[1]):
        require(seq <= end, "wire capture has TCP data gap")
        end = max(end, seq + size)
    require(end == length + 1, "wire capture does not cover exact payload")
    return {"advertised_mss": advertised, "wire_mss": maximum,
            "data_packets": len(segments), "wire_data_bytes": sum(r[2] for r in segments)}


@contextmanager
def tracer(out, boot):
    root = f"/sys/kernel/tracing/instances/wave7-tso-{boot}"
    check = f'test "$(cat /proc/sys/kernel/random/boot_id)" = {boot}'
    remote(f"set -e; {check}; test ! -e {root}; mkdir {root}")
    try:
        remote(f"""set -e; {check}
echo 0 > {root}/tracing_on
echo 2048 > {root}/buffer_size_kb
for event in net_dev_queue net_dev_start_xmit; do
  echo 'name == "lan"' > {root}/events/net/$event/filter
  echo 1 > {root}/events/net/$event/enable
done""")
        for event in ("net_dev_queue", "net_dev_start_xmit"):
            (out / f"{event}-format.txt").write_text(remote(f"cat {root}/events/net/{event}/format"))
        def capture(tag, call):
            remote(f"set -e; {check}; echo 0 > {root}/tracing_on; : > {root}/trace; echo 1 > {root}/tracing_on")
            try:
                return call()
            finally:
                (out / f"{tag}.trace").write_text(remote(
                    f"set -e; {check}; echo 0 > {root}/tracing_on; cat {root}/trace", timeout=30))
        yield capture
    finally:
        remote(f"""set -e; {check}
echo 0 > {root}/tracing_on
for event in net_dev_queue net_dev_start_xmit; do echo 0 > {root}/events/net/$event/enable; done
rmdir {root}""")


def decode(pcap):
    return probe["run"](["tshark", "-n", "-r", str(pcap), "-Y", "tcp",
        "-T", "fields", *sum((["-e", k] for k in (
            "tcp.srcport", "tcp.dstport", "tcp.flags.syn", "tcp.flags.ack",
            "tcp.len", "tcp.options.mss_val", "tcp.seq")), [])], timeout=30)


def run_case(out, capture, binary, variant, boot, family, requested, payload):
    tag = f"v{4 if family == socket.AF_INET else 6}-mss{requested}"
    capture_dir = out / tag
    capture_dir.mkdir(mode=0o700)
    try:
        with probe["capture_nics"](capture_dir, f"tcp port {pw.PORT}"):
            record = capture(tag, lambda: pw.run_case(
                out, "direct", family, "tcp-send", requested, binary, variant, boot, payload))
        wire = wire_report(decode(capture_dir / "direct.pcapng"),
                           decode(capture_dir / "switch.pcapng"), requested, len(payload))
        record["wire"] = wire
        record["boundary"] = trace_report((out / f"{tag}.trace").read_text(),
                                           family, wire["wire_mss"])
        require(record["qualification"] == "PASS", f"{tag}: payload/physical witness failed")
        require(not record["edma_delta"]["tx_tso_drop_packets"] and
                not record["edma_delta"]["tx_gso_drop_packets"], "EDMA offload drops")
        return record
    finally:
        # Keep each capture in the primary manifest (including on failure).
        for file in capture_dir.iterdir():
            file.rename(out / f"{tag}-{file.name}")
        capture_dir.rmdir()


def selftest():
    queue = "wave7-payload-2-123 [000] 1.0: net_dev_queue: dev=lan skbaddr=0000 len=4000"
    xmit = "task [000] 1.0: net_dev_start_xmit: dev=lan protocol=0x0800 ip_summed=3 gso_size=256"
    raw = "# entries-in-buffer/entries-written: 2/2\n" + queue + "\n" + xmit
    assert trace_report(raw, socket.AF_INET, 256)["matching_gso"] == 1
    assert trace_report(raw.replace("gso_size=256", "gso_size=0"), socket.AF_INET, 255)["matching_gso"] == 0
    tcp = "35000\t52228\tTrue\tFalse\t0\t256\t0\n52228\t35000\tFalse\tTrue\t256\t\t1\n52228\t35000\tFalse\tTrue\t1\t\t257\n"
    assert wire_report(tcp, "", 256, 257)["wire_mss"] == 256
    for invalid in (raw.replace("gso_size=256", "gso_size=255"), raw.replace("2/2","2/3"),
                    raw.replace("len=4000","len=400"), raw.replace("ip_summed=3","ip_summed=0")):
        try:
            trace_report(invalid, socket.AF_INET, 256)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid trace accepted")
    for invalid in (tcp.replace("\t257\n","\t258\n"), tcp.replace("\t256\t\t1","\t257\t\t1")):
        try:
            wire_report(invalid, "", 256, 257)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid wire capture accepted")
    print("EDMA_TSO_BOUNDARY_SELFTEST_PASS")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, nargs="?")
    parser.add_argument("binary", type=Path, nargs="?")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--lock-fd", type=int)
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return
    require(args.run and args.binary and args.attempt > 0, "run and binary required")
    record = pw.cohort["load_run"](args.run.resolve())
    require(record and record["variant"] == VARIANT and record["outcome"] == "clean",
            "requires sealed clean TSO candidate")
    variant, boot = record["variant"], record["boot"]
    out = args.run.resolve() / f"tso-mss-boundary-r{args.attempt}"
    report = {"boot": boot, "variant": variant, "cases": []}
    failure = None
    with probe["lab_session"](out, lock_fd=args.lock_fd):
        try:
            for _, dev, *_ in pw.PATHS.values():
                features = probe["run"](["ethtool", "-k", dev])
                (out / f"{dev}-features.txt").write_text(features)
                require(re.search(r"^generic-receive-offload: off$", features, re.M) and
                        re.search(r"^large-receive-offload: off", features, re.M),
                        "capture requires GRO/LRO disabled")
            pw.bench["sample"](out, "initial", variant, boot)
            payload = pw.pattern(0, LENGTH)
            with pw.remote_peer(out, boot, args.binary.resolve()) as binary, tracer(out, boot) as capture:
                for family in (socket.AF_INET, socket.AF_INET6):
                    for requested in REQUESTS:
                        row = run_case(out, capture, binary, variant, boot, family, requested, payload)
                        report["cases"].append(row)
            for label in ("v4", "v6"):
                rows = [r for r in report["cases"] if f"-{label}-" in r["case"]]
                require({255, 256, 257} <= {r["wire"]["wire_mss"] for r in rows},
                        f"{label}: exact MSS boundary not exercised")
            report["status"] = "PASS"
        except Exception as exc:
            report.update(status="FAILED", error=str(exc))
            failure = exc
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if failure:
        raise failure


if __name__ == "__main__":
    main()

