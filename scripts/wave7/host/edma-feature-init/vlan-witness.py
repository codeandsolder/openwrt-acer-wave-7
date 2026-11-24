#!/usr/bin/env -S uv run --no-project python
"""Tagged IPv4/IPv6 payload integrity on the sealed DSA-aware EDMA boot."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import socket
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("payload_witness", HERE / "payload-witness.py")
pw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pw)
p = pw.probe
require = pw.require
remote = pw.remote
VLAN = {"direct": (3760, "198.18.76.1", "198.18.76.2"),
        "switch": (3761, "198.18.76.5", "198.18.76.6")}

def names(path):
    vid, dst, src = VLAN[path]
    return f"w7v{vid}", dst, src, f"fd76:7:{vid}::1", f"fd76:7:{vid}::2"

def addresses(path, family):
    dev, dst, src, dst6, src6 = names(path)
    if family == socket.AF_INET:
        return (dst, pw.PORT), (src, 0), f"{dst}:{pw.PORT}", src, dev
    return (dst6, pw.PORT, 0, 0), (src6, 0, 0, 0), f"[{dst6}]:{pw.PORT}", src6, dev

def counters(path):
    dev = names(path)[0]
    return {k: int((Path("/sys/class/net") / dev / "statistics" / k).read_text())
            for k in ("rx_bytes", "tx_bytes")}

def verify_host():
    for path, (vid, _, _) in VLAN.items():
        dev, dst, src, dst6, src6 = names(path)
        row, = json.loads(p["run"](["ip", "-j", "-d", "link", "show", "dev", dev]))
        require(row["link"] == pw.PATHS[path][1], "wrong VLAN parent")
        require(row["linkinfo"]["info_kind"] == "vlan" and
                row["linkinfo"]["info_data"]["id"] == vid, "wrong VLAN ID")
        for target, source in ((dst, src), (dst6, src6)):
            route, = json.loads(p["run"](["ip", "-j", "route", "get", target, "from", source]))
            require(route["dev"] == dev, "wrong VLAN route")

def verify_trace(raw, path):
    device = "lan" if path == "direct" else "switch"
    tagged_offset = 18 if path == "direct" else 26
    tagged = []
    for line in raw.splitlines():
        if "net_dev_start_xmit: " not in line:
            continue
        f = dict(re.findall(r"(\w+)=([^ ]+)", line.split("net_dev_start_xmit: ", 1)[1]))
        if f["dev"] == device and (int(f["network_offset"]) == tagged_offset or
                (f.get("vlan_tagged") == "1" and int(f["vlan_tci"], 16) & 0xfff == VLAN[path][0])):
            tagged.append(f)
    require(tagged, "no tagged frames at physical driver boundary")
    summary = {"tagged": len(tagged), "gso": sum(int(f["gso_size"]) > 0 for f in tagged),
               "partial": sum(int(f["ip_summed"]) == 3 for f in tagged)}
    if path == "switch":
        require(summary["gso"] == summary["partial"] == 0, "DSA parser offload leak")
    return summary

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args()
    record = pw.cohort["load_run"](args.run.resolve())
    require(record and record["variant"] == "edma-dsa-feature-check" and
            record["outcome"] == "clean", "requires sealed clean DSA candidate")
    variant, boot = record["variant"], record["boot"]
    require(args.attempt > 0, "invalid attempt")
    out = args.run.resolve() / ("payload-vlan-direct-switch-trace" + (f"-r{args.attempt}" if args.attempt > 1 else ""))
    report = {"boot": boot, "variant": variant, "cases": []}
    failure = None
    created = []
    marker = f"wave7-vlan-witness-{boot}-{args.attempt}"
    firewall = False
    with p["lab_session"](out):
        try:
            pw.bench["sample"](out, "initial", variant, boot)
            verify_host()
            require(remote("cat /sys/class/net/br-lan/bridge/vlan_filtering").strip() == "0",
                    "bridge VLAN filtering is enabled")
            existing = remote("cat /proc/net/vlan/config")
            (out / "router-vlan-before.txt").write_text(existing)
            for path, (vid, _, _) in VLAN.items():
                dev, dst, src, dst6, src6 = names(path)
                require(dev not in existing and not re.search(rf"\|\s*{vid}\s*\|", existing),
                        "VLAN already exists")
                remote(f"set -e; test ! -e /sys/class/net/{dev}; ip link add link br-lan name {dev} type vlan id {vid}")
                created.append(dev)
                remote(f"set -e; ip addr add {dst}/30 dev {dev}; ip -6 addr add {dst6}/64 dev {dev}; ip link set {dev} up")
            firewall_before = remote("nft -a list chain inet fw4 input")
            (out / "firewall-before.txt").write_text(firewall_before)
            require(marker not in firewall_before, "stale test rule")
            firewall = True
            for path in VLAN:
                dev, dst, src, dst6, src6 = names(path)
                for proto, source, dest in (("ip", src, dst), ("ip6", src6, dst6)):
                    remote(f"nft insert rule inet fw4 input iifname {dev} {proto} saddr {source} {proto} daddr {dest} "
                           f"meta l4proto '{{ tcp, udp }}' th dport {pw.PORT} counter accept comment '{marker}'")
                remote(f"nft insert rule inet fw4 input iifname {dev} icmpv6 type "
                       f"'{{ nd-neighbor-solicit, nd-neighbor-advert }}' counter accept comment '{marker}'")
            (out / "firewall-active.txt").write_text(remote("nft -a list chain inet fw4 input"))
            time.sleep(2)
            (out / "router-vlan-active.txt").write_text(remote("cat /proc/net/vlan/config; ip addr show"))
            (out / "features.txt").write_text(remote(
                "for d in switch lan1 lan br-lan w7v3760 w7v3761; do echo === $d ===; ethtool -k $d; done"))
            payload = pw.pattern(0, pw.LENGTH)
            with pw.remote_peer(out, boot, args.binary.resolve()) as binary, pw.trace_instance(out, boot, True) as trace:
                for path in VLAN:
                    for family in (socket.AF_INET, socket.AF_INET6):
                        for mode, mss in (("tcp-send",0), ("tcp-receive",0), ("tcp-send",512),
                                          ("tcp-receive",512), ("udp",0)):
                            before = counters(path)
                            tag = f'{path}-v{4 if family == socket.AF_INET else 6}-{mode}-mss{mss or "default"}'
                            def call():
                                return pw.run_case(out, path, family, mode, mss, binary,
                                                   variant, boot, payload, address_resolver=addresses)
                            case = trace(tag, call) if mode == "tcp-send" else call()
                            report["cases"].append(case)
                            after = counters(path)
                            case["vlan_delta"] = {k: after[k]-before[k] for k in before}
                            if case["qualification"] == "PASS":
                                for d, n in case["payload_bytes"].items():
                                    require(case["vlan_delta"]["tx_bytes" if d == "rx" else "rx_bytes"] >= n,
                                            "VLAN interface did not witness payload")
                                if mode == "tcp-send":
                                    case["tagged_trace"] = verify_trace((out / f"{tag}-xmit.trace").read_text(), path)
                            else:
                                raise ValueError(f"{tag}: {case.get('error')}")
            report["status"] = "PASS"
        except Exception as exc:
            report.update(status="FAILED", error=str(exc))
            failure = exc
        finally:
            try:
                if firewall:
                    rules = remote("nft -a list chain inet fw4 input")
                    (out / "firewall-counters.txt").write_text(rules)
                    handles = [re.search(r"# handle (\d+)$", line).group(1)
                               for line in rules.splitlines() if f'comment "{marker}"' in line]
                    for handle in handles:
                        remote(f"nft delete rule inet fw4 input handle {handle}")
                    after = remote("nft -a list chain inet fw4 input")
                    (out / "firewall-after.txt").write_text(after)
                    require(marker not in after, "test firewall rule remains")
                for dev in reversed(created):
                    remote(f"set -e; test \"$(cat /proc/sys/kernel/random/boot_id)\" = {boot}; ip link delete {dev}")
                (out / "router-vlan-after.txt").write_text(remote("cat /proc/net/vlan/config"))
                pw.bench["sample"](out, "final", variant, boot)
            except Exception as exc:
                report.update(status="FAILED", cleanup_error=str(exc))
                failure = exc
            (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if failure:
        raise failure

if __name__ == "__main__":
    main()

