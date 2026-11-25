#!/usr/bin/env python3
"""Summarize sealed MLO hold evidence and post-activation data metadata."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import tarfile

EVENT = re.compile(r"(\d+\.\d+): mt7925_lab_(\w+): (.*)")
FIELDS = re.compile(r"(\w+)=(\S+)")
PING = re.compile(r"bytes from .*?icmp_seq=(\d+)")
TOTAL = re.compile(r"(\d+) packets transmitted, (\d+) received")


def hold_summary(archive, bin_size=40):
    results = []
    with tarfile.open(archive) as tar:
        for member in sorted(tar.getmembers(), key=lambda x: x.name):
            if not re.search(r"/short-hold-(?:[12]|v6)\.txt$", member.name):
                continue
            with tar.extractfile(member) as src:
                text = src.read().decode()
            seq = set(map(int, PING.findall(text)))
            total = TOTAL.search(text)
            sent = int(total[1]) if total else None
            received = int(total[2]) if total else None
            if received is not None and received != len(seq):
                raise ValueError(f"{member.name}: ping count mismatch")
            limit = sent if sent is not None else max(seq, default=0)
            results.append({
                "file": member.name,
                "sent": sent,
                "received": received,
                "observed_unique_replies": len(seq),
                "last_observed_reply": max(seq, default=None),
                "bin_size": bin_size,
                "reply_bins": [sum(start <= n < start + bin_size for n in seq)
                               for start in range(1, limit + 1, bin_size)],
            })
    return results


def trace_summary(path):
    rows = [(float(m[1]), m[2], dict(FIELDS.findall(m[3])))
            for m in EVENT.finditer(path.read_text())]
    keys = [t for t, event, data in rows
            if event == "wtbl_peer" and data.get("stage") == "7"]
    anchor = max(keys, default=None)
    rx = Counter()
    raw = Counter()
    txd = Counter()
    txs = Counter()
    for t, event, data in rows:
        if event == "rx_header" and data.get("wcid") == "4095":
            raw[(data["freq"], "post" if anchor is not None and t >= anchor
                 else "pre_or_no_activation")] += 1
        if anchor is None or t < anchor:
            continue
        if event == "rx_frame" and data.get("data") == data.get("u2m") == "1":
            rx[(int((t-anchor)//2)*2, data["wcid"], data["freq"],
                data["encap"])] += 1
        elif event == "tx_descriptor":
            txd[tuple(data[k] for k in ("wcid", "link", "band", "tgid",
                                       "wlan_idx", "protect", "pairwise",
                                       "keyidx"))] += 1
        elif event == "txs_peer_data":
            txs[tuple(data[k] for k in ("wcid", "link", "band", "ack_error",
                                       "encap"))] += 1

    def counts(counter, names):
        return [dict(zip(names, key), count=count)
                for key, count in sorted(counter.items())]

    return {
        "activation_key_snapshot_monotonic": anchor,
        "unresolved_headers": counts(raw, ("frequency", "phase")),
        "post_activation_rx": counts(rx, ("seconds_bin_start", "wcid",
                                          "frequency", "encap")),
        "post_activation_tx_descriptors": counts(txd, ("wcid", "link", "band",
                                                       "tgid", "wlan_idx",
                                                       "protect", "pairwise",
                                                       "keyidx")),
        "post_activation_tx_status": counts(txs, ("wcid", "link", "band",
                                                  "ack_error", "encap")),
    }


NDP_COUNTERS = ("Icmp6OutRouterSolicits", "Icmp6InRouterAdvertisements",
                "Icmp6OutNeighborSolicits", "Icmp6InNeighborAdvertisements")


def ndp_summary(prefix):
    path = prefix.with_suffix(".client-ip6.txt")
    rows = []
    row = None
    done = None
    for line in path.read_text().splitlines():
        if line.startswith("IP6_SAMPLE "):
            if row is not None:
                raise ValueError("incomplete IPv6 sample")
            fields = dict(FIELDS.findall(line))
            row = {"index": int(fields["index"]), "epoch": float(fields["epoch"]),
                   "monotonic": float(fields["monotonic"]), "counts": {}, "usable": []}
            if row["index"] != len(rows):
                raise ValueError("nonconsecutive IPv6 sample")
        elif line.startswith("IP6_SAMPLE_END "):
            if row is None or int(dict(FIELDS.findall(line))["index"]) != row["index"]:
                raise ValueError("invalid sample end")
            if not set(NDP_COUNTERS).issubset(row["counts"]):
                raise ValueError("missing IPv6 counter")
            rows.append(row)
            row = None
        elif row is not None and line.startswith("IP6_COUNTER "):
            _, key, value = line.split()
            if key in row["counts"]:
                raise ValueError("duplicate IPv6 counter")
            row["counts"][key] = int(value)
        elif row is not None and line.startswith("IP6_ADDR "):
            fields = line.split()
            if "global" in fields and "tentative" not in fields and "dadfailed" not in fields:
                row["usable"].append(fields[fields.index("inet6") + 1])
        elif line.startswith("CLIENT_IP6_OBSERVER_END "):
            done = int(dict(FIELDS.findall(line))["samples"])
    if row is not None or not rows or len(rows) != done:
        raise ValueError("incomplete IPv6 observation")
    transitions = []
    for prev, cur in zip(rows, rows[1:]):
        if cur["monotonic"] <= prev["monotonic"]:
            raise ValueError("nonmonotonic IPv6 sample")
        for key in NDP_COUNTERS:
            delta = cur["counts"][key] - prev["counts"][key]
            if delta < 0:
                raise ValueError("IPv6 counter reset")
            if delta:
                transitions.append({"counter": key, "delta": delta,
                                    "epoch_window": [prev["epoch"], cur["epoch"]]})
    first_global = next(({"epoch": r["epoch"], "addresses": r["usable"]}
                         for r in rows if r["usable"]), None)
    result = {"samples": len(rows), "counter_transitions": transitions,
              "counter_deltas": {k: rows[-1]["counts"][k] - rows[0]["counts"][k]
                                 for k in NDP_COUNTERS},
              "first_usable_global": first_global}
    capture = prefix.with_suffix(".wired-ndp.txt")
    if capture.exists():
        status = prefix.with_suffix(".wired-ndp-status.txt").read_text()
        if not re.search(r"Packets received/dropped on interface 'enp4s0f4u2u4': [0-9]+/0 "
                         r"\(pcap:[0-9]+/dumpcap:0/flushed:0/ps_ifdrop:0\)", status):
            raise ValueError("incomplete or dropped wired capture")
        events = []
        for line in capture.read_text().splitlines():
            epoch, mac_src, mac_dst, src, dst, kind = line.split("\t")
            if kind not in ("133", "134"):
                raise ValueError("unexpected NDP type")
            events.append({"epoch": float(epoch), "mac_src": mac_src, "mac_dst": mac_dst,
                           "src": src, "dst": dst, "type": int(kind)})
        result["wired_events"] = events
        result["wired_counts"] = dict(Counter(str(e["type"]) for e in events))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--band", choices=("24", "5"), default="24")
    args = p.parse_args()
    subprocess.run(["sha256sum", "-c", "SHA256SUMS", "--status"],
                   cwd=args.run, check=True)
    prefix = args.run / ("band-" + args.band)
    result = {
        "run": args.run.name,
        "band": args.band,
        "hold": hold_summary(prefix.with_suffix(".client.tar")),
        "trace": trace_summary(prefix.with_suffix(".client-control-trace.txt")),
        "ap_rx_delta": json.loads(prefix.with_suffix(".rx-delta.json").read_text()),
    }
    if prefix.with_suffix(".client-ip6.txt").exists():
        result["router_discovery"] = ndp_summary(prefix)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
