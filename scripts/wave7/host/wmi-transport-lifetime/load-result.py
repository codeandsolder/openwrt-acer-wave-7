#!/usr/bin/env python3
"""Validate the client TCP-load archive and report receiver goodput."""
import argparse
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
import tarfile

PING = re.compile(r"^(\d+) packets transmitted, (\d+) received", re.M)
RTT = re.compile(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms")
MODES = ("uplink", "downlink", "bidirectional")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load_archive(path, tag):
    with tarfile.open(path) as archive:
        files = {}
        for member in archive.getmembers():
            if member.isdir():
                continue
            require(member.isfile() and member.name.startswith(tag + "/"),
                    "unexpected client archive member")
            name = member.name[len(tag) + 1:]
            require("/" not in name and name not in files, "invalid client evidence path")
            with archive.extractfile(member) as src:
                files[name] = src.read()
    manifest = files.pop("SHA256SUMS").decode()
    seen = set()
    for line in manifest.splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.removeprefix("./")
        require(name not in seen and name in files and
                hashlib.sha256(files[name]).hexdigest() == digest, "client evidence seal")
        seen.add(name)
    require(seen == files.keys(), "unsealed client evidence")
    return {name: data.decode() for name, data in files.items()}


def ping(text, expected, strict=False):
    m = PING.search(text)
    require(m and int(m[1]) == expected and 0 <= int(m[2]) <= expected,
            "incomplete ping result")
    received = int(m[2])
    require(not strict or received == expected, "strict ping loss")
    rtt = RTT.search(text)
    require(not received or rtt, "missing RTT statistics")
    return {"sent": expected, "received": received,
            "rtt_ms": dict(zip(("min", "mean", "max", "mdev"), map(float, rtt.groups())))
            if rtt else None}


def check_link(text):
    require(re.search(r"\bactive=0x3 valid=0x3\b", text), "dual-link state lost")


def iperf(text, server_text, mode, target, *, source="192.168.76.2", port=52231,
          streams=4, duration=15, omit=2):
    raw = json.loads(text)
    server = json.loads(server_text)
    expected = {
        "protocol": "TCP", "num_streams": streams, "duration": duration, "omit": omit,
        "reverse": int(mode == "uplink"), "bidir": int(mode == "bidirectional"),
    }
    for result in (raw, server):
        require(not result.get("error"), "iperf error")
        test = result["start"]["test_start"]
        require(all(test[k] == v for k, v in expected.items()), "wrong iperf parameters")
    conn = raw["start"]["connected"]
    server_conn = server["start"]["connected"]
    count = streams * (2 if mode == "bidirectional" else 1)
    require(len(conn) == len(server_conn) == count
            and all(c["local_host"] == source and c["remote_host"] == target
                    and c["remote_port"] == port for c in conn)
            and all(c["local_host"] == target and c["remote_host"] == source
                    and c["local_port"] == port for c in server_conn)
            and len({c["local_port"] for c in conn}) == count
            and {c["local_port"] for c in conn} == {c["remote_port"] for c in server_conn},
            "wrong TCP endpoints or mismatched independent connections")
    end = raw["end"]
    server_end = server["end"]

    def direction(suffix, uplink):
        sent = end["sum_sent" + suffix]
        recv = end["sum_received" + suffix]
        secs = recv["seconds"]
        rate = recv["bits_per_second"]
        require(0 < secs and duration - 1 <= secs <= duration + 5
                and math.isfinite(rate) and rate > 0 and recv["bytes"] > 0
                and math.isclose(rate, recv["bytes"] * 8 / secs, rel_tol=.001)
                and sent["retransmits"] >= 0, "invalid TCP receiver statistics")
        # Wyse's independently archived server JSON witnesses its actual
        # send (uplink) or receive (downlink) byte counts.
        observed = server_end[("sum_sent" if uplink else "sum_received") + suffix]
        require(observed["bytes"] == (sent if uplink else recv)["bytes"],
                "independent server byte count mismatch")
        if uplink:
            require(observed["retransmits"] == sent["retransmits"],
                    "independent server retransmit count mismatch")
        return {"receiver_mbps": rate / 1e6, "receiver_bytes": recv["bytes"],
                "seconds": secs, "sender_retransmits": sent["retransmits"]}

    result = {("uplink" if mode == "uplink" else "downlink"):
              direction("", mode == "uplink")}
    if mode == "bidirectional":
        result["uplink"] = direction("_bidir_reverse", True)
    return result


def summarize(path, tag, prefix):
    f = load_archive(path, tag)
    require(f["status"].strip() == "exit=0" and
            f["dual-stack-load-result.txt"].strip() == "dual_stack_load_pass=1" and
            f["short-dual-hold-result.txt"].strip() == "short_dual_hold_pass=1",
            "client load gate failed")
    source = re.search(r"\bipv4=(\S+)", f["early-only-snapshot.txt"])[1]
    require(ipaddress.ip_address(source) in ipaddress.ip_network("192.168.76.0/24"),
            "source outside lab")
    result = {}
    for mode in MODES:
        require(f[f"load-{mode}-exit.txt"].strip() == "0", "load process failed")
        check_link(f[f"load-{mode}-before.txt"])
        check_link(f[f"load-{mode}-after.txt"])
        require(Path(f"{prefix}.load-{mode}-exit.txt").read_text().strip() == "0",
                "Asus iperf process failed")
        result[mode] = iperf(Path(f"{prefix}.load-{mode}.json").read_text(),
                             f[f"load-{mode}.server.json.txt"], mode, source)
        result[mode]["latency"] = {
            family: ping(f[f"load-{mode}-latency-{family}.txt"], 100)
            for family in ("v4", "v6")}
    check_link(f["load-final.txt"])
    return {"source": source, "cases": result,
            "pre_load": {name: ping(f[f"short-hold-{name}.txt"], 440, strict=True)
                         for name in ("1", "2", "v6")},
            "post_load": {name: ping(f[f"post-load-{name}.txt"], 100, strict=True)
                          for name in ("1", "2", "v6")}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive")
    p.add_argument("tag")
    p.add_argument("prefix", type=Path)
    args = p.parse_args()
    print(json.dumps(summarize(args.archive, args.tag, args.prefix), indent=2))


if __name__ == "__main__":
    main()
