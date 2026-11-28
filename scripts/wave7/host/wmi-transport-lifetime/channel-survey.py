#!/usr/bin/env python3
"""Qualify edge-only nl80211 channel survey telemetry independently of TCP."""

import re

INTERFACE = "ap-mld0"
FIELDS = {
    "channel active time": "active",
    "channel busy time": "busy",
    "extension channel busy time": "ext_busy",
    "channel receive time": "rx_reported",
    "channel BSS receive time": "rx_bss",
    "channel transmit time": "tx",
}
REQUIRED = {"active", "busy", "tx"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def geometry(lines):
    channels = {}
    require(f"Interface {INTERFACE}" in lines, "missing AP interface identity")
    for line in lines:
        if m := re.fullmatch(r"\s*channel \d+ \((\d+) MHz\), (.+)", line):
            freq = int(m[1])
            require(freq not in channels, "duplicate channel geometry")
            channels[freq] = m[2]
    require(channels, "missing operating channel geometry")
    return channels


def records(lines):
    """Read iw's survey dump, including sparse inactive-channel replies."""
    channels = {}
    current = None
    for line in lines:
        if line == f"Survey data from {INTERFACE}":
            current = {}
        elif not line.strip():
            continue
        else:
            require(current is not None, "unexpected survey output")
            if m := re.fullmatch(r"\s*frequency:\s*(\d+) MHz( \[in use\])?", line):
                freq = int(m[1])
                require("freq" not in current and freq not in channels,
                        "duplicate survey frequency")
                current.update(freq=freq, in_use=bool(m[2]), counters={})
                channels[freq] = current
            elif m := re.fullmatch(r"\s*noise:\s*(-?\d+) dBm", line):
                require("freq" in current and "noise" not in current and
                        -128 <= int(m[1]) <= 127, "invalid survey noise")
                current["noise"] = int(m[1])
            elif m := re.fullmatch(r"\s*([^:]+):\s*(\d+) ms", line):
                require("freq" in current and m[1] in FIELDS,
                        "unrecognized survey counter")
                key, value = FIELDS[m[1]], int(m[2])
                require(key not in current["counters"] and value < 2**64,
                        "invalid or duplicate survey counter")
                current["counters"][key] = value
            else:
                raise ValueError(f"unexpected survey output: {line[:160]}")
    return channels


def take(lines, marker, end_pattern):
    require(lines and lines[0] == marker, f"missing {marker}")
    for i, line in enumerate(lines[1:], 1):
        if m := re.fullmatch(end_pattern, line):
            return lines[1:i], m, lines[i+1:]
    raise ValueError(f"unsealed {marker}")


def uptime_ms(text):
    sec, hundredths = text.split(".")
    return 1000 * int(sec) + 10 * int(hundredths)


def parse_snapshot(lines):
    pre, pre_end, rest = take(lines, "GEOMETRY_BEFORE", r"GEOMETRY_BEFORE_END rc=(\d+)")
    require(rest, "missing survey request")
    begin = re.fullmatch(r"SURVEY_BEGIN (\d+\.\d{2})", rest[0])
    require(begin, "missing survey begin uptime")
    raw, end, rest = take(rest, rest[0], r"SURVEY_END (\d+\.\d{2}) rc=(\d+)")
    post, post_end, rest = take(rest, "GEOMETRY_AFTER", r"GEOMETRY_AFTER_END rc=(\d+)")
    require(not rest, "trailing survey data")
    require(pre_end[1] == end[2] == post_end[1] == "0",
            "iw info or survey request failed")
    start_ms, end_ms = uptime_ms(begin[1]), uptime_ms(end[1])
    # ath12k waits 3*HZ for each BSS-channel response. If the total
    # request approaches that limit we cannot exclude stale cached data.
    require(0 <= end_ms - start_ms < 2900, "survey request may have timed out")
    operating = geometry(pre)
    require(operating == geometry(post), "channel geometry changed during survey")
    data = records(raw)
    unexpected = [f for f, v in data.items() if v["in_use"] and f not in operating]
    require(not unexpected, "in-use survey frequency disagrees with AP geometry")
    channels = {}
    for freq in operating:
        entry = data.get(freq)
        if entry is None or not entry["in_use"]:
            channels[freq] = dict(qualified=False, reason="no in-use survey reply")
        elif not REQUIRED <= entry["counters"].keys():
            channels[freq] = dict(qualified=False, reason="missing active/busy/TX counter",
                                  counters=entry["counters"])
        else:
            channels[freq] = dict(qualified=True, counters=entry["counters"],
                                  noise_dbm=entry.get("noise"))
    return dict(qualified=True, start_ms=start_ms, end_ms=end_ms,
                geometry=operating, channels=channels)


def describe_snapshot(lines):
    try:
        return parse_snapshot(lines)
    except ValueError as e:
        # Keep TCP and host datapath measurements usable even when the
        # optional firmware survey is unsupported, malformed, or stale.
        return dict(qualified=False, reason=str(e))


def interval(before, after, wall_min, wall_max):
    require(before["qualified"], "before: " + before.get("reason", "unqualified"))
    require(after["qualified"], "after: " + after.get("reason", "unqualified"))
    a, b = before["counters"], after["counters"]
    require(a.keys() == b.keys(), "survey counter schema changed")
    require(all(a[k] <= b[k] for k in a), "survey counter reset or wrap")
    delta = {k: b[k] - a[k] for k in a}
    active = delta["active"]
    require(active > 0, "active-time counter did not advance")
    # /proc/uptime is quantized to 10 ms and survey counters to 1 ms.
    # Do not silently normalize a wrong firmware clock or stale counter.
    require(active <= wall_max + 22, "active time exceeds observation interval")
    require(all(delta[k] <= active + 2 for k in delta if k != "active"),
            "survey time exceeds active time")
    # Ath12k currently reports rx_bss_cycle_count through TIME_RX.
    # Preserve the reported field, not a purported total receive time.
    # Never infer external interference by subtracting TX or RX from busy:
    # these firmware counters have not been proven mutually exclusive.
    return dict(qualified=True, delta_ms=delta,
                fraction_active_pct={k: 100 * v / active for k, v in delta.items()
                                     if k != "active"},
                active_vs_wall_pct_range=[100 * active / wall_max, 100 * active / wall_min],
                noise_dbm={"before": before.get("noise_dbm"), "after": after.get("noise_dbm")})


def compare(before, after):
    try:
        require(before["qualified"], "before: " + before.get("reason", "unqualified"))
        require(after["qualified"], "after: " + after.get("reason", "unqualified"))
        require(before["geometry"] == after["geometry"], "operating channel geometry changed")
        wall_min = after["start_ms"] - before["end_ms"]
        wall_max = after["end_ms"] - before["start_ms"]
        require(0 < wall_min <= wall_max, "overlapping or reversed survey requests")
    except ValueError as e:
        return dict(qualified=False, reason=str(e))
    channels = {}
    for freq in before["geometry"]:
        try:
            channels[freq] = interval(before["channels"][freq], after["channels"][freq],
                                      wall_min, wall_max)
        except ValueError as e:
            channels[freq] = dict(qualified=False, reason=str(e))
    return dict(qualified=all(v["qualified"] for v in channels.values()),
                wall_ms_range=[wall_min, wall_max],
                geometry=before["geometry"], channels=channels)
