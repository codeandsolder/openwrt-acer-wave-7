#!/usr/bin/env -S uv run --no-project python
"""Witness real TCP load on each physical path of a sealed ordering boot."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import re
import runpy
import subprocess
import time

HERE = Path(__file__).resolve().parent
probe = runpy.run_path(str(HERE / "probe-mib-freshness.py"))
cohort = runpy.run_path(str(HERE / "report-ordering-cohort.py"))
require, remote = probe["require"], probe["remote"]
PATHS = probe["PATHS"]
RUNTIME = Path("/home/jan/firmware/wave7/trials/20261115-deferred-regression/iperf-runtime")
FILES = ("iperf3", "libiperf.so.0", "libatomic.so.1")
PORT = 52227
DURATION = 12
MAC_BYTES = ("rx_bytes_g", "tx_bytes_g")
ERRORS = probe["XGMAC_ERRORS"]
COMMAND = probe["REMOTE"].replace(
    'echo "end_boot=$(cat /proc/sys/kernel/random/boot_id)"',
    'echo "=== DIRECT ==="\nethtool -S lan\n'
    'echo "end_boot=$(cat /proc/sys/kernel/random/boot_id)"')


def mac_bytes(raw):
    fields = {}
    for line in raw.splitlines():
        match = re.fullmatch(r"\s*(rx_bytes_g|tx_bytes_g):\s+(\d+)", line)
        if match:
            require(match[1] not in fields, "duplicate XGMAC byte counter")
            fields[match[1]] = int(match[2])
    require(set(fields) == set(MAC_BYTES), "missing XGMAC byte counter")
    return fields


def sample(out, name, variant, boot):
    probe["routes"]()
    raw = remote(COMMAND)
    (out / f"{name}.txt").write_text(raw)
    state = probe["parse_snapshot"](raw, variant)
    require(state["fields"]["boot"] == boot and state["fields"]["noc"] == "0",
            "unexpected boot or NoC")
    cpu = raw.split("=== CPU ===\n", 1)[1].split("=== COPPER ===\n", 1)[0]
    direct = raw.split("=== DIRECT ===\n", 1)[1].split("end_boot=", 1)[0]
    state["macs"] = {
        "switch": {**probe["parse_xgmac"](cpu), **mac_bytes(cpu)},
        "direct": {**probe["parse_xgmac"](direct), **mac_bytes(direct)},
    }
    state["host"] = {
        path: {k: int((Path("/sys/class/net") / dev / "statistics" / k).read_text())
               for k in ("rx_bytes", "tx_bytes")}
        for path, (_, dev, *_) in PATHS.items()}
    (out / f"{name}.json").write_text(json.dumps(state, indent=2)+"\n")
    return state


def received_bytes(client, mode, server=None):
    require(not client.get("error"), "iperf client error")
    end = client["end"]
    def amount(key):
        obj = end[key]
        count = obj["bytes"]
        require(isinstance(count, int) and count > 0 and obj["seconds"] >= DURATION - 1,
                "short or empty TCP transfer")
        return count
    forward = amount("sum_received")
    if mode == "forward":
        result = {"rx": forward}
    elif mode == "reverse":
        result = {"tx": forward}
    else:
        require(mode == "bidir", "unknown TCP mode")
        result = {"rx": forward, "tx": amount("sum_received_bidir_reverse")}
    if server is not None:
        require(not server.get("error"), "iperf server error")
        if "rx" in result:
            require(server["end"]["sum_received"]["bytes"] == result["rx"],
                    "server and client disagree on router received bytes")
        if "tx" in result:
            key = "sum_sent_bidir_reverse" if mode == "bidir" else "sum_sent"
            require(server["end"][key]["bytes"] >= result["tx"],
                    "router sent fewer bytes than peer received")
    return result


def assess(before, after, path, payload):
    require(before["fields"]["boot"] == after["fields"]["boot"], "mixed boot")
    mib = probe["delta"](before, after)
    def changes(a, b):
        require(a.keys() == b.keys(), "counter set changed")
        d = {k: b[k] - a[k] for k in a}
        require(all(v >= 0 for v in d.values()), "counter reset/wrap")
        return d
    macs = {p: changes(before["macs"][p], after["macs"][p]) for p in PATHS}
    host = {p: changes(before["host"][p], after["host"][p]) for p in PATHS}
    require(all(v >= 0 for row in mib.values() for v in row.values()), "RTL counter reset")
    require(not any(row[k] for row in mib.values() for k in probe["ERRORS"]),
            "RTL errors during TCP load")
    require(not any(row[k] for row in macs.values() for k in ERRORS),
            "XGMAC errors during TCP load")
    other = "direct" if path == "switch" else "switch"
    for direction, count in payload.items():
        host_key = "tx_bytes" if direction == "rx" else "rx_bytes"
        mac_key = direction+"_bytes_g"
        cpu_key = "ifOutOctets" if direction == "rx" else "ifInOctets"
        copper_key = "ifInOctets" if direction == "rx" else "ifOutOctets"
        require(host[path][host_key] >= count and macs[path][mac_key] >= count,
                "selected host/Qualcomm MAC cannot account for received payload")
        require(host[other][host_key] < count and macs[other][mac_key] < count,
                "other physical path could account for payload")
        if path == "switch":
            require(mib["cpu"][cpu_key] >= count and mib["copper"][copper_key] >= count,
                    "Realtek trunk/copper cannot account for received payload")
        else:
            require(mib["cpu"][cpu_key] < count and mib["copper"][copper_key] < count,
                    "direct control not isolated from Realtek payload")
    return {"payload_bytes": payload, "mib_delta": mib,
            "xgmac_delta": macs, "host_delta": host}


@contextmanager
def runtime(boot):
    path = "/tmp/wave7-ordering-bench-" + boot
    probe["run"](["sha256sum", "-c", str(RUNTIME / "sha256sums")])
    remote(f"test \"$(cat /proc/sys/kernel/random/boot_id)\" = '{boot}' && "
           f"test ! -e '{path}' && mkdir -m 700 '{path}'")
    try:
        opts = probe["ssh_args"]("true")[2:-2]
        for name in FILES:
            file = RUNTIME / name
            probe["run"](["scp", "-q", "-O", *opts, str(file),
                          f"root@{probe['ROUTER']}:{path}/"], timeout=20)
            local = probe["run"](["sha256sum", str(file)]).split()[0]
            actual = remote(f"sha256sum '{path}/{name}'").split()[0]
            require(local == actual, "router runtime digest mismatch")
        yield path
    finally:
        names = " ".join(f"'{path}/{name}'" for name in FILES)
        remote(f"test \"$(cat /proc/sys/kernel/random/boot_id)\" = '{boot}' && "
               f"rm -f {names} && rmdir '{path}'")


def listening():
    return any(line.split()[3].endswith(f":{PORT}") for line in
               remote("netstat -lnt").splitlines() if line.startswith("tcp"))


# A finite read-only sampler, running once per second on each endpoint.
# Use boot IDs and monotonic uptime, not wall clock assumptions.
PROFILE_COMMAND = r"""set -eu
echo "boot=$(cat /proc/sys/kernel/random/boot_id)"
i=0
while [ "$i" -lt 15 ]; do
    echo "=== SAMPLE $i ==="
    cat /proc/uptime
    sed -n '/^cpu[0-9]/p' /proc/stat
    echo SOFTNET
    cat /proc/net/softnet_stat
    echo SOFTIRQS
    sed -n '/NET_RX:/p; /NET_TX:/p' /proc/softirqs
    echo FREQ
    for f in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq; do
        [ ! -r "$f" ] || printf '%s %s\n' "$f" "$(cat "$f")"
    done
    echo END_SAMPLE
    i=$((i+1))
    sleep 1
