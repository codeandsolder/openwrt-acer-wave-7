#!/usr/bin/env python3
"""Correlate low-volume management TX events and distinguish missing completion."""
import argparse
import json
import re
from pathlib import Path

EVENT = re.compile(r"\[\d+\]\s+\S+\s+(\d+\.\d+): (mt7925_lab_mgmt_\w+): (.*)")
FIELDS = re.compile(r"\b(\w+)=(\S+)")
ABSENCE = re.compile(r"\[\d+\]\s+\S+\s+(\d+\.\d+): mt7925_lab_absence: (.*)")
COUNTER = re.compile(r"^(?:entries|overrun|commit overrun|dropped events): (\d+)$", re.M)
KIND = {0x00: "association_request", 0x10: "association_response",
        0x20: "reassociation_request", 0x30: "reassociation_response",
        0xa0: "disassociation", 0xb0: "authentication", 0xc0: "deauthentication",
        0xd0: "action", 0xe0: "action_no_ack"}


def decode_descriptor(fields):
    d0, d1, d2, d3, d5, d6 = (int(fields[f"d{i}"], 16) for i in (0, 1, 2, 3, 5, 6))
    return {
        "queue": (d0 >> 25) & 0x7f,
        "wcid": d1 & 0xfff,
        "tgid": (d1 >> 12) & 3,
        "own_mac": (d1 >> 25) & 0x3f,
        "frame_type": (d2 >> 4) & 3,
        "frame_subtype": d2 & 0xf,
        "protect": bool(d3 & 2),
        "no_ack": bool(d3 & 1),
        "remaining_tx_count": (d3 >> 11) & 31,
        "pid": d5 & 0xff,
        "status_requested": bool(d5 & (1 << 10)),
        "fixed_link": bool(d5 & (1 << 15)),
        "disable_mat": bool(d6 & 8),
        "fixed_rate_index": (d6 >> 16) & 0x3f,
    }


def summarize(text):
    stats = COUNTER.findall(text)
    if not stats or len(stats) % 4 or any(int(v) for v in stats):
        raise ValueError("trace incomplete, unread or lost events")
    if text.count("CLIENT_CONTROL_TRACE_END rc=0") != 1:
        raise ValueError("missing successful trace cleanup")
    events, absence_events = [], []
    for line in text.splitlines():
        m = EVENT.search(line)
        if m:
            t, name, raw = m.groups()
            fields = dict(FIELDS.findall(raw))
            fields["time"] = float(t)
            fields["event"] = name.removeprefix("mt7925_lab_mgmt_")
            events.append(fields)
        elif m := ABSENCE.search(line):
            t, raw = m.groups()
            f = {key: int(value) for key, value in FIELDS.findall(raw)}
            if f["tag"] != 0 or f["len"] < 8 or f["absent"] not in (0, 1):
                raise ValueError(f"unexpected BSS absence event: {line}")
            absence_events.append({"time": float(t), **f})
        elif "mt7925_lab_absence:" in line:
            raise ValueError(f"unparsed absence event: {line}")
        elif "mt7925_lab_mgmt_" in line:
            raise ValueError(f"unparsed management trace line: {line}")
    events.sort(key=lambda e: e["time"])
    records, unmatched = [], []
    latest = {}
    for e in events:
        cookie, fc = e["cookie"], int(e["fc"], 16)
        if cookie in ("(ptrval)", "(null)", "0000000000000000"):
            raise ValueError("no usable skb correlation cookie")
        if e["event"] == "txd":
            descriptor = decode_descriptor(e)
            if descriptor["wcid"] != int(e["wcid"]):
                raise ValueError("descriptor WCID differs from selected WCID")
            rec = {
                "kind": KIND.get(fc & 0xf0, f"0x{fc & 0xf0:02x}"),
                "submission": e, "descriptor": descriptor,
                "completions": [],
            }
            records.append(rec)
            latest[cookie] = rec
        elif e["event"] in ("tx_free", "txs"):
            rec = latest.get(cookie)
            # Cookies may be reused after skb retirement. Do not silently
            # attribute a duplicate or mismatched event to another frame.
            if (rec is None
                    or int(rec["submission"]["fc"], 16) & 0xfc != fc & 0xfc
                    or any(x["event"] == e["event"] for x in rec["completions"])):
                unmatched.append(e)
                continue
            e["latency_ms"] = (e["time"] - rec["submission"]["time"]) * 1000
            if e["event"] == "tx_free" and e["header_valid"] == "1":
                header = int(e["header"], 16)
                e["preceding_header_count"] = (header >> 24) & 0xf
                e["preceding_header_status"] = (header >> 28) & 3
            rec["completions"].append(e)
        else:
            raise ValueError(f"unexpected management event {e['event']}")
    if not records:
        raise ValueError("no management submissions")
    absence_events.sort(key=lambda e: e["time"])
    def last_observed(t):
        state = {}
        for e in absence_events:
            if e["time"] > t:
                break
            state[e["bss"]] = {**e, "age_ms": (t - e["time"]) * 1000}
        return state

    for rec in records:
        # This is the last *observed* event per BSS, not a proof of
        # current channel privilege. Unknown BSSes are left absent from
        # the map rather than interpreted as available.
        rec["last_bss_absence_at_submission"] = last_observed(rec["submission"]["time"])
        for event in rec["completions"]:
            event["last_bss_absence_at_completion"] = last_observed(event["time"])
        rec["firmware_token_released"] = any(e["event"] == "tx_free" for e in rec["completions"])
        rec["matched_tx_status"] = any(e["event"] == "txs" for e in rec["completions"])
    return {"frames": records, "unmatched": unmatched, "bss_absence_events": absence_events}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.trace.read_text()), indent=2))
