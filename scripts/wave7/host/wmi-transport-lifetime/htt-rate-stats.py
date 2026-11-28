#!/usr/bin/env python3
"""Qualify firmware TX rate distributions, independently of PPDU last-rate decoding.

HTT type 9 tag 34: pinned Qualcomm FW API 4e7fbfa23c97c619a3404bb249c125925edffc8c,
htt_stats_tx_pdev_rate_stats_tlv through tx_bw_320mhz. These are separate
marginals over pdev traffic; do not treat them as joint rate observations,
per-peer measurements, or MPDU retry counts. Index 3 of BW combines
160 and 80+80 MHz; MCS indices 14/15 are retained as firmware indices.
"""
import re

BEGIN = re.compile(r"HTT_RATE_BEGIN ([^/\s]+/mac\d+) 9 (\d+\.\d{2})")
END = re.compile(r"HTT_RATE_END ([^/\s]+/mac\d+) 9 (\d+\.\d{2}) rc=(\d+)")
HEADER = "HTT_TX_PDEV_RATE_STATS_TLV:"
ARRAYS = {"tx_mcs": (0, 16), "tx_nss": (1, 8), "tx_bw": (0, 5),
          "tx_pream": (0, 7), **{f"tx_gi[{i}]": (0, 14) for i in range(4)}}
SCALARS = {"tx_ldpc", "rts_cnt", "rts_success"}
PER_ARRAYS = {"mcs_drop_rate": (0, 16), "per_histogram_count": (0, 101)}
PER_SCALARS = {"rate_retry_mcs_drop_cnt", "low_latency_rate_cnt",
               "su_burst_rate_drop_cnt", "su_burst_rate_drop_fail_cnt"}
PER_HEADER = "PER_HISTOGRAM_STATS"
DURATION_HEADER = "HTT_TX_PDEV_PPDU_DUR_TLV:"
DURATION_ARRAYS = {"tx_ppdu_dur_hist": (0, 16), "tx_ofdma_ppdu_dur_hist": (0, 16)}
DURATION_COUNTERS = {"tx_success_time_us", "tx_fail_time_us", "pdev_up_time_us"}



def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def ms(s):
    sec, hundredths = s.split(".")
    return int(sec) * 1000 + int(hundredths) * 10


def field(lines, name):
    hits = [m[1] for line in lines if (m := re.fullmatch(
        rf"\s*{re.escape(name)}\s*=\s*(.*?)\s*", line))]
    require(len(hits) == 1, "missing or duplicate " + name)
    return hits[0]


def scalar(lines, name, limit=2**32):
    value = field(lines, name)
    require(re.fullmatch(r"\d+", value) and int(value) < limit, "invalid " + name)
    return int(value)


def histogram(lines, name, first, length):
    items = field(lines, name).split(",")
    require(len(items) == length, "incomplete " + name)
    result = []
    for i, item in enumerate(items, first):
        m = re.fullmatch(r"\s*(\d+):(\d+)\s*", item)
        require(m and int(m[1]) == i and int(m[2]) < 2**32, "invalid " + name)
        result.append(int(m[2]))
    return result


def decode(lines):
    require(lines.count(HEADER) == 1, "missing or duplicate TX rate TLV")
    i = lines.index(HEADER) + 1
    j = i
    while j < len(lines) and lines[j].strip() and not lines[j].endswith("_TLV:"):
        j += 1
    body = lines[i:j]
    mac_id = scalar(body, "mac_id", 256)
    arrays = {k: histogram(body, k, *shape) for k, shape in ARRAYS.items()}
    counters = {k: scalar(body, k) for k in sorted(SCALARS)}
    # ack_rssi is a last-sample gauge in dB above noise floor, not a counter.
    gauge = scalar(body, "ack_rssi")
    # Vendor type 9 may include a separate PPDU PER / rate-drop TLV.
    # The driver prints its scalars before the histogram header.
    extras = lines[:i-1] + lines[j:]
    optional = (PER_HEADER in extras or any(
        re.match(rf"\s*{re.escape(k)}\s*=", line)
        for k in PER_ARRAYS.keys() | PER_SCALARS for line in extras))
    if optional:
        require(extras.count(PER_HEADER) == 1, "missing or duplicate PER histogram")
        counters.update({k: scalar(extras, k) for k in sorted(PER_SCALARS)})
        arrays.update({k: histogram(extras, k, *shape) for k, shape in PER_ARRAYS.items()})
    if DURATION_HEADER in extras:
        require(extras.count(DURATION_HEADER) == 1, "duplicate PPDU duration TLV")
        start = extras.index(DURATION_HEADER) + 1
        end = start
        while end < len(extras) and extras[end].strip() and not extras[end].endswith("_TLV:"):
            end += 1
        dur = extras[start:end]
        counters.update({k: scalar(dur, k, 2**64) for k in sorted(DURATION_COUNTERS)})
        arrays.update({k: histogram(dur, k, *shape) for k, shape in DURATION_ARRAYS.items()})
    return dict(mac_id=mac_id, counters=counters, histograms=arrays, ack_rssi_raw=gauge)


