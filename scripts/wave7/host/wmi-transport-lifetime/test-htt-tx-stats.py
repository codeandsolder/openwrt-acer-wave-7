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
            "HTT_TX_PDEV_STATS_URRN_TLV:", "urrn_stats = 0:0,1:0,2:0", "",
            "HTT_TX_PDEV_STATS_FLUSH_TLV:", f"flush_errs = 0:0,1:{value},2:0",
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
assert h["compare"](pre,post)["radios"]["radio-a/mac0"]["histogram_delta"]["flush"] == [0,50,0]
assert not parse(a,[x for x in b if not x.startswith("flush_errs")])["qualified"]
assert not parse(a,[x.replace("1:70,2:0", "1:70,3:0") for x in b])["qualified"]
assert not parse(a,[x.replace("1:70,2:0", "1:4294967296,2:0") for x in b])["qualified"]
assert not h["compare"](pre,parse(c,[x.replace("1:150,2:0", "1:69,2:0") for x in d]))["qualified"]
assert not h["compare"](pre,parse(c,[x.replace("1:150,2:0", "1:150") for x in d]))["qualified"]
print("HTT_TX_STATS_PASS")

# Direct tag 82 parser: exact bin width, arbitrary valid TLV length, no retries.
header = h['MPDU_HIST_HEADER']
for n in (1, 10, 255, 256, 1022):
    lines = [header, 'hist_bin_size = 30', 'tried_mpdu_cnt_hist = ' +
             ', '.join(f'{i}:{i+1}' for i in range(n))]
    assert h['mpdu_histogram'](lines) == {'bin_size':30,'bins':list(range(1,n+1))}
    for bad in (lines[:-1], lines+lines, [lines[0], 'hist_bin_size = 0', lines[2]],
                [lines[0], 'invalid_length = 4']):
        try:
            h['mpdu_histogram'](bad)
        except ValueError:
            pass
        else:
            raise AssertionError('malformed aggregation histogram accepted')
assert h['mpdu_histogram']([]) is None
print('HTT_MPDU_HIST_PASS')

def with_mpdu(raw, width, values):
    out=[]
    for line in raw:
        if line.startswith("HTT_END "):
            out += [header, f'hist_bin_size = {width}', 'tried_mpdu_cnt_hist = ' +
                    ', '.join(f'{i}:{v}' for i,v in enumerate(values)), '']
        out.append(line)
    return out

raw_a=reply("radio-a","10.00","10.01",10)+reply("radio-b","10.02","10.03",10)
raw_b=reply("radio-a","20.00","20.01",20)+reply("radio-b","20.02","20.03",20)
decode=lambda raw:h['describe_snapshot'](raw,devices)
a=decode(with_mpdu(raw_a,30,[10,20,30]))
b=decode(with_mpdu(raw_b,30,[12,25,33]))
r=h['compare'](a,b)
assert r['qualified']
for v in r['radios'].values():
    assert v['mpdu_per_ppdu']==dict(bin_size=30,bins=[2,5,3],fraction_pct=[20,50,30])
for bad in (raw_b, with_mpdu(raw_b,31,[12,25,33]), with_mpdu(raw_b,30,[12,25]),
            with_mpdu(raw_b,30,[9,25,33])):
    assert not h['compare'](a,decode(bad))['qualified']
print('HTT_MPDU_DELTA_PASS')
