#!/usr/bin/env python3
"""Bounded, read-only router observation under independent path traffic.

No reboots, attestation, network configuration or register writes. Keep
each sample boot-scoped. Report sampled evidence, never infer causality
from a successful pulse log alone.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

BASE = Path("/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8")
ROUTER = "192.168.76.1"
PATHS = {
    "direct": ("192.168.76.2", "enp4s0f4u2u4", "762"),
    "switch": ("192.168.76.250", "enp4s0f4u2u2u4", "763"),
}
COUNTERS = {
    "dot3StatsFCSErrors": "fcs",
    "etherStatsFragments": "fragments",
    "etherStatsDropEvents": "drops",
    "ifInUcastPkts": "ucast",
    "ifInMulticastPkts": "mcast",
    "ifInBroadcastPkts": "bcast",
}
ERRORS = ("fcs", "fragments", "drops")
GOOD = ("ucast", "mcast", "bcast")
BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
EVENT = re.compile(r"^\[\s*(\d+\.\d+)\].*(?:SerDes.*(?:corrupt-only ingress|link lost|recovery pulse|still pending|did not latch)|NOC ERROR DETECTED)")
REMOTE = r"""set -e
echo "boot=$(cat /proc/sys/kernel/random/boot_id)"
echo "uptime=$(cut -d' ' -f1 /proc/uptime)"
echo "revision=$(cat /etc/openwrt_version)"
echo "lan1_carrier=$(cat /sys/class/net/lan1/carrier 2>/dev/null || echo absent)"
echo "direct_carrier=$(cat /sys/class/net/lan/carrier 2>/dev/null || echo absent)"
ethtool -S switch | grep -E 's00_p06_(dot3StatsFCSErrors|etherStatsFragments|etherStatsDropEvents|ifInUcastPkts|ifInMulticastPkts|ifInBroadcastPkts):'
dmesg | grep -E 'SerDes.*(corrupt-only ingress|link lost|recovery pulse|still pending|did not latch)|NOC ERROR DETECTED' || :
echo "end_boot=$(cat /proc/sys/kernel/random/boot_id)"
"""

def run(args, timeout):
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        return {"rc": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired as exc:
        def decode(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        return {"rc": 124, "stdout": decode(exc.stdout), "stderr": decode(exc.stderr)}

def route(name):
    """Record and validate the route, not just the successful case."""
    ip, dev, table = PATHS[name]
    result = run(["ip", "-j", "-4", "route", "get", ROUTER, "from", ip], 3)
    result["valid"] = False
    if result["rc"]:
        return result
    try:
        records = json.loads(result["stdout"])
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise ValueError("expected one route object")
        record = records[0]
        result["route"] = record
        result["valid"] = all(str(record.get(k)) == v for k, v in
                              (("dev", dev), ("table", table), ("from", ip)))
    except (ValueError, TypeError) as exc:
        result["parse_error"] = str(exc)
    return result


def routes():
    return {name:route(name) for name in PATHS}


def probe(name, count, route_state):
    # Do not send traffic if the route no longer selects the dedicated NIC.
    if not route_state["valid"]:
        return {"rc":None,"sent":None,"received":None,"skipped":"route unavailable"}
    return ping(name, count)


def observed_snapshot(revision, route_state):
    if not route_state["direct"]["valid"]:
        return {"rc":None,"skipped":"direct route unavailable","wall_epoch":time.time()}
    return snapshot(revision)


def ping(name, count):
    ip, _, _ = PATHS[name]
    result = run(["ping", "-n", "-D", "-O", "-I", ip, "-c", str(count), "-i", "0.25",
                  "-W", "1", ROUTER], count * .25 + 5)
    m = re.search(r"(\d+) packets transmitted, (\d+)(?: packets)? received", result["stdout"])
    result["sent"], result["received"] = tuple(map(int, m.groups())) if m else (None, None)
    return result

def parse_snapshot(output, expected_revision):
    fields = {}
    for line in output.splitlines():
        if re.match(r"^\w+=", line):
            key, value = line.split("=", 1)
            if key in fields:
                raise ValueError(f"duplicate field {key}")
            fields[key] = value
    boot = fields.get("boot", "")
    if not BOOT.fullmatch(boot) or fields.get("end_boot") != boot:
        raise ValueError("missing/mixed boot ID")
    if fields.get("revision") != expected_revision:
        raise ValueError("unexpected router revision")
    values = {}
    for line in output.splitlines():
        m = re.fullmatch(r"\s*s00_p06_(\w+):\s+(\d+)\s*", line)
        if m and m[1] in COUNTERS:
            key = COUNTERS[m[1]]
            if key in values:
                raise ValueError("duplicate counter")
            values[key] = int(m[2])
    if set(values) != set(COUNTERS.values()):
        raise ValueError("missing CPU-port counters")
    uptime = float(fields["uptime"])
    if not math.isfinite(uptime) or uptime < 0:
        raise ValueError("invalid uptime")
    if any(fields[k] not in ("0","1","absent") for k in ("lan1_carrier","direct_carrier")):
        raise ValueError("invalid carrier")
    return {"boot": boot, "uptime": uptime,
            "revision": fields["revision"], "lan1_carrier": fields["lan1_carrier"],
            "direct_carrier": fields["direct_carrier"], "counters": values,
            "events": [{"uptime":float(m[1]),"line":line} for line in output.splitlines()
                       if (m := EVENT.match(line))]}

def snapshot(revision):
    ip, dev, _ = PATHS["direct"]
    result = run(["ssh", "-nT", "-i", "/home/jan/.ssh/wave7-root-rsa",
                  "-o", f"BindInterface={dev}", "-o", f"BindAddress={ip}",
                  "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                  "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={BASE/'known_hosts'}",
                  "-o", "ConnectTimeout=4", "-o", "ConnectionAttempts=1",
                  f"root@{ROUTER}", REMOTE], 8)
    result["wall_epoch"] = time.time()
    if not result["rc"]:
        try:
            result["state"] = parse_snapshot(result["stdout"], revision)
        except (ValueError, KeyError) as exc:
            result["parse_error"] = str(exc)
    return result

def classify(previous, current, probes, routes_before=None, routes_after=None):
    # Missing or changed routing is an explicit result, not a reason to
    # terminate a capture. Old raw evidence predates route journaling.
    for state in (routes_before, routes_after):
        if state is not None:
            if not state["direct"]["valid"]:
                return {"kind":"DIRECT_ROUTE_UNAVAILABLE"}
            if not state["switch"]["valid"]:
                return {"kind":"SWITCH_ROUTE_UNAVAILABLE"}
    if previous is None or current is None:
        return {"kind":"UNOBSERVED"}
    if previous["boot"] != current["boot"]:
        return {"kind":"NEW_BOOT"}
    if current["uptime"] <= previous["uptime"]:
        return {"kind":"NONMONOTONIC_UPTIME"}
    delta = {k: current["counters"][k]-previous["counters"][k] for k in COUNTERS.values()}
    if min(delta.values()) < 0:
        return {"kind":"COUNTER_RESET_OR_WRAP", "delta":delta}
    d,s = (probes[k] for k in ("direct","switch"))
    valid = all(isinstance(p["sent"],int) and p["sent"] > 0 and
                isinstance(p["received"],int) and 0 <= p["received"] <= p["sent"] for p in (d,s))
    if not valid:
        kind = "PROBE_UNOBSERVED"
    elif d["received"] != d["sent"]:
        kind = "DIRECT_CONTROL_LOSS"
    elif current.get("direct_carrier", "1") != "1":
        kind = "DIRECT_CARRIER_UNAVAILABLE"
    elif current["lan1_carrier"] == "0":
        kind = "SWITCH_COPPER_DOWN"
    elif current["lan1_carrier"] != "1":
        kind = "SWITCH_CARRIER_UNAVAILABLE"
    elif not s["received"] and (delta["fcs"]+delta["fragments"]) and not sum(delta[k] for k in GOOD):
        kind = "CORRUPT_ONLY_WITH_DIRECTIONAL_LOSS"
    elif s["received"] != s["sent"]:
        kind = "SWITCH_PATH_LOSS"
    elif any(delta[k] for k in ERRORS):
        kind = "ERRORS_WITH_VALID_TRAFFIC"
    elif s["received"] == s["sent"]:
        # Successful echo replies alone do not prove CPU-trunk use.
        # At least one valid ingress frame must be visible in the MIB.
        kind = "CLEAN_FORWARDING" if sum(delta[k] for k in GOOD) else "MIB_FORWARDING_UNCONFIRMED"
    else:
        kind = "REVIEW"
    return {"kind":kind,"delta":delta}

def report(rows):
    counts, boots, events = {}, {}, {}
    previous = None
    intervals = []
    for row in rows:
        current = row["snapshot"].get("state")
        if current:
            boot = current["boot"]
            boots[boot] = {"first_uptime":boots.get(boot,{}).get("first_uptime",current["uptime"]),
                           "last_uptime":current["uptime"], "final_counters":current["counters"]}
            for event in current["events"]:
                events[(boot,event["line"])] = {"boot":boot,**event}
        if "probes" in row:
            result = classify(previous,current,row["probes"],row.get("routes_before"),row.get("routes_after"))
            kind = result["kind"]
            counts[kind] = counts.get(kind,0)+1
            intervals.append({"kind":kind,"boot":current and current["boot"],
                              "start_uptime":previous and previous["uptime"],
                              "end_uptime":current and current["uptime"],
                              "direct_sent":row["probes"]["direct"]["sent"],
                              "direct_received":row["probes"]["direct"]["received"],
                              "switch_sent":row["probes"]["switch"]["sent"],
                              "switch_received":row["probes"]["switch"]["received"],
                              **({"delta":result["delta"]} if "delta" in result else {})})
        # Never bridge a missed sample or compare counters across a reboot.
        routes_after = row.get("routes_after")
        previous = current if routes_after is None or all(r["valid"] for r in routes_after.values()) else None
    return {"interval_counts":counts,"boots":boots,"driver_events":list(events.values()),
            "intervals":intervals}

def capture(out, revision, duration, count):
    if os.getuid() == 0:
        raise ValueError("run as jan, not root")
    if not 15 <= duration <= 600 or not 4 <= count <= 20:
        raise ValueError("duration 15–600 seconds, count 4–20")
    if out.parent.resolve() != (BASE/"native-recovery-dhcp-guard8"/"observations").resolve():
        raise ValueError("output must be under native-recovery observations")
    initial_routes = routes()
    out.mkdir(mode=0o700)
    (out/"metadata.json").write_text(json.dumps({"revision":revision,"duration":duration,
                                              "count":count,"schema":2,"routes":initial_routes},indent=2)+"\n")
    rows = []
    with (out/"samples.jsonl").open("x") as stream, ThreadPoolExecutor(2) as pool:
        def append(row):
            rows.append(row)
            stream.write(json.dumps(row)+"\n")
            stream.flush()
        append({"snapshot":observed_snapshot(revision,initial_routes),"routes_after":initial_routes})
        deadline = time.monotonic()+duration
        while time.monotonic()<deadline:
            before = routes()
            started = time.time()
            futures = {k:pool.submit(probe,k,count,before[k]) for k in PATHS}
            probes = {k:f.result() for k,f in futures.items()}
            end_probe = time.time()
            after = routes()
            append({"start_wall_epoch":started,"end_probe_epoch":end_probe,
                    "routes_before":before,"routes_after":after,
                    "probes":probes,"snapshot":observed_snapshot(revision,after)})
            # Both paths down can otherwise reduce the interval to a tight loop.
            time.sleep(max(0, count * .25 - (time.time()-started)))
    summary = report(rows)
    (out/"report.json").write_text(json.dumps(summary,indent=2)+"\n")
    names = ("metadata.json","samples.jsonl","report.json")
    (out/"SHA256SUMS").write_text("".join(f"{hashlib.sha256((out/n).read_bytes()).hexdigest()}  {n}\n" for n in names))
    print(json.dumps({k:v for k,v in summary.items() if k!="intervals"},indent=2))

def selftest():
    b = "12345678-1234-1234-1234-123456789abc"
    a = {"boot":b,"uptime":1,"lan1_carrier":"1","counters":dict.fromkeys(COUNTERS.values(),0),"events":[]}
    p = {"direct":{"sent":8,"received":8},"switch":{"sent":8,"received":0}}
    c = {**a,"uptime":3,"counters":{**a["counters"],"fcs":11,"fragments":4,"drops":15}}
    assert classify(a,c,p)["kind"] == "CORRUPT_ONLY_WITH_DIRECTIONAL_LOSS"
    d = {**c,"uptime":5,"counters":{**c["counters"],"ucast":8}}
    q = {**p,"switch":{"sent":8,"received":8}}
    assert classify(c,d,q)["kind"] == "CLEAN_FORWARDING"
    assert classify(c,{**d,"boot":"other"},q)["kind"] == "NEW_BOOT"
    assert classify(d,{**a,"uptime":7},q)["kind"] == "COUNTER_RESET_OR_WRAP"
    assert classify(a,c,{**p,"direct":{"sent":8,"received":0}})["kind"] == "DIRECT_CONTROL_LOSS"
    assert classify(a,{**c,"lan1_carrier":"0"},p)["kind"] == "SWITCH_COPPER_DOWN"
    assert classify(None,c,p)["kind"] == "UNOBSERVED"
    assert classify(a,c,{**p,"switch":{"sent":None,"received":None}})["kind"] == "PROBE_UNOBSERVED"
    assert classify(c,{**c,"uptime":5},q)["kind"] == "MIB_FORWARDING_UNCONFIRMED"
    assert classify(a,{**c,"lan1_carrier":"absent"},p)["kind"] == "SWITCH_CARRIER_UNAVAILABLE"
    assert classify(a,{**c,"direct_carrier":"0"},p)["kind"] == "DIRECT_CARRIER_UNAVAILABLE"
    good_routes = {name:{"valid":True} for name in PATHS}
    for name in PATHS:
        bad_routes = {**good_routes,name:{"valid":False}}
        for before, after in ((bad_routes,good_routes),(good_routes,bad_routes)):
            assert classify(a,c,p,before,after)["kind"] == name.upper()+"_ROUTE_UNAVAILABLE"
        assert probe(name,8,bad_routes[name])["skipped"]
    assert observed_snapshot("wrong",{"direct":{"valid":False}})["skipped"]
    rows=[{"snapshot":{"state":a}},{"snapshot":{"state":c},"probes":p},
          {"snapshot":{},"probes":q},{"snapshot":{"state":d},"probes":q}]
    assert report(rows)["interval_counts"] == {"CORRUPT_ONLY_WITH_DIRECTIONAL_LOSS":1,"UNOBSERVED":2}
    print("TRUNK_RECOVERY_PROBE_SELFTEST_PASS")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command",required=True)
    subs.add_parser("selftest")
    p = subs.add_parser("capture")
    p.add_argument("out",type=Path)
    p.add_argument("revision")
    p.add_argument("--duration",type=int,default=60)
    p.add_argument("--count",type=int,default=8)
    p = subs.add_parser("report")
    p.add_argument("samples",type=Path)
    args=parser.parse_args()
    if args.command=="selftest":
        selftest()
    elif args.command=="report":
        print(json.dumps(report([json.loads(line) for line in args.samples.read_text().splitlines()]),indent=2))
    else:
        capture(args.out,args.revision,args.duration,args.count)