def describe_snapshot(lines, witness):
    try:
        require(witness["qualified"] and witness["radios"], "unqualified pdev TX reset witness")
        radios = {}
        i = 0
        while i < len(lines):
            if not lines[i].strip():
                i += 1
                continue
            b = BEGIN.fullmatch(lines[i])
            require(b and b[1] not in radios, "invalid or duplicate rate begin")
            j = i + 1
            while j < len(lines) and not lines[j].startswith(("HTT_RATE_BEGIN ", "HTT_RATE_END ")):
                j += 1
            e = END.fullmatch(lines[j]) if j < len(lines) else None
            require(e and e[1] == b[1] and e[3] == "0", "unsealed or failed rate reply")
            start, end = ms(b[2]), ms(e[2])
            require(0 <= end - start < 2900, "rate request may have timed out")
            r = decode(lines[i+1:j])
            require(b[1] in witness["radios"] and
                    r["mac_id"] == witness["radios"][b[1]]["mac_id"], "rate MAC identity mismatch")
            radios[b[1]] = dict(start_ms=start, end_ms=end, **r)
            i = j + 1
        require(radios.keys() == witness["radios"].keys(), "incomplete rate radio coverage")
        return dict(qualified=True, radios=radios)
    except ValueError as exc:
        return dict(qualified=False, reason=str(exc))


def compare(before, after, tx_before, tx_after, tx):
    try:
        require(before["qualified"] and after["qualified"], "unqualified rate snapshot")
        require(tx["qualified"], "unqualified pdev TX reset witness")
        require(before["radios"].keys() == after["radios"].keys() == tx["radios"].keys(),
                "rate radio identity changed")
        radios = {}
        for radio, a in before["radios"].items():
            b = after["radios"][radio]
            require(a["mac_id"] == b["mac_id"] == tx["radios"][radio]["mac_id"],
                    "rate MAC identity changed")
            require(tx_before["radios"][radio]["end_ms"] <= a["start_ms"] and
                    b["end_ms"] <= tx_after["radios"][radio]["start_ms"],
                    "rate interval not bracketed by pdev reset witness")
            lo, hi = b["start_ms"] - a["end_ms"], b["end_ms"] - a["start_ms"]
            require(0 < lo <= hi, "overlapping or reversed rate intervals")
            p, q = a["counters"], b["counters"]
            require(p.keys() == q.keys() and all(p[k] <= q[k] for k in p),
                    "rate counter schema change or reset")
            x, y = a["histograms"], b["histograms"]
            require(x.keys() == y.keys(), "rate histogram schema changed")
            hist = {}
            fractions = {}
            for name in x:
                require(len(x[name]) == len(y[name]) and all(v <= w for v, w in zip(x[name], y[name])),
                        "rate histogram reset or wrap: " + name)
                values = [w-v for v,w in zip(x[name], y[name])]
                hist[name] = values
                total = sum(values)
                fractions[name] = [100*v/total for v in values] if total else None
            radios[radio] = dict(mac_id=a["mac_id"], wall_ms_range=[lo, hi],
                                 delta={k:q[k]-p[k] for k in p},
                                 histogram_delta=hist, fraction_pct=fractions,
                                 ack_rssi_raw={"before":a["ack_rssi_raw"],"after":b["ack_rssi_raw"]})
        return dict(qualified=True, radios=radios)
    except ValueError as exc:
        return dict(qualified=False, reason=str(exc))
