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
            if not re.search(r"/short-hold-[12]\.txt$", member.name):
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
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
