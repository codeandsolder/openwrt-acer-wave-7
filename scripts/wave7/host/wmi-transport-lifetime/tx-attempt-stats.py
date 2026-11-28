#!/usr/bin/env python3
"""Independent WBM TQM completion-record attempt distribution.

Counts are not unique MPDUs. A WBM release list can contain multiple
records for a transmitted frame. Preserve the observed list position.
"""
import re

REASONS = 16
COUNTS = 128
CLASSES = ("direct", "list_middle", "list_first", "list_last", "list_single")
HEADER = re.compile(r"version=1 generation=(\d+) reasons=16 classes=5 counts=128")


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def parse_radio(lines):
    require(len(lines) == 1 + REASONS * len(CLASSES), "incomplete TX attempt matrix")
    header = HEADER.fullmatch(lines[0])
    require(header and 0 < int(header[1]) < 2**64, "invalid TX attempt epoch/schema")
    rows = {}
    for line in lines[1:]:
        fields = line.split()
        require(len(fields) == 2 + COUNTS and all(re.fullmatch(r"\d+", v) for v in fields),
                "malformed TX attempt row")
        reason, position, *counts = map(int, fields)
        key = (reason, position)
        require(0 <= reason < REASONS and 0 <= position < len(CLASSES)
                and key not in rows and all(0 <= n < 2**64 for n in counts),
                "invalid or duplicate TX attempt row")
        rows[key] = tuple(counts)
    require(len(rows) == REASONS * len(CLASSES), "missing TX attempt rows")
    return dict(generation=int(header[1]), rows=rows)


def parse_sections(sections, devices):
    prefix = "TX_ATTEMPT "
    radios = {k.removeprefix(prefix): parse_radio(v)
              for k, v in sections.items() if k.startswith(prefix)}
    require(radios.keys() == set(devices), "incomplete TX attempt device coverage")
    return radios


def compare(before, after):
    require(before.keys() == after.keys(), "TX attempt radio set changed")
    result = {}
    for radio, pre in before.items():
        post = after[radio]
        require(pre["generation"] == post["generation"], "TX attempt firmware epoch changed")
        a, b = pre["rows"], post["rows"]
        require(a.keys() == b.keys(), "TX attempt schema changed")
        totals = dict.fromkeys(CLASSES, 0)
        reasons = {}
        for (reason, position), x in a.items():
            y = b[(reason, position)]
            require(len(x) == len(y) == COUNTS and all(l <= r for l, r in zip(x, y)),
                    "TX attempt counter regressed")
            histogram = {str(n): r-l for n, (l,r) in enumerate(zip(x,y)) if r != l}
            if not histogram:
                continue
            count = sum(histogram.values())
            name = CLASSES[position]
            totals[name] += count
            reasons.setdefault(str(reason), {})[name] = dict(records=count,
                                                              transmit_count=histogram)
        result[radio] = dict(generation=pre["generation"], records=sum(totals.values()),
                             records_by_position=totals, reasons=reasons)
    return result
