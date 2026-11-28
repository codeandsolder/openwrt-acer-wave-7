#!/usr/bin/env python3
"""Exercise HTT qualification independently of a hardware reply."""
import runpy
from pathlib import Path

h = runpy.run_path(str(Path(__file__).with_name("htt-tx-stats.py")))
devices = {"radio-a", "radio-b"}


def reply(device, start, end, value, **overrides):
    fields = dict.fromkeys(h["COUNTERS"], value)
    fields.update(mac_id=0, pdev_resets=0, tx_active_dur_us_low=value,
                  tx_active_dur_us_high=0)
    fields.update(overrides)
    return [f"HTT_BEGIN {device}/mac0 {start} selector=1", "HTT_TX_PDEV_STATS_CMN_TLV:",
            *(f"{k} = {v}" for k,v in sorted(fields.items())), "",
            "HTT_TX_PDEV_STATS_URRN_TLV:", "urrn_stats = 0:0,1:0",
            f"HTT_END {device}/mac0 {end} rc=0"]


def parse(a, b):
    return h["describe_snapshot"](a+b, devices)


a = reply("radio-a", "100.00", "100.10", 50)
b = reply("radio-b", "100.11", "100.25", 70)
c = reply("radio-a", "117.00", "117.10", 100)
d = reply("radio-b", "117.11", "117.25", 150)
pre, post = parse(a,b), parse(c,d)
assert pre["qualified"] and post["qualified"]
r = h["compare"](pre, post)
assert r["qualified"] and r["radios"]["radio-a/mac0"]["delta"]["mpdu_tried"] == 50
assert r["radios"]["radio-b/mac0"]["wall_ms_range"] == [16860,17140]
assert not h["describe_snapshot"](a,devices)["qualified"]
assert not parse(a,b[:-1])["qualified"]
assert not parse(a,b+[b[0]])["qualified"]
assert not parse(a,[*b[:2],"mac_id = 1",*b[2:]])["qualified"]
assert not parse(a,[x for x in b if not x.startswith("mpdu_tried =")])["qualified"]
assert not parse(a,[*b[:-1],b[-1].replace("rc=0","rc=1")])["qualified"]
assert not parse(a,reply("radio-b","101.00","104.00",70))["qualified"]
assert not h["compare"](post,pre)["qualified"]
assert not h["compare"](pre,parse(c,reply("radio-b","117.11","117.25",150,pdev_resets=1)))["qualified"]
assert not h["compare"](pre,parse(c,reply("radio-b","117.11","117.25",150,mpdu_tried=69)))["qualified"]
assert not h["compare"](pre,parse(c,reply("radio-b","117.11","117.25",150,mac_id=1)))["qualified"]
r = h["compare"](parse(reply("radio-a","100.00","100.10",50,tx_active_dur_us_low=4294967290),b),
                 parse(reply("radio-a","117.00","117.10",100,tx_active_dur_us_low=4,tx_active_dur_us_high=1),d))
assert r["qualified"] and r["radios"]["radio-a/mac0"]["delta"]["tx_active_dur_us"] == 10
print("HTT_TX_STATS_PASS")
