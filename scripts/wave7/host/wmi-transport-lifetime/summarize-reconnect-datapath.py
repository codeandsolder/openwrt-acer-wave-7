#!/usr/bin/env python3
"""Compare independently clocked authorization windows at lab data boundaries."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

LINE = re.compile(r"\[\d+\]\s+\S+\s+(\d+\.\d+): (\w+): (.*)")
FIELD = re.compile(r"(\w+)=([^\s]+)")
STATE = re.compile(r"\bsta:([0-9a-f:]+) state: (\d+)->(\d+)")
LOSS = re.compile(r"^(?:overrun|commit overrun|dropped events):\s*(\d+)$", re.M)
NET = {
    "net_dev_start_xmit", "netif_receive_skb_entry",
    "netif_receive_skb_list_entry", "napi_gro_receive_entry", "netif_rx_entry",
}
RX = {"mt7925_lab_rxdesc", "mt7925_lab_rx_frame", "mt7925_lab_txs_peer_data",
      "mt7925_lab_absence"}
PROTOCOLS = {0x800: "IPv4", 0x806: "ARP", 0x86dd: "IPv6"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_seal(path):
    seen = set()
    for line in (path / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.removeprefix("./")
        require("/" not in name and name not in seen, "invalid seal path")
        with (path / name).open("rb") as f:
            require(hashlib.file_digest(f, "sha256").hexdigest() == digest,
                    f"seal mismatch: {name}")
        seen.add(name)
    return seen


def parse_trace(text, side):
    marker = {"client": "CLIENT_CONTROL_TRACE", "ap": "AP_CONTROL_TRACE"}[side]
    require(text.count(marker + "_READY ") == 1 and
            text.count(marker + "_END rc=0") == 1, f"{side}: incomplete trace")
    loss = LOSS.findall(text)
    require(loss and len(loss) % 3 == 0 and not any(map(int, loss)),
            f"{side}: trace losses or missing stats")
    windows = []
    active = {}
    observations = []
    for line in text.splitlines():
        m = LINE.search(line)
        if not m:
            continue
        timestamp, event, body = m.groups()
        time = float(timestamp)
        if event == "drv_sta_state":
            state = STATE.search(body)
            require(state, f"{side}: malformed station state")
            address, old, new = state.groups()
            if old == "3" and new == "4":
                require(address not in active, f"{side}: duplicate authorization")
                active[address] = time
            elif old == "4" and new == "3":
                require(address in active, f"{side}: unpaired deauthorization")
                windows.append((active.pop(address), time, address))
        elif event in NET | RX:
            fields = dict(FIELD.findall(body))
            if event in NET:
                dev = fields["dev"]
                allowed = {"wlp2s0"} if side == "client" else {"ap-mld0", "br-lan"}
                protocol = int(fields["protocol"], 16)
                require(dev in allowed and protocol in PROTOCOLS, f"{side}: bad filter")
                key = (event, dev, PROTOCOLS[protocol], fields["len"])
            elif event == "mt7925_lab_rxdesc":
                key = (event, fields["result"], fields["resolved_wcid"],
                       fields["link"], fields["valid"], fields["freq"], fields["encap"])
            elif event == "mt7925_lab_rx_frame":
                require(fields["data"] == "1", "non-data RX frame")
                key = (event, fields["wcid"], fields["freq"], fields["raw_bss"],
                       fields["encap"], fields["u2m"])
            elif event == "mt7925_lab_txs_peer_data":
                key = (event, fields["wcid"], fields["link"], fields["band"],
                       fields["ack_error"], fields["encap"])
            else:
                key = (event, fields["bss"], fields["absent"], fields["quota"])
            observations.append((time, key))
    require(not active, f"{side}: unclosed authorized peer lifetime")
    require(len(windows) >= 2, f"{side}: missing reassociation window")
    windows.sort()
    require(len({w[2] for w in windows}) == 1, f"{side}: unrelated stations in trace")
    # Count every tracepoint separately; RX paths may see the same skb at
    # multiple layers. Counts are not unique packets or RF transmission counts.
    results = []
    for start, stop, address in windows:
        require(stop > start, f"{side}: inverted window")
        rows = {}
        for name, end in (("first_2s", min(stop, start + 2)),
                          ("first_8s", min(stop, start + 8)),
                          ("whole", stop)):
            counts = Counter()
            first = {}
            last = {}
            for timestamp, key in observations:
                if start <= timestamp < end:
                    counts[key] += 1
                    first[key] = min(first.get(key, timestamp), timestamp)
                    last[key] = max(last.get(key, timestamp), timestamp)
            rows[name] = [
                {"fields": list(key), "count": count,
                 "first_s": round(first[key] - start, 6),
                 "last_s": round(last[key] - start, 6)}
                for key, count in sorted(counts.items())
            ]
        results.append({"authorized_at": start, "deauthorized_at": stop,
                        "duration_s": stop - start, "station": address, **rows})
    require(any(row["fields"][0] in NET for row in results[0]["whole"]),
            f"{side}: initial association lacks net trace")
    if side == "client":
        require(any(row["fields"][0] == "mt7925_lab_rx_frame"
                    for row in results[0]["whole"]), "missing initial RX-frame trace")
    return results


def selftest():
    def line(t, e, body):
        return f"worker [001] ..... {t:.6f}: {e}: {body}\n"

    s = "AP_CONTROL_TRACE_READY boot=x\n"
    for start in (10, 20):
        s += line(start, "drv_sta_state", "sta:aa:bb:cc:dd:ee:ff state: 3->4")
        s += line(start + 0.1, "net_dev_start_xmit",
                  "dev=ap-mld0 protocol=0x0800 len=300")
        s += line(start + 1, "drv_sta_state", "sta:aa:bb:cc:dd:ee:ff state: 4->3")
    s += "overrun: 0\ncommit overrun: 0\ndropped events: 0\nAP_CONTROL_TRACE_END rc=0\n"
    result = parse_trace(s, "ap")
    assert len(result) == 2 and result[1]["whole"][0]["count"] == 1
    for broken in (s.replace("overrun: 0", "overrun: 1", 1),
                   s.replace("AP_CONTROL_TRACE_END rc=0", ""),
                   s.replace("dev=ap-mld0", "dev=lan1")):
        try:
            parse_trace(broken, "ap")
        except ValueError:
            pass
        else:
            raise AssertionError("bad trace accepted")
    print("RECONNECT_DATAPATH_SELFTEST_PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial", type=Path, nargs="?")
    parser.add_argument("--band", choices=("24", "5"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
    else:
        require(args.trial and args.band, "trial and band required")
        sealed = verify_seal(args.trial)
        result = {}
        for side in ("client", "ap"):
            name = f"band-{args.band}.{side}-control-trace.txt"
            require(name in sealed, f"unsealed {side} trace")
            result[side] = parse_trace((args.trial / name).read_text(), side)
        print(json.dumps(result, indent=2))
