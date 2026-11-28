#!/usr/bin/env python3
"""Exercise the actual iw text schema and per-channel qualification."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("survey", Path(__file__).with_name("channel-survey.py"))
survey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(survey)

GEOMETRY = [
    "Interface ap-mld0",
    "\t - link ID  0 link addr 70:5a:6f:5a:bb:16",
    "\t   channel 1 (2412 MHz), width: 20 MHz, center1: 2412 MHz",
    "\t - link ID  1 link addr 4e:5a:6f:5a:bb:16",
    "\t   channel 36 (5180 MHz), width: 80 MHz, center1: 5210 MHz",
]


def reply(freq, active, busy, tx, rx, noise=-96):
    return ["Survey data from ap-mld0", f"\tfrequency:\t\t\t{freq} MHz [in use]",
            f"\tnoise:\t\t\t\t{noise} dBm",
            f"\tchannel active time:\t\t{active} ms",
            f"\tchannel busy time:\t\t{busy} ms",
            f"\tchannel receive time:\t\t{rx} ms",
            f"\tchannel transmit time:\t\t{tx} ms"]


def snapshot(start, end, *rows, rc=0, after=GEOMETRY):
    return ["GEOMETRY_BEFORE", *GEOMETRY, "GEOMETRY_BEFORE_END rc=0",
            f"SURVEY_BEGIN {start}", *rows, f"SURVEY_END {end} rc={rc}",
            "GEOMETRY_AFTER", *after, "GEOMETRY_AFTER_END rc=0"]


a = snapshot("100.01", "100.05", *reply(2412, 10000, 3000, 1000, 500),
             "Survey data from ap-mld0", "\tfrequency:\t2437 MHz",
             *reply(5180, 20000, 5000, 2000, 1000))
b = snapshot("117.01", "117.09", *reply(2412, 26000, 7000, 3000, 1500),
             *reply(5180, 37000, 19000, 12000, 2000))
pre, post = survey.describe_snapshot(a), survey.describe_snapshot(b)
r = survey.compare(pre, post)
assert r["qualified"] and r["wall_ms_range"] == [16960, 17080]
assert r["channels"][2412]["delta_ms"] == {"active": 16000, "busy": 4000, "tx": 2000, "rx_reported": 1000}
assert r["channels"][2412]["fraction_active_pct"]["busy"] == 25
assert r["channels"][5180]["fraction_active_pct"]["busy"] == 1400000 / 17000

bad_rows = (
    (snapshot("117.01", "120.01", *reply(2412, 26000, 7000, 3000, 1500)), "timed out"),
    (snapshot("117.01", "117.09", *reply(2412, 26000, 7000, 3000, 1500), rc=1), "failed"),
    (snapshot("117.01", "117.09", *reply(2412, 26000, 7000, 3000, 1500),
              after=[v.replace("5180", "5200") for v in GEOMETRY]), "geometry changed"),
    (snapshot("117.01", "117.09", *reply(2412, 26000, 7000, 3000, 1500),
              *reply(5200, 37000, 19000, 12000, 2000)), "disagrees"),
    (snapshot("117.01", "117.09", *reply(2412, 26000, 7000, 3000, 1500),
              *reply(2412, 26000, 7000, 3000, 1500)), "duplicate"),
    (b[:-1], "unsealed"),
)
for raw, reason in bad_rows:
    bad = survey.describe_snapshot(raw)
    assert not bad["qualified"] and reason in bad["reason"], bad
    assert not survey.compare(pre, bad)["qualified"]

for raw, reason in (
    (snapshot("117.01", "117.09", *reply(2412, 26000, 7000, 3000, 1500)), "no in-use"),
    (snapshot("117.01", "117.09", *reply(2412, 26000, 7000, 3000, 1500),
              *reply(5180, 20000, 5000, 2000, 1000)), "did not advance"),
    (snapshot("117.01", "117.09", *reply(2412, 26000, 7000, 3000, 1500),
              *reply(5180, 19000, 5000, 2000, 1000)), "reset"),
    (snapshot("117.01", "117.09", *reply(2412, 26000, 7000, 3000, 1500),
              *reply(5180, 39000, 19000, 12000, 2000)), "exceeds observation"),
    (snapshot("117.01", "117.09", *reply(2412, 26000, 7000, 3000, 1500),
              *reply(5180, 37000, 29000, 12000, 2000)), "exceeds active"),
    (snapshot("117.01", "117.09", *reply(2412, 26000, 7000, 3000, 1500),
              *reply(5180, 37000, 19000, 12000, 2000)[:-1]), "missing active"),
):
    result = survey.compare(pre, survey.describe_snapshot(raw))
    assert not result["qualified"] and result["channels"][2412]["qualified"], result
    assert reason in result["channels"][5180]["reason"], result

assert not survey.compare(post, pre)["qualified"]
print("CHANNEL_SURVEY_SELFTEST_PASS")
