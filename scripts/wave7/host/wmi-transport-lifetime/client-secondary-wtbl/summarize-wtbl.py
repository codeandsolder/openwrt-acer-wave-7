"""Decode MT7925 LWTBL peer metadata captured by client-wtbl.patch.

Register layout: MediaTek gen4m 6bceb1b8e3444dd6caf80ad7470c9e57bbdcd1ab,
include/chips/coda/mt7925/wf_ds_lwtbl.h. No key data is captured.
"""
import argparse
import json
import re
from pathlib import Path

STAGES = {
    1: "key", 2: "pre_refresh", 3: "post_refresh", 4: "post_add",
    5: "post_assoc", 6: "post_mld", 7: "post_keys",
}
EVENT = re.compile(
    r"(?P<time>\d+\.\d+): mt7925_lab_wtbl_peer: "
    r"stage=(?P<stage>\d+) wcid=(?P<wcid>\d+) link=(?P<link>\d+) "
    r"bss=(?P<bss>\d+) host_band=(?P<host_band>\d+) "
    r"dw0=(?P<dw0>0x[0-9a-f]+) dw1=(?P<dw1>0x[0-9a-f]+) "
    r"cipher=(?P<cipher>\d+) dw28=(?P<dw28>0x[0-9a-f]+) mld=(?P<mld>\d+)"
)

def decode(match):
    d = match.groupdict()
    time = float(d.pop("time"))
    values = {name: int(value, 0) for name, value in d.items()}
    dw0, dw1, dw28 = (values[k] for k in ("dw0", "dw1", "dw28"))
    mac = (dw1.to_bytes(4, "little") +
           (dw0 & 0xffff).to_bytes(2, "little")).hex(":")
    return dict(
        time=time,
        stage=STAGES[values["stage"]],
        wcid=values["wcid"], link=values["link"], bss=values["bss"],
        host_band=values["host_band"], mac=mac,
        muar=(dw0 >> 16) & 63, rca1=(dw0 >> 22) & 1,
        kid=(dw0 >> 23) & 3, rcid=(dw0 >> 25) & 1,
        hardware_band=(dw0 >> 26) & 3, rv=(dw0 >> 28) & 1,
        rca2=(dw0 >> 29) & 1, cipher=values["cipher"],
        related_idx0=dw28 & 4095, related_band0=(dw28 >> 12) & 3,
        primary_mld_band=(dw28 >> 14) & 3,
        related_idx1=(dw28 >> 16) & 4095, related_band1=(dw28 >> 28) & 3,
        secondary_mld_band=(dw28 >> 30) & 3, mld=values["mld"],
    )

def parse(text):
    rows = [decode(match) for match in EVENT.finditer(text)]
    event_lines = sum(": mt7925_lab_wtbl_peer:" in line for line in text.splitlines())
    if len(rows) != event_lines or not rows:
        raise ValueError(f"decoded {len(rows)} of {event_lines} WTBL events")
    return rows

def self_test():
    dw0 = 0xbb16 | (7 << 16) | (1 << 26) | (1 << 28)
    dw28 = 3 | (1 << 12) | (1 << 14) | (2 << 16) | (0 << 30)
    row, = parse(
        f"  42.000: mt7925_lab_wtbl_peer: stage=7 wcid=2 link=0 bss=0 "
        f"host_band=1 dw0=0x{dw0:08x} dw1=0x5a6f5a70 cipher=4 "
        f"dw28=0x{dw28:08x} mld=5"
    )
    assert row["mac"] == "70:5a:6f:5a:16:bb"
    assert row["hardware_band"] == row["host_band"] == row["rv"] == 1
    assert row["muar"] == 7 and row["related_idx0"] == 3
    assert row["related_band0"] == 1 and row["related_idx1"] == 2
    assert row["primary_mld_band"] == 1 and row["secondary_mld_band"] == 0
    assert row["cipher"] == 4 and row["mld"] == 5
    for bad in ("", "1.0: mt7925_lab_wtbl_peer: malformed"):
        try:
            parse(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted invalid capture")
    print("WTBL_SUMMARY_FIXTURE_PASS")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, nargs="?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.trace:
        print(json.dumps(parse(args.trace.read_text()), indent=2))
    else:
        parser.error("provide a trace or --self-test")