done
echo "end_boot=$(cat /proc/sys/kernel/random/boot_id)"
"""


@contextmanager
def profile_load(out, name, boot, enabled):
    if not enabled:
        yield
        return
    from contextlib import ExitStack
    with ExitStack() as stack:
        jobs = []
        for endpoint, cmd in (("router", probe["ssh_args"](PROFILE_COMMAND)),
                              ("host", ["sh", "-c", PROFILE_COMMAND])):
            stdout = stack.enter_context((out / f"{name}-{endpoint}-cpu.txt").open("x"))
            stderr = stack.enter_context((out / f"{name}-{endpoint}-cpu.err").open("x"))
            jobs.append(subprocess.Popen(cmd, stdout=stdout, stderr=stderr))
        try:
            yield
        finally:
            for job in jobs:
                try:
                    job.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    job.terminate()
                    job.wait(timeout=5)
            require(all(job.returncode == 0 for job in jobs), "CPU sampler failed")
    raw = (out / f"{name}-router-cpu.txt").read_text()
    require(raw.startswith(f"boot={boot}\n") and raw.endswith(f"end_boot={boot}\n"),
            "CPU sampler boot mismatch")


def run_case(out, path, mode, runtime_dir, variant, boot, bitrate, profile=False):
    name = f"{path}-{mode}"
    before = sample(out, name+"-before", variant, boot)
    require(not listening(), "benchmark server port occupied")
    # The runtime is the existing hashed temporary ARM64 iperf package.
    # One-shot server, bounded even when SSH or the client fails.
    command = (f"timeout 35 env LD_LIBRARY_PATH='{runtime_dir}' "
               f"'{runtime_dir}/iperf3' -s -1 -B {probe['ROUTER']} -p {PORT} -J")
    with (out / f"{name}-server.json").open("x") as stdout, \
         (out / f"{name}-server.err").open("x") as stderr:
        server = subprocess.Popen(probe["ssh_args"](command), stdout=stdout, stderr=stderr)
        try:
            for _ in range(20):
                require(server.poll() is None, "server exited before client")
                if listening():
                    break
                time.sleep(0.2)
            else:
                raise ValueError("benchmark server did not listen")
            ip, dev, *_ = PATHS[path]
            flags = {"forward": [], "reverse": ["-R"], "bidir": ["--bidir"]}[mode]
            argv = ["iperf3", "-4", "-c", probe["ROUTER"], "-B", ip, "--bind-dev", dev,
                    "-p", str(PORT), "--connect-timeout", "4000", "-t", str(DURATION),
                    "-J", *flags]
            if bitrate is not None:
                argv.extend(["-b", str(bitrate * 1_000_000)])
            with profile_load(out, name, boot, profile):
                result = subprocess.run(argv, text=True, capture_output=True, timeout=25)
            (out / f"{name}-client.json").write_text(result.stdout)
            (out / f"{name}-client.err").write_text(result.stderr)
            result.check_returncode()
            require(server.wait(timeout=10) == 0, "iperf server error")
            client = json.loads(result.stdout)
            server_report = json.loads((out / f"{name}-server.json").read_text())
            require(not server_report.get("error"), "server JSON error")
        finally:
            if server.poll() is None:
                try:
                    server.wait(timeout=36)
                except subprocess.TimeoutExpired:
                    server.terminate()
                    server.wait(timeout=5)
    after = sample(out, name+"-after", variant, boot)
    payload = received_bytes(client, mode, server_report)
    summaries = {d: client["end"]["sum_received_bidir_reverse"
                                  if mode=="bidir" and d=="tx" else "sum_received"]
                 for d in payload}
    return {"name": name, **assess(before, after, path, payload),
            "receiver_mbps": {d: row["bits_per_second"]/1e6 for d,row in summaries.items()},
            "iperf_end": client["end"]}


def bench(run, peers, modes, bitrate, profile=False):
    record = cohort["load_run"](run)
    require(record is not None and record["variant"] in ("stock-order", "force-order")
            and record["outcome"] == "clean" and record["direct_mbps"] == 2500,
            "requires sealed clean ordering boot at 2.5GbE direct")
    variant, boot = record["variant"], record["boot"]
    suffix = "-no-omit" + ("" if bitrate is None else f"-paced-{bitrate}mbps")
    if peers != ("switch", "direct") or modes != ("forward", "reverse", "bidir"):
        suffix += "-" + "-".join(peers) + "-" + "-".join(modes)
    if profile:
        suffix += "-profile"
    out = run / ("throughput" + suffix)
    report = {"boot": boot, "variant": variant, "duration": DURATION,
              "offered_mbps_per_direction": bitrate, "omit_seconds": 0,
              "peers": peers, "modes": modes, "cpu_profile": profile, "cases": []}
    failure = None
    with probe["lab_session"](out):
        try:
            initial = sample(out, "initial", variant, boot)
            require(not any(row[k] for row in initial["counters"].values()
                            for k in probe["ERRORS"] if k != "etherStatsDropEvents")
                    and not any(row[k] for row in initial["macs"].values()
                                for k in ERRORS if k not in ("rx_fifo_overflow", "rx_drop_frames")),
                    "initial hardware corruption counters are not zero")
            with runtime(boot) as path:
                (out / "version.txt").write_text(remote(
                    f"LD_LIBRARY_PATH='{path}' '{path}/iperf3' --version"))
                for peer in peers:
                    for mode in modes:
                        case = run_case(out, peer, mode, path, variant, boot, bitrate, profile)
                        report["cases"].append(case)
                        print(json.dumps({"case":case["name"],"receiver_mbps":case["receiver_mbps"]}),
                              flush=True)
            report["status"] = "PASS"
        except Exception as exc:
            report["status"] = "FAILED"
            report["error"] = str(exc)
            failure = exc
        (out / "report.json").write_text(json.dumps(report, indent=2)+"\n")
    if failure:
        raise failure


def selftest():
    def state(n):
        return {"fields":{"boot":"test","noc":"0","uptime":str(n)},
                "counters":{p:{k:0 for k in probe["FIELDS"]} for p in probe["MACS"]},
                "macs":{p:{k:0 for k in (*probe["XGMAC"],*MAC_BYTES)} for p in PATHS},
                "host":{p:{"rx_bytes":0,"tx_bytes":0} for p in PATHS}}
    before = state(0)
    for peer in PATHS:
        for direction in ("rx","tx"):
            after = state(1)
            host_key = "tx_bytes" if direction=="rx" else "rx_bytes"
            after["host"][peer][host_key] = 100
            after["macs"][peer][direction+"_bytes_g"] = 101
            if peer=="switch":
                after["counters"]["cpu"]["ifOutOctets" if direction=="rx" else "ifInOctets"]=102
                after["counters"]["copper"]["ifInOctets" if direction=="rx" else "ifOutOctets"]=103
            assess(before,after,peer,{direction:100})
            after["host"][peer][host_key]=99
            try:
                assess(before,after,peer,{direction:100})
            except ValueError:
                pass
            else:
                raise AssertionError("counter deficit accepted")
    fake={"end":{"sum_received":{"bytes":100,"seconds":12},
                 "sum_received_bidir_reverse":{"bytes":200,"seconds":12}}}
    server={"end":{"sum_received":{"bytes":100},"sum_sent_bidir_reverse":{"bytes":201}}}
    require(received_bytes(fake,"bidir",server)=={"rx":100,"tx":200},"bidir mapping")
    require(received_bytes(fake,"reverse")=={"tx":100},"reverse mapping")
    after=state(1)
    after["host"]["switch"]["tx_bytes"]=100
    after["macs"]["switch"]["rx_bytes_g"]=100
    after["counters"]["cpu"]["ifOutOctets"]=100
    after["counters"]["copper"]["ifInOctets"]=100
    assess(before,after,"switch",{"rx":100})
    for row,key in ((after["macs"]["direct"],"rx_bytes_g"),
                    (after["counters"]["cpu"],"dot3StatsFCSErrors")):
        row[key]=100
        try: assess(before,after,"switch",{"rx":100})
        except ValueError: pass
        else: raise AssertionError("wrong path or corruption accepted")
        row[key]=0
    try: received_bytes(fake,"bidir",{"end":{"sum_received":{"bytes":99}}})
    except ValueError: pass
    else: raise AssertionError("inconsistent endpoint payload accepted")
    print("ORDERING_TCP_ACCOUNTING_SELFTEST_PASS")


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("selftest")
    b=sub.add_parser("bench")
    b.add_argument("run",type=Path)
    b.add_argument("--peer",choices=tuple(PATHS),action="append")
    b.add_argument("--mode",choices=("forward", "reverse", "bidir"),action="append")
    b.add_argument("--bitrate-mbps",type=int)
    b.add_argument("--profile",action="store_true",help="sample per-core CPU and network backlog")
    args=parser.parse_args()
    if args.command=="selftest":
        selftest()
    else:
        require(args.bitrate_mbps is None or 0 < args.bitrate_mbps <= 2500, "invalid bitrate")
        peers = tuple(args.peer or ("switch", "direct"))
        modes = tuple(args.mode or ("forward", "reverse", "bidir"))
        require(len(set(peers))==len(peers) and len(set(modes))==len(modes), "duplicate case selection")
        bench(args.run.resolve(), peers, modes, args.bitrate_mbps, args.profile)
