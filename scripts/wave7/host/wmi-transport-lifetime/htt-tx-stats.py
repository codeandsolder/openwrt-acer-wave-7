#!/usr/bin/env python3
"""Qualify edge-only firmware HTT pdev TX counters without assuming airtime semantics."""
import re

BEGIN = re.compile(r"HTT_BEGIN ([^/\s]+/mac\d+) (\d+\.\d{2}) selector=([01])")
END = re.compile(r"HTT_END ([^/\s]+/mac\d+) (\d+\.\d{2}) rc=(\d+)")
COUNTERS = set("""
hw_queued hw_reaped underrun hw_flush hw_filt tx_abort ppdu_ok
mpdu_requeued tx_xretry mpdu_dropped_xretry illegal_rate_phy_err tx_timeout
phy_underrun seq_failed_queueing mpdus_sw_flush mpdus_hw_filter
mpdus_truncated mpdus_ack_failed mpdus_expired mpdus_seq_hw_retry
remove_mpdus_max_retries num_total_ppdus_tried_ota num_data_ppdus_tried_ota
mpdu_tried pdev_resets fes_offsets_err_cnt
hw_paused txop_ovf seq_posted seq_completed seq_restarted seq_txop_repost_stop
seq_qdepth_repost_stop seq_min_msdu_repost_stop mu_seq_min_msdu_repost_stop
next_seq_cancel seq_switch_hw_paused mpdu_count_tqm msdu_count_tqm
mpdu_removed_tqm msdu_removed_tqm local_ctrl_mgmt_enqued local_ctrl_mgmt_freed
local_data_enqued local_data_freed ack_tlv_proc self_triggers
""".split())
REQUIRED = COUNTERS | {"mac_id", "tx_active_dur_us_low", "tx_active_dur_us_high"}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def ms(s):
    sec, hundredths = s.split(".")
    return int(sec) * 1000 + int(hundredths) * 10


def common(lines):
    header = "HTT_TX_PDEV_STATS_CMN_TLV:"
    require(lines.count(header) == 1, "missing or ambiguous TX common TLV")
    vals = {}
    for line in lines[lines.index(header) + 1:]:
        if not line.strip() or line.endswith(":"):
            break
        m = re.fullmatch(r"\s*(\w+)\s*=\s*(\d+)\s*", line)
        require(m, "malformed TX common TLV")
        k, v = m[1], int(m[2])
        require(k not in vals and v < 2**32, "invalid or duplicate TX common field")
        vals[k] = v
    require(REQUIRED <= vals.keys(), "incomplete TX common TLV")
    counters = {k: vals[k] for k in sorted(COUNTERS)}
    counters["tx_active_dur_us"] = (vals["tx_active_dur_us_high"] << 32) | vals["tx_active_dur_us_low"]
    return vals["mac_id"], counters


def histogram(lines, header, field, limit):
    # Firmware TLVs have variable length; accept only a complete contiguous
    # array of the reported size, then require equal shapes across edges.
    require(lines.count(header) == 1, "missing or ambiguous " + field)
    i = lines.index(header) + 1
    require(i < len(lines), "missing " + field)
    m = re.fullmatch(r"\s*" + field + r"\s*=\s*(.+)", lines[i])
    require(m, "malformed " + field)
    values = []
    for item in m[1].split(","):
        v = re.fullmatch(r"\s*(\d+):(\d+)\s*", item)
        require(v and int(v[1]) == len(values) and int(v[2]) < 2**32,
                "invalid " + field + " index/value")
        values.append(int(v[2]))
    require(0 < len(values) <= limit, "invalid " + field + " length")
    return values


def describe_snapshot(lines, expected_devices):
    radios = {}
    try:
        i = 0
        while i < len(lines):
            if not lines[i].strip():
                i += 1
                continue
            b = BEGIN.fullmatch(lines[i])
            require(b and b[1] not in radios, "invalid or duplicate HTT begin")
            j = i + 1
            # Only request markers delimit replies.
            while j < len(lines) and not lines[j].startswith(("HTT_BEGIN ", "HTT_END ")):
                j += 1
            e = END.fullmatch(lines[j]) if j < len(lines) else None
            require(e and e[1] == b[1], "unsealed HTT reply")
            try:
                require(e[3] == "0", "HTT request failed")
                start, end = ms(b[2]), ms(e[2])
                require(0 <= end - start < 2900, "HTT request may have timed out")
                reply = lines[i+1:j]
                mac, counters = common(reply)
                flush = histogram(reply, "HTT_TX_PDEV_STATS_FLUSH_TLV:", "flush_errs", 150)
                underruns = histogram(reply, "HTT_TX_PDEV_STATS_URRN_TLV:", "urrn_stats", 3)
                radios[b[1]] = dict(qualified=True, start_ms=start, end_ms=end,
                                    mac_id=mac, counters=counters, flush=flush, underruns=underruns)
            except ValueError as exc:
                radios[b[1]] = dict(qualified=False, reason=str(exc))
            i = j + 1
        require(set(k.split("/")[0] for k in radios) == set(expected_devices),
                "incomplete HTT device coverage")
        return dict(qualified=all(v["qualified"] for v in radios.values()), radios=radios)
    except ValueError as exc:
        return dict(qualified=False, reason=str(exc), radios=radios)


def compare(before, after):
    a, b = before["radios"], after["radios"]
    if "reason" in before or "reason" in after or a.keys() != b.keys():
        return dict(qualified=False, reason="unmatched or incomplete HTT snapshots")
    radios = {}
    for key in a:
        x, y = a[key], b[key]
        try:
            require(x["qualified"] and y["qualified"], "unqualified HTT reply")
            require(x["mac_id"] == y["mac_id"], "HTT MAC identity changed")
            lo, hi = y["start_ms"] - x["end_ms"], y["end_ms"] - x["start_ms"]
            require(0 < lo <= hi, "overlapping or reversed HTT windows")
            p, q = x["counters"], y["counters"]
            require(p.keys() == q.keys(), "HTT counter schema changed")
            require(p["pdev_resets"] == q["pdev_resets"], "firmware pdev reset")
            require(all(p[k] <= q[k] for k in p), "HTT counter reset or wrap")
            delta = {k: q[k] - p[k] for k in p}
            histograms = {}
            for name in ("flush", "underruns"):
                left, right = x[name], y[name]
                require(len(left) == len(right), name + " histogram shape changed")
                require(all(a <= b for a, b in zip(left, right)), name + " histogram reset or wrap")
                histograms[name] = [b - a for a, b in zip(left, right)]
            radios[key] = dict(qualified=True, mac_id=x["mac_id"],
                               wall_ms_range=[lo, hi], delta=delta,
                               histogram_delta=histograms)
        except ValueError as exc:
            radios[key] = dict(qualified=False, reason=str(exc))
    return dict(qualified=bool(radios) and all(v["qualified"] for v in radios.values()), radios=radios)
