#!/usr/bin/env python3
"""Attribute common reply silence in an independent low-rate MLO hold.

A truncated ping log proves only observed silence, not a count of sent
packets. Client trace boundaries are separate observations, not unique
packets or proof of OTA delivery. BSS indices are not mac80211 link IDs.
"""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from decimal import Decimal as D
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


trace = module("client_trace", HERE.parent / "secondary-ap/report-client-kernel-trace.py")
load = module("client_archive", HERE / "load-result.py")
tokens = module("client_tokens", HERE / "summarize-reconnect-datapath.py")
TIMED = re.compile(r"^\[(\d+\.\d+)\] (.*)$")
REPLY = re.compile(r"\bbytes from .*?\bicmp_seq=(\d+)\b")
PATHS = ("1", "2", "v6")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def ping(text):
    replies = {}
    observed = []
    for line in text.splitlines():
        m = TIMED.fullmatch(line)
        if not m:
            continue
        when, msg = D(m[1]), m[2]
        observed.append(when)
        r = REPLY.search(msg)
        if r:
            seq = int(r[1])
            require(seq > 0, "invalid ping sequence")
            # A duplicate reply is still observed traffic, but does not
            # increase the count of distinct replies.
            replies.setdefault(seq, []).append(when)
    require(observed and all(a <= b for a,b in zip(observed, observed[1:])),
            "no timestamped ping evidence or clock step")
    summary = load.PING.search(text)
    if summary:
        sent, received = map(int, summary.groups())
        require(0 <= received <= sent and received == len(replies) and
                all(n <= sent for n in replies), "inconsistent ping summary")
        missing = sorted(set(range(1, sent+1)) - replies.keys())
    else:
        sent = received = missing = None
    return dict(first_observed=observed[0], last_observed=observed[-1],
                replies=replies, summary=dict(sent=sent, received=received,
                missing_sequences=missing, unique_replies_observed=len(replies),
                duplicate_replies_observed=sum(len(v)-1 for v in replies.values())))


def silence(paths, threshold=D(".25")):
    require(paths.keys() == set(PATHS), "incomplete hold path set")
    # Only use the time span that all three ping processes actually logged.
    start = max(p["first_observed"] for p in paths.values())
    stop = min(p["last_observed"] for p in paths.values())
    require(start <= stop, "no common observed interval")
    all_replies = sorted(set(t for p in paths.values() for times in p["replies"].values()
                             for t in times if start <= t <= stop))
    # Do not silently drop late/out-of-order replies or fabricate send times.
    edges = [start, *all_replies, stop]
    windows = []
    for i, (a,b) in enumerate(zip(edges,edges[1:])):
        if b-a < threshold:
            continue
        windows.append(dict(start=a, end=b, duration_s=b-a,
                            left_censored=i==0, right_censored=i==len(edges)-2))
    return start, stop, windows


def signature(name, payload):
    fields = dict(re.findall(r"(\w+)=([^\s]+)", payload))
    keep = {
        "mt7925_lab_absence": ("bss", "tag", "len", "absent", "quota"),
        "mt7925_lab_mcu_rx": ("eid", "option", "length"),
        "mt7925_lab_data_txd": ("wcid", "link", "band", "qid", "protocol"),
        "mt7925_lab_data_tx_free": ("desc_wcid", "fw_wcid", "header_valid"),
        "mt7925_lab_txs_peer_data": ("wcid", "link", "band", "ack_error", "encap"),
        "mt7925_lab_rxdesc": ("result", "resolved_wcid", "link", "freq", "encap"),
        "mt7925_lab_rx_frame": ("wcid", "freq", "raw_bss", "encap", "u2m"),
    }.get(name)
    if name in tokens.NET:
        return (name, fields["dev"], fields["protocol"])
    if keep:
        require(all(k in fields for k in keep), f"missing {name} field")
        if name == "mt7925_lab_absence":
            require(fields["tag"] == "0" and fields["len"] == "8" and
                    fields["absent"] in ("0","1"), "unknown absence format")
        return (name, *(f"{k}={fields[k]}" for k in keep))
    return (name,)


def summarize(files, text):
    require(text.count("CLIENT_CONTROL_TRACE_READY ") == 1 and
            text.count("CLIENT_CONTROL_TRACE_END rc=0") == 1,
            "incomplete stall trace")
    parsed = trace.parse(text)
    lo, hi = parsed["offset_lo"], parsed["offset_hi"]
    paths = {k: ping(files[f"short-hold-{k}.txt"]) for k in PATHS}
    start, stop, gaps = silence(paths)
    require(parsed["first_anchor"] + hi <= start and stop <= parsed["last_anchor"] + lo,
            "hold lies outside clock anchor coverage")
    submissions, unmatched = tokens.data_token_submissions(text)
    events = parsed["events"]
    ts = [e[0] for e in events]
    # Only count events definitely within the observed gap for every clock
    # offset; preserve nearby state transitions with uncertainty bounds.
    for gap in gaps:
        a,b = gap["start"],gap["end"]
        left,right = bisect_left(ts,a-lo),bisect_right(ts,b-hi)
        selection = events[left:right] if right >= left else []
        counts = Counter(signature(name,payload) for _,name,_,payload,_ in selection)
        gap["trace_counts"] = [dict(fields=list(key), count=n)
                               for key,n in sorted(counts.items())]
        nearby = []
        for t,name,_,payload,_ in events[bisect_left(ts,a-D(".2")-hi):
                                          bisect_right(ts,b+D(".2")-lo)]:
            if name in ("mt7925_lab_absence","mt7925_lab_beacon_loss","mt7925_lab_roc_sync",
                        "drv_hw_scan","api_scan_completed","api_beacon_loss","api_connection_loss"):
                nearby.append(dict(event=name, fields=payload,
                                   relative_to_start_bounds_s=[t+lo-a,t+hi-a]))
        gap["nearby_state_transitions"] = nearby
        selected = [s for s in submissions if D(str(s["submitted_at"]))+lo >= a
                    and D(str(s["submitted_at"]))+hi <= b]
        hist = Counter()
        for row in selected:
            ret = row.get("return")
            if ret is None:
                key = "unreturned_in_trace"
            elif ret["header_count"] is None:
                key = "invalid_header"
            else:
                key = f"attempt_field={ret['header_count']} status={ret['header_status']}"
            hist[key]+=1
        gap["descriptor_submissions"] = len(selected)
        gap["eventual_token_return_histogram"] = dict(sorted(hist.items()))
        gap["token_returned_definitely_inside"] = sum(
            "return" in s and D(str(s["return"]["time"]))+hi <= b for s in selected)
    return dict(clock_offset_bounds_s=[lo,hi], trace_anchors=parsed["anchors"],
                common_observed_start=start, common_observed_end=stop,
                ping={k:v["summary"] for k,v in paths.items()},
                total_descriptor_submissions=len(submissions),
                unmatched_token_returns=unmatched, common_silence=gaps)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("tag")
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    files = load.load_archive(args.archive,args.tag)
    print(json.dumps(summarize(files,args.trace.read_text()),default=str,indent=2))


if __name__ == "__main__":
    main()
