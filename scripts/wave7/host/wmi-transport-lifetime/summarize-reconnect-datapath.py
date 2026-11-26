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



def token_windows(text, windows):
    """Pair each submitted descriptor with its eventual token return."""
    events = []
    for line in text.splitlines():
        m = LINE.search(line)
        if m and m[2] in {"mt7925_lab_data_txd", "mt7925_lab_data_tx_free"}:
            events.append((float(m[1]), m[2], dict(FIELD.findall(m[3]))))
    pending = {}
    submissions = []
    unmatched_free = 0
    for time, event, fields in sorted(events, key=lambda row: row[0]):
        cookie = fields["cookie"]
        require(cookie not in {"0000000000000000", "(null)"}, "invalid skb cookie")
        if event == "mt7925_lab_data_txd":
            require(cookie not in pending, "duplicate outstanding skb cookie")
            row = {"submitted_at": time, **fields}
            submissions.append(row)
            pending[cookie] = row
        else:
            row = pending.pop(cookie, None)
            if row is None:
                # Return tracing also covers data outside the MLD station.
                unmatched_free += 1
                continue
            require(row["wcid"] == fields["desc_wcid"], "descriptor WCID mismatch")
            header = int(fields["header"], 16)
            row["return"] = {
                "time": time,
                "latency_ms": round((time - row["submitted_at"]) * 1000, 3),
                **fields,
                "header_count": (header >> 24) & 15 if fields["header_valid"] == "1" else None,
                "header_status": (header >> 28) & 3 if fields["header_valid"] == "1" else None,
            }
    result = []
    for window in windows:
        start, stop = window["authorized_at"], window["deauthorized_at"]
        rows = [row for row in submissions if start <= row["submitted_at"] < stop]
        counts = Counter()
        for row in rows:
            returned = row.get("return")
            key = (row["protocol"], row["wcid"], row["band"],
                   "missing" if returned is None else str(returned["header_count"]),
                   "missing" if returned is None else
                   "after_deauthorize" if returned["time"] >= stop else "before_deauthorize")
            counts[key] += 1
        result.append({
            "authorized_at": start, "deauthorized_at": stop,
            "submitted": len(rows),
            "returned": sum("return" in row for row in rows),
            "groups": [{"fields": list(key), "count": count}
                       for key, count in sorted(counts.items())],
            "descriptors": rows,
        })
    return {"unmatched_free": unmatched_free, "windows": result}

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
    txd = "cookie=00000000abcd1234 protocol=0x0800 wcid=2 band=1"
    free = "cookie=00000000abcd1234 desc_wcid=2 header_valid=1 header=40000000"
    token_trace = line(10.1, "mt7925_lab_data_txd", txd)
    token_trace += line(11.2, "mt7925_lab_data_tx_free", free)
    token_trace += line(20.1, "mt7925_lab_data_txd", txd)
    token_trace += line(20.2, "mt7925_lab_data_tx_free", free)
    tokens = token_windows(token_trace, result)["windows"]
    assert tokens[0]["groups"][0]["fields"][-1] == "after_deauthorize"
    assert tokens[0]["descriptors"][0]["return"]["header_count"] == 0
    assert tokens[1]["returned"] == 1
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
            text = (args.trial / name).read_text()
            result[side] = parse_trace(text, side)
            if side == "client" and "mt7925_lab_data_txd:" in text:
                result["data_tokens"] = token_windows(text, result[side])
        print(json.dumps(result, indent=2))
