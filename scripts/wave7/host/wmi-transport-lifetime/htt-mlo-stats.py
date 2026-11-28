#!/usr/bin/env python3
"""Read firmware MLO preferred-link scheduling and IPC backpressure stats."""
import re

BEGIN = re.compile(r"HTT_MLO_BEGIN ([^/\s]+/mac\d+) (63|64) (\d+\.\d{2})")
END = re.compile(r"HTT_MLO_END ([^/\s]+/mac\d+) (63|64) (\d+\.\d{2}) rc=(\d+)")
SCHED = {"num_sec_link_sched", "num_pref_link_timeout",
         "num_pref_link_sch_delay_ipc", "num_pref_link_timeout_ipc"}
LINKS, RINGS = 6, 7


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def ms(s):
    sec, hundredths = s.split(".")
    return int(sec) * 1000 + int(hundredths) * 10


def decode(kind, lines):
    lines = [line.strip() for line in lines if line.strip()]
    require(lines, "empty MLO reply")
    if kind == "63":
        require(lines[0] == "HTT_STATS_MLO_SCHED_STATS:", "missing MLO scheduler TLV")
        values = {}
        for line in lines[1:]:
            m = re.fullmatch(r"(\w+)\s*=\s*(\d+)", line)
            require(m and m[1] in SCHED and m[1] not in values and int(m[2]) < 2**32,
                    "invalid MLO scheduler field")
            values[m[1]] = int(m[2])
        require(values.keys() == SCHED, "incomplete MLO scheduler TLV")
        return values
    require(kind == "64" and lines[0] == "HTT_STATS_MLO_IPC_STATS:",
            "missing MLO IPC TLV")
    values = {}
    link = -1
    ring = RINGS
    for line in lines[1:]:
        if m := re.fullmatch(r"src_link:\s*(\d+)", line):
            require(ring == RINGS and int(m[1]) == link + 1 and int(m[1]) < LINKS,
                    "invalid IPC link index")
            link, ring = int(m[1]), 0
            continue
        m = re.fullmatch(r"mlo_ipc_ring_full_cnt\[(\d+)\]:\s*(\d+)", line)
        require(m and link >= 0 and int(m[1]) == ring and ring < RINGS and int(m[2]) < 2**32,
                "invalid IPC ring counter")
        values[f"link{link}/ring{ring}"] = int(m[2])
        ring += 1
    require(len(values) == LINKS * RINGS and link == LINKS-1 and ring == RINGS,
            "incomplete IPC matrix")
    return values


def describe_snapshot(lines, expected_radios):
    replies = {}
    try:
        i = 0
        while i < len(lines):
            if not lines[i].strip():
                i += 1
                continue
            b = BEGIN.fullmatch(lines[i])
            require(b, "invalid MLO begin marker")
            radio, kind = b[1], b[2]
            key = (radio, kind)
            require(key not in replies, "duplicate MLO reply")
            j = i + 1
            while j < len(lines) and not lines[j].startswith(("HTT_MLO_BEGIN ", "HTT_MLO_END ")):
                j += 1
            e = END.fullmatch(lines[j]) if j < len(lines) else None
            require(e and e[1] == radio and e[2] == kind and e[4] == "0",
                    "unsealed or failed MLO reply")
            start, end = ms(b[3]), ms(e[3])
            require(0 <= end - start < 2900, "MLO request may have timed out")
            replies[key] = dict(start_ms=start, end_ms=end, counters=decode(kind, lines[i+1:j]))
            i = j + 1
        require(set(replies) == {(r,k) for r in expected_radios for k in ("63","64")},
                "incomplete MLO radio/type coverage")
        radios = {}
        for (radio, kind), value in replies.items():
            radios.setdefault(radio, {})[kind] = value
        for r in radios.values():
            require(r["63"]["end_ms"] <= r["64"]["start_ms"], "overlapping MLO requests")
        return dict(qualified=True, radios=radios)
    except ValueError as exc:
        return dict(qualified=False, reason=str(exc))


def compare(before, after, tx_before, tx_after, tx):
    try:
        require(before["qualified"] and after["qualified"], "unqualified MLO snapshot")
        require(tx["qualified"], "unqualified pdev TX reset witness")
        require(before["radios"].keys() == after["radios"].keys() == tx["radios"].keys(),
                "MLO radio identity changed")
        radios = {}
        for radio, a in before["radios"].items():
            b = after["radios"][radio]
            require(tx_before["radios"][radio]["end_ms"] <= a["63"]["start_ms"] and
                    b["64"]["end_ms"] <= tx_after["radios"][radio]["start_ms"],
                    "MLO interval not bracketed by pdev reset witness")
            require(a.keys() == b.keys(), "MLO request type changed")
            result = {}
            for kind, x in a.items():
                y = b[kind]
                lo, hi = y["start_ms"] - x["end_ms"], y["end_ms"] - x["start_ms"]
                require(0 < lo <= hi, "overlapping or reversed MLO interval")
                p, q = x["counters"], y["counters"]
                require(p.keys() == q.keys(), "MLO counter schema changed")
                require(all(p[k] <= q[k] for k in p), "MLO counter reset or wrap")
                result[kind] = dict(wall_ms_range=[lo,hi], delta={k:q[k]-p[k] for k in p})
            radios[radio] = result
        return dict(qualified=True, radios=radios)
    except ValueError as exc:
        return dict(qualified=False, reason=str(exc))
