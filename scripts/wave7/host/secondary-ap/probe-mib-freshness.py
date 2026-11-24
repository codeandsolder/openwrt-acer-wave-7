#!/usr/bin/env -S uv run --no-project python
"""Physical packet/counter accounting on the guarded Wave7 lab.

No flash, reset or raw register writes. The latch mode arms only a
revision-pinned, lab-only driver parameter. The existing lab-control
lock excludes other captures/trials. Observe ordinary driver stats reads,
not the indirect SRAM bus itself. Background traffic is allowed, so the
number of physically observed probe frames is a lower bound on MIB deltas.
"""
import argparse
from contextlib import contextmanager
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import signal
import select
import subprocess
import time

BASE = Path("/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8")
ROUTER = "192.168.76.1"
PATHS = {
    "direct": ("192.168.76.2", "enp4s0f4u2u4", "762", "00:e0:4c:68:00:6d", "2500"),
    "switch": ("192.168.76.250", "enp4s0f4u2u2u4", "763", "00:e0:4c:68:01:45", "1000"),
}
COHORT = runpy.run_path(str(Path(__file__).with_name("report-ordering-cohort.py")))
IDENTITIES = COHORT["PINS"]
PINS = {name: pin[:2] for name, pin in IDENTITIES.items()}
FIELDS = ("ifInUcastPkts", "ifOutUcastPkts", "ifInOctets", "ifOutOctets",
          "dot3StatsFCSErrors", "etherStatsFragments", "etherStatsDropEvents")
ERRORS = FIELDS[4:]
# These are unique PPE XGMAC hardware statistics in ethtool -S switch.
# rx_bytes and tx_bytes are deliberately excluded: EDMA exports those
# same names earlier in the result.
XGMAC_ERRORS = ("rx_crc_err","rx_frag_err","rx_jabber_err","rx_len_err",
                "rx_fifo_overflow","rx_drop_frames","tx_underflow_err")
XGMAC = ("rx_frames","tx_frames","rx_unicast_g","tx_unicast",
         "rx_pause","tx_pause",*XGMAC_ERRORS)
MACS = ("cpu", "copper")
PHASES = [
    ("direct", 32, 64), ("switch", 32, 64),
    ("direct", 48, 256), ("switch", 48, 256),
    ("direct", 64, 1024), ("switch", 64, 1024),
]
REMOTE = r"""set -eu
echo "boot=$(cat /proc/sys/kernel/random/boot_id)"
echo "rev=$(cat /rom/etc/openwrt_version)"
echo "peer=${SSH_CONNECTION%% *}"
echo "bootfail=$(fw_printenv -n bootfail)"
echo "keep=$(test -e /tmp/wave7-keep-boot && echo 1 || echo 0)"
echo "uptime=$(cut -d' ' -f1 /proc/uptime)"
echo "noc=$(dmesg | grep -c 'NOC ERROR DETECTED' || :)"
echo "q6=$(for p in /sys/class/remoteproc/remoteproc[012]; do cat "$p/state"; done | grep -c '^running$')"
echo "lan=$(cat /sys/class/net/lan/speed)"
echo "lan1=$(cat /sys/class/net/lan1/speed)"
p=lib/modules/6.18.60/rtl8365mb.ko
echo "module=$(sha256sum /$p | cut -d' ' -f1)"
echo "module_rom=$(sha256sum /rom/$p | cut -d' ' -f1)"
echo "module_live=$(cat /sys/module/rtl8365mb/initstate)"
for item in pcs:pcs-qcom-ipq9574:pcs_qcom_ipq9574 ppe:qcom-ppe:qcom_ppe; do
    name=${item%%:*}; rest=${item#*:}; file=${rest%%:*}; mod=${rest#*:}
    p=lib/modules/6.18.60/$file.ko
    echo "${name}_sha=$(sha256sum /$p | cut -d' ' -f1)"
    echo "${name}_rom_sha=$(sha256sum /rom/$p | cut -d' ' -f1)"
    echo "${name}_live=$(cat /sys/module/$mod/initstate)"
    echo "${name}_taint=$(cat /sys/module/$mod/taint)"
done
echo "manifest_handoff_patch=$(sed -n 's/^trial_pcs0_handoff_patch_commit=//p' /rom/etc/wave7-role-profile)"
echo "manifest_feature_patch=$(sed -n 's/^trial_edma_feature_init_patch_commit=//p' /rom/etc/wave7-role-profile)"
echo "manifest_fixed_patch=$(sed -n 's/^trial_pcs0_\(stock_mode\|force_only\)_patch_commit=//p' /rom/etc/wave7-role-profile)"
echo "module_upper_clear=$(test ! -e /overlay/upper/lib/modules && test ! -L /overlay/upper/lib/modules && echo 1 || echo 0)"
echo '=== CPU ==='
ethtool -S switch
echo '=== COPPER ==='
ethtool -S lan1
echo "end_boot=$(cat /proc/sys/kernel/random/boot_id)"
"""
BOOT = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def run(argv, timeout=10):
    return subprocess.run(argv, check=True, text=True, capture_output=True, timeout=timeout).stdout


def routes():
    result = {}
    for name, (ip, dev, table, mac, speed) in PATHS.items():
        sys = Path("/sys/class/net") / dev
        require((sys/"address").read_text().strip() == mac, f"{name}: MAC mismatch")
        require((sys/"carrier").read_text().strip() == "1", f"{name}: carrier down")
        require((sys/"speed").read_text().strip() == speed, f"{name}: speed mismatch")
        records = json.loads(run(["ip", "-j", "-4", "route", "get", ROUTER, "from", ip]))
        require(len(records) == 1, f"{name}: ambiguous route")
        require(all(str(records[0].get(k)) == v for k,v in
                    (("dev",dev),("table",table),("from",ip))), f"{name}: route mismatch")
        result[name] = records[0]
    return result


def parse_xgmac(raw):
    counters={}
    for line in raw.splitlines():
        match=re.fullmatch(r"\s*(\w+):\s+(\d+)",line)
        if match and match[1] in XGMAC:
            require(match[1] not in counters,"duplicate XGMAC counter")
            counters[match[1]]=int(match[2])
    require(set(counters)==set(XGMAC),"missing XGMAC counters")
    return counters


def parse_snapshot(raw, variant):
    sections = {"cpu": {}, "copper": {}}
    fields = {}
    port = None
    for line in raw.splitlines():
        if line == "=== CPU ===":
            port = "cpu"
        elif line == "=== COPPER ===":
            port = "copper"
        elif re.match(r"^\w+=", line):
            key, val = line.split("=", 1)
            require(key not in fields, f"duplicate metadata: {key}")
            fields[key] = val
        elif port is not None:
            pattern = r"\s*s00_p06_(\w+):\s+(\d+)" if port == "cpu" else r"\s*(\w+):\s+(\d+)"
            match = re.fullmatch(pattern, line)
            if match and match[1] in FIELDS:
                require(match[1] not in sections[port], f"duplicate {port} counter {match[1]}")
                sections[port][match[1]] = int(match[2])
    commit, module, pcs, ppe, handoff, feature = IDENTITIES[variant]
    expected = {"rev": f"r0+38346-{commit}-ap-dhcp-guard8",
                "peer": PATHS["direct"][0], "bootfail":"0", "keep":"1",
                "q6":"3", "lan":"2500", "lan1":"1000",
                "module":module, "module_rom":module, "module_live":"live",
                "module_upper_clear":"1",
                "pcs_sha":pcs, "pcs_rom_sha":pcs, "pcs_live":"live", "pcs_taint":"",
                "ppe_sha":ppe, "ppe_rom_sha":ppe, "ppe_live":"live", "ppe_taint":"",
                "manifest_handoff_patch":handoff, "manifest_feature_patch":feature,
                "manifest_fixed_patch":COHORT["FIXED_MODE_PINS"].get(variant,"")}
    require(BOOT.fullmatch(fields["boot"]) and fields["end_boot"] == fields["boot"], "mixed boot")
    require(all(fields.get(k, "" if k=="manifest_fixed_patch" else None)==v for k,v in expected.items()), "snapshot identity or link mismatch")
    require(fields["noc"].isdecimal(), "invalid NoC count")
    for port in MACS:
        require(set(sections[port]) == set(FIELDS), f"missing {port} MIB fields")
    cpu_raw=raw.split("=== CPU ===\n",1)[1].split("=== COPPER ===\n",1)[0]
    return {"fields":fields,"counters":sections,"xgmac":parse_xgmac(cpu_raw),"wall":time.time()}


def ssh_args(command, stdin=False):
    ip,dev,*_ = PATHS["direct"]
    return ["ssh","-T" if stdin else "-nT","-i","/home/jan/.ssh/wave7-root-rsa",
            "-o",f"BindInterface={dev}","-o",f"BindAddress={ip}",
            "-o","BatchMode=yes","-o","IdentitiesOnly=yes",
            "-o","StrictHostKeyChecking=yes","-o",f"UserKnownHostsFile={BASE/'known_hosts'}",
            "-o","ConnectTimeout=4","-o","ConnectionAttempts=1",f"root@{ROUTER}",command]


def remote(command, timeout=20):
    return run(ssh_args(command),timeout)


def snapshot(out, name, variant):
    raw = remote(REMOTE)
    (out/f"{name}.txt").write_text(raw)
    return parse_snapshot(raw,variant)

def delta(before, after):
    require(before["fields"]["boot"] == after["fields"]["boot"], "boot changed")
    require(before["fields"]["noc"] == after["fields"]["noc"], "new NoC fault")
    require(float(after["fields"]["uptime"]) >= float(before["fields"]["uptime"]), "uptime decreased")
    return {port:{k:after["counters"][port][k]-before["counters"][port][k] for k in FIELDS}
            for port in MACS}


def xgmac_delta(before,after):
    require(before["fields"]["boot"]==after["fields"]["boot"],"XGMAC boot changed")
    return {key:after["xgmac"][key]-before["xgmac"][key] for key in XGMAC}


def lower_bounds(packets):
    requests, replies = packets[8], packets[0]
    req, rep = len(requests), len(replies)
    req_bytes = sum(length for _,length in requests)
    rep_bytes = sum(length for _,length in replies)
    return {"cpu":{"ifOutUcastPkts":req,"ifInUcastPkts":rep,
                   "ifOutOctets":req_bytes,"ifInOctets":rep_bytes},
            "copper":{"ifInUcastPkts":req,"ifOutUcastPkts":rep,
                      "ifInOctets":req_bytes,"ifOutOctets":rep_bytes}}


def assess(phase, captures):
    ident, path, count = phase["id"], phase["path"], phase["count"]
    packets = captures[path].get(ident,{8:[],0:[]})
    other = captures["direct" if path == "switch" else "switch"].get(ident,{8:[],0:[]})
    expected = list(range(1,count+1))
    physical_ok = all(sorted(seq for seq,_ in packets[t]) == expected for t in (8,0))
    physical_ok &= not any(other.values())
    first, repeat = phase["delta"], phase["repeat_delta"]
    mac, mac_repeat = phase["xgmac_delta"],phase["repeat_xgmac_delta"]
    monotonic = (all(repeat[p][k]>=first[p][k]>=0 for p in MACS for k in FIELDS)
                 and all(mac_repeat[k]>=mac[k]>=0 for k in XGMAC))
    errors = {p:{k:repeat[p][k] for k in ERRORS} for p in MACS}
    lower = lower_bounds(packets) if path=="switch" else None
    def sufficient(d):
        return all(d[p][k]>=v for p,b in lower.items() for k,v in b.items())
    if not physical_ok or phase["ping_rc"] != 0:
        kind = "PACKET_PATH_MISMATCH"
    elif not monotonic:
        kind = "NONMONOTONIC_COUNTERS"
    elif any(v for p in errors.values() for v in p.values()):
        kind = "COUNTER_ERRORS"
    elif any(mac_repeat[k] for k in XGMAC_ERRORS):
        kind = "XGMAC_ERRORS"
    elif lower is None:
        kind = "DIRECT_CONTROL"
    elif (mac["rx_unicast_g"]<len(packets[8]) or
          mac["tx_unicast"]<len(packets[0])):
        kind = "XGMAC_COUNTER_DEFICIT"
    elif sufficient(first):
        kind = "FRESH_FIRST_READ"
    elif sufficient(repeat):
        kind = "FRESH_ONLY_ON_REPEAT"
    else:
        kind = "COUNTER_DEFICIT"
    return {"id":ident,"path":path,"count":count,"payload":phase["payload"],
            "kind":kind,"requests":len(packets[8]),"replies":len(packets[0]),
            "wrong_path_frames":sum(map(len,other.values())),
            "lower_bounds":lower,"delta":first,"repeat_delta":repeat,
            "xgmac_delta":mac,"repeat_xgmac_delta":mac_repeat}


def extract(out,name):
    raw=run(["tshark","-n","-r",str(out/f"{name}.pcapng"),"-Y","icmp.type == 8 || icmp.type == 0",
             "-T","fields","-E","occurrence=f","-e","icmp.ident","-e","icmp.seq",
             "-e","icmp.type","-e","ip.src","-e","ip.dst","-e","frame.len"],20)
    (out/f"{name}-packets.tsv").write_text(raw)
    data={}
    for row in raw.splitlines():
        ident,seq,kind,src,dst,length=row.split("\t")
        ident,seq,kind,length=map(int,(ident,seq,kind,length))
        require(kind in (0,8) and 48101<=ident<=48106, "unexpected captured packet")
        path=PHASES[ident-48101][0]
        host=PATHS[path][0]
        require((src,dst)==((host,ROUTER) if kind==8 else (ROUTER,host)), "wrong packet addresses")
        data.setdefault(ident,{0:[],8:[]})[kind].append((seq,length))
    return data


@contextmanager
def lab_session(out):
    require(os.getuid()!=0,"run as jan")
    lockpath=BASE/".lab-control.lock"
    require(lockpath.is_file() and not lockpath.is_symlink() and lockpath.stat().st_uid==os.getuid(),
            "invalid lab lock")
    with lockpath.open("r+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        runtime=f"/run/user/{os.getuid()}"
        bus=dict(os.environ,XDG_RUNTIME_DIR=runtime,DBUS_SESSION_BUS_ADDRESS=f"unix:path={runtime}/bus")
        active=subprocess.run(["systemctl","--user","--no-pager","--no-legend","list-units",
            "--state=active,activating","wave7-*supervisor-*","wave7-*watch-*","wave7-autonomous-observer-*"],
            env=bus,check=True,text=True,capture_output=True,timeout=10).stdout
        require(not active.strip(),"another firmware supervisor active")
        routes_before=routes()
        out.mkdir(mode=0o700,parents=False,exist_ok=False)
        (out/"routes-before.json").write_text(json.dumps(routes_before,indent=2)+"\n")
        yield
        routes_after=routes()
        (out/"routes-after.json").write_text(json.dumps(routes_after,indent=2)+"\n")
        seal(out)


@contextmanager
def capture_nics(out,filt):
    procs={}
    logs={}
    try:
        for name,(_,dev,*_) in PATHS.items():
            logs[name]=(out/f"{name}-capture.log").open("xb")
            procs[name]=subprocess.Popen(["dumpcap","-q","-p","-i",dev,"-f",filt,
                "-s","160","-a","duration:180","-w",str(out/f"{name}.pcapng")],
                stdout=logs[name],stderr=subprocess.STDOUT)
        deadline=time.monotonic()+5
        while not all((out/f"{n}.pcapng").exists() and p.poll() is None
                      for n,p in procs.items()):
            require(time.monotonic()<deadline,"capture failed to arm")
            time.sleep(.1)
        time.sleep(.3)
        yield
    finally:
        for proc in procs.values():
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
        for name,proc in procs.items():
            proc.wait(timeout=10)
            logs[name].close()
    require(all(p.returncode==0 for p in procs.values()),"capture failure")
    for name in PATHS:
        log=(out/f"{name}-capture.log").read_text()
        match=re.search(r"Packets received/dropped on interface '[^']+': (\d+)/(\d+)",log)
        require(match is not None and int(match[2])==0,
                f"{name}: capture drop count not confirmed")


def seal(out):
    files=sorted(p for p in out.iterdir() if p.is_file())
    (out/"SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in files))


def capture(variant,out):
    with lab_session(out):
        phase_data=[]
        filt="icmp and host 192.168.76.1 and (host 192.168.76.2 or host 192.168.76.250) and icmp[4:2] >= 48101 and icmp[4:2] <= 48106"
        with capture_nics(out,filt):
            initial=snapshot(out,"initial",variant)
            require(variant=="0498" or initial["fields"]["noc"]=="0","candidate has historical NoC faults")
            for index,(name,count,payload) in enumerate(PHASES,1):
                routes()
                ident=48100+index
                ip,dev,*_=PATHS[name]
                before=snapshot(out,f"{index:02}-before",variant)
                delta(initial,before)
                result=subprocess.run(["ping","-n","-D","-I",dev,"-I",ip,"-e",str(ident),
                     "-s",str(payload),"-c",str(count),"-i","0.2","-W","1",ROUTER],
                     text=True,capture_output=True,timeout=count*.2+6)
                (out/f"{index:02}-ping.txt").write_text(result.stdout+result.stderr)
                after=snapshot(out,f"{index:02}-after",variant)
                repeat=snapshot(out,f"{index:02}-repeat",variant)
                phase_data.append({"id":ident,"path":name,"count":count,"payload":payload,
                    "ping_rc":result.returncode,"delta":delta(before,after),
                    "repeat_delta":delta(before,repeat),
                    "xgmac_delta":xgmac_delta(before,after),
                    "repeat_xgmac_delta":xgmac_delta(before,repeat)})
                delta(initial,repeat)
                (out/"phases.json").write_text(json.dumps(phase_data,indent=2)+"\n")
        captures={name:extract(out,name) for name in PATHS}
        report=[assess(p,captures) for p in phase_data]
        summary={"variant":variant,"boot":initial["fields"]["boot"],
            "historical_noc":int(initial["fields"]["noc"]),"phases":report}
        (out/"report.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2))


# The kernel logs read-completion timestamps, not the start of the second
# bus transaction. Use only the first 150 ms of its explicit 250 ms sleep.
# Require both the request and its reply in that window, so a queued old
# reply cannot count as a newly forwarded CPU-ingress frame.
NS = 1_000_000_000
LATCH_ID = 48201
LATCH_COUNT = 500
PARAM = "/sys/module/rtl8365mb/parameters/mib_same_row_probe"
PROBE_LINE = re.compile(
    r"wave7-mib-probe port=6 row=190 initial=(\d+) same=(\d+) refreshed=(\d+) "
    r"initial_ns=(\d+) same_ns=(\d+) refreshed_ns=(\d+)$"
)


def ns(seconds):
    return int(Decimal(seconds)*NS)


@contextmanager
def clock_peer():
    # One tiny line per request; keep the authenticated session open for
    # both sets of brackets to exclude connection/handshake latency.
    command=r"""set -eu
printf 'READY\n'
while IFS= read -r request; do
    test "$request" = sample
    printf '%s %s\n' "$(cat /proc/sys/kernel/random/boot_id)" "$(cut -d' ' -f1 /proc/uptime)"
done
"""
    proc=subprocess.Popen(ssh_args(command,stdin=True),stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,bufsize=0)
    def readline():
        data=bytearray()
        deadline=time.monotonic()+5
        while not data.endswith(b"\n"):
            remain=deadline-time.monotonic()
            require(remain>0 and select.select([proc.stdout],[],[],remain)[0],"clock peer timeout")
            chunk=os.read(proc.stdout.fileno(),256)
            require(chunk and len(data)+len(chunk)<=256,"clock peer disconnected or malformed")
            data.extend(chunk)
        return data.decode("ascii").strip()
    def sample():
        proc.stdin.write(b"sample\n")
        return readline()
    try:
        require(readline()=="READY","clock peer not ready")
        yield sample
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=3)
        proc.stdout.close()


def clock_samples(boot,sample):
    samples=[]
    for _ in range(5):
        start=time.time_ns()
        mono_start=time.monotonic_ns()
        raw=sample()
        mono_end=time.monotonic_ns()
        end=time.time_ns()
        actual,uptime=raw.split()
        require(actual==boot,"boot changed during clock bracket")
        require(re.fullmatch(r"\d+\.\d{2}",uptime),"unexpected uptime precision")
        require(abs(end-start-(mono_end-mono_start))<5_000_000,"host wall-clock step")
        # /proc/uptime exposes boottime truncated to centiseconds.
        low=start-ns(uptime)-10_000_000
        high=end-ns(uptime)
        samples.append({"lower":low,"upper":high,"start":start,"end":end,"uptime":uptime})
    return samples


def clock_bounds(before,after):
    # Use the fastest round trip on either side. Take the union, not the
    # intersection, and add a drift margin over the short bounded trial.
    a,b=(min(x,key=lambda y:y["upper"]-y["lower"]) for x in (before,after))
    low=min(a["lower"],b["lower"])-5_000_000
    high=max(a["upper"],b["upper"])+5_000_000
    require(high-low<=100_000_000,"clock bracket too wide for latch witness")
    return low,high


def parse_probe(raw):
    lines=raw.splitlines()
    require(len(lines)==1,"expected exactly one new probe log line")
    match=PROBE_LINE.search(lines[0])
    require(match is not None,"diagnostic failed or malformed log")
    keys=("initial","same","refreshed","initial_ns","same_ns","refreshed_ns")
    return dict(zip(keys,map(int,match.groups())))


def latch_packets(out,name):
    raw=run(["tshark","-n","-r",str(out/f"{name}.pcapng"),"-Y","icmp.type == 8 || icmp.type == 0",
             "-T","fields","-E","occurrence=f","-e","icmp.ident","-e","icmp.seq",
             "-e","icmp.type","-e","ip.src","-e","ip.dst","-e","frame.time_epoch"],20)
    (out/f"{name}-packets.tsv").write_text(raw)
    packets={8:{},0:{}}
    host=PATHS["switch"][0]
    for line in raw.splitlines():
        ident,seq,kind,src,dst,stamp=line.split("\t")
        ident,seq,kind=map(int,(ident,seq,kind))
        require(ident==LATCH_ID and kind in (0,8) and 1<=seq<=LATCH_COUNT,"unexpected probe frame")
        require((src,dst)==((host,ROUTER) if kind==8 else (ROUTER,host)),"wrong probe IP")
        require(seq not in packets[kind],"duplicate probe frame")
        packets[kind][seq]=ns(stamp)
    return packets


def timed_witnesses(t0,bounds,packets,other,count):
    lower,upper=bounds
    # Only use the first 150 ms of the known 250 ms sleep.
    window=(t0+upper+5_000_000,t0+150_000_000+lower-5_000_000)
    expected=set(range(1,count+1))
    physical=all(set(packets[k])==expected for k in (8,0)) and not any(other.values())
    witnesses=sorted(seq for seq,request in packets[8].items()
                     if seq in packets[0] and window[0]<=request<=packets[0][seq]<=window[1])
    return window,physical,witnesses


def assess_latch(probe,bounds,packets,other,count):
    lower,upper=bounds
    first,same,refresh=(probe[k] for k in ("initial","same","refreshed"))
    t0,t1,t2=(probe[k] for k in ("initial_ns","same_ns","refreshed_ns"))
    require(t0+200_000_000<=t1<=t2,"invalid diagnostic timing")
    window,physical,witnesses=timed_witnesses(t0,bounds,packets,other,count)
    if not physical:
        kind="PACKET_PATH_MISMATCH"
    elif not first<=same<=refresh:
        kind="NONMONOTONIC_COUNTERS"
    elif not witnesses:
        kind="INSUFFICIENT_TIMED_TRAFFIC"
    elif same-first>=len(witnesses):
        kind="SAME_READ_FRESH_CONSISTENT"
    elif refresh-first>=len(witnesses):
        kind="SAME_ROW_STALE_REFRESH_RECOVERS"
    else:
        kind="BOTH_READS_DEFICIENT"
    return {"kind":kind,"probe":probe,"clock_offset_ns":[lower,upper],
            "conservative_window_epoch_ns":window,"witness_sequences":sorted(witnesses),
            "same_delta":same-first,"refresh_delta":refresh-first,
            "requests":len(packets[8]),"replies":len(packets[0]),
            "wrong_path_frames":sum(map(len,other.values()))}


def trigger_latch(boot,out):
    # Re-check the exact boot and image before changing the one-shot
    # parameter. The EXIT trap disarms even if the ethtool call fails.
    command=r"""set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = 'BOOT'
test "$(cat /rom/etc/openwrt_version)" = 'REV'
test "$(sha256sum /lib/modules/6.18.60/rtl8365mb.ko | cut -d' ' -f1)" = 'MODULE'
test "$(sha256sum /rom/lib/modules/6.18.60/rtl8365mb.ko | cut -d' ' -f1)" = 'MODULE'
test ! -e /overlay/upper/lib/modules
test ! -L /overlay/upper/lib/modules
test "$(cat /sys/module/rtl8365mb/initstate)" = live
test "$(fw_printenv -n bootfail)" = 0
test -e /tmp/wave7-keep-boot
test "$(dmesg | grep -c 'NOC ERROR DETECTED' || :)" = 0
p=PARAM
test "$(cat "$p")" = N
echo '=== BEFORE ==='
dmesg | grep 'wave7-mib-probe' || :
trap 'printf "N\n" > "$p"' EXIT
trap 'exit 1' HUP INT TERM
printf 'Y\n' > "$p"
ethtool -S switch >/dev/null
test "$(cat "$p")" = N
echo '=== AFTER ==='
dmesg | grep 'wave7-mib-probe' || :
test "$(cat /proc/sys/kernel/random/boot_id)" = 'BOOT'
"""
    commit,module=PINS["mib-diag"]
    command=command.replace("BOOT",boot).replace("REV",f"r0+38346-{commit}-ap-dhcp-guard8")
    command=command.replace("MODULE",module).replace("PARAM",PARAM)
    raw=remote(command)
    (out/"trigger.txt").write_text(raw)
    require(raw.startswith("=== BEFORE ===\n"),"missing pre-trigger log")
    before,after=raw.removeprefix("=== BEFORE ===\n").split("=== AFTER ===\n")
    before,after=before.splitlines(),after.splitlines()
    require(after[:len(before)]==before and len(after)==len(before)+1,"ambiguous new diagnostic log")
    return parse_probe(after[-1])


def timed_traffic(boot,out,action):
    wall_start,mono_start=time.time_ns(),time.monotonic_ns()
    with clock_peer() as sample:
        before=clock_samples(boot,sample)
        filt=f"icmp and host {ROUTER} and host {PATHS['switch'][0]} and icmp[4:2] = {LATCH_ID}"
        with capture_nics(out,filt):
            ip,dev,*_=PATHS["switch"]
            with (out/"ping.txt").open("xb") as log:
                proc=subprocess.Popen(["ping","-n","-D","-I",dev,"-I",ip,"-e",str(LATCH_ID),
                    "-s","64","-c",str(LATCH_COUNT),"-i","0.01","-W","1",ROUTER],
                    stdout=log,stderr=subprocess.STDOUT)
                try:
                    time.sleep(.5)
                    require(proc.poll() is None,"probe traffic exited before trigger")
                    result=action(sample)
                    require(proc.wait(timeout=15)==0,"probe traffic failed")
                    # AF_PACKET/libpcap batches may still hold the tail.
                    time.sleep(1)
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=5)
        after=clock_samples(boot,sample)
    require(abs(time.time_ns()-wall_start-(time.monotonic_ns()-mono_start))<5_000_000,
            "host wall-clock step during capture")
    (out/"clock.json").write_text(json.dumps({"before":before,"after":after},indent=2)+"\n")
    captures={name:latch_packets(out,name) for name in PATHS}
    return result,clock_bounds(before,after),captures


def checked_delta(initial,final):
    changes=delta(initial,final)
    require(all(changes[p][k]>=0 for p in MACS for k in FIELDS),"counters went backwards")
    require(not any(changes[p][k] for p in MACS for k in ERRORS),"physical switch errors during probe")
    return changes


def latch(out):
    with lab_session(out):
        require(remote(f"cat {PARAM}").strip()=="N","diagnostic parameter absent or armed")
        initial=snapshot(out,"initial","mib-diag")
        require(initial["fields"]["noc"]=="0","diagnostic boot has historical NoC faults")
        boot=initial["fields"]["boot"]
        probe,bounds,captures=timed_traffic(boot,out,lambda sample:trigger_latch(boot,out))
        final=snapshot(out,"final","mib-diag")
        changes=checked_delta(initial,final)
        require(remote(f"cat {PARAM}").strip()=="N","probe remained armed")
        report=assess_latch(probe,bounds,captures["switch"],captures["direct"],LATCH_COUNT)
        mac=xgmac_delta(initial,final)
        require(all(v>=0 for v in mac.values()) and not any(mac[k] for k in XGMAC_ERRORS),
                "XGMAC counter reset or error during latch probe")
        require(mac["rx_unicast_g"]>=LATCH_COUNT and mac["tx_unicast"]>=LATCH_COUNT,
                "XGMAC does not account for physical probe traffic")
        report.update(boot=boot,variant="mib-diag",counter_deltas=changes,xgmac_deltas=mac)
        (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


def clock_check(variant,out):
    # Read-only timing rehearsal, not a latch experiment. No driver
    # parameter is accessed and no synthetic counter result is generated.
    with lab_session(out):
        initial=snapshot(out,"initial",variant)
        boot=initial["fields"]["boot"]
        def mark(sample):
            actual,uptime=sample().split()
            require(actual==boot and re.fullmatch(r"\d+\.\d{2}",uptime),"invalid timing mark")
            (out/"timing-mark.txt").write_text(f"{actual} {uptime}\n")
            return ns(uptime)+10_000_000
        t0,bounds,captures=timed_traffic(boot,out,mark)
        final=snapshot(out,"final",variant)
        changes=checked_delta(initial,final)
        mac=xgmac_delta(initial,final)
        require(all(v>=0 for v in mac.values()) and not any(mac[k] for k in XGMAC_ERRORS),
                "XGMAC counter reset or error during timing rehearsal")
        require(mac["rx_unicast_g"]>=LATCH_COUNT and mac["tx_unicast"]>=LATCH_COUNT,
                "XGMAC does not account for physical probe traffic")
        window,physical,witnesses=timed_witnesses(
            t0,bounds,captures["switch"],captures["direct"],LATCH_COUNT)
        require(physical and witnesses,"timing rehearsal lacks physical witnesses")
        report={"kind":"TIMING_REHEARSAL_PASS","variant":variant,"boot":boot,
                "clock_offset_uncertainty_ns":bounds[1]-bounds[0],
                "conservative_window_epoch_ns":window,"witness_sequences":witnesses,
                "requests":len(captures["switch"][8]),"replies":len(captures["switch"][0]),
                "wrong_path_frames":sum(map(len,captures["direct"].values())),
                "counter_deltas":changes,"xgmac_deltas":mac}
        (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


def latch_selftest():
    base={"initial":10,"same":10,"refreshed":12,
          "initial_ns":NS,"same_ns":NS+250_000_000,"refreshed_ns":NS+251_000_000}
    offset=100*NS
    bounds=(offset-10_000_000,offset+10_000_000)
    packets={8:{1:101*NS+20_000_000,2:101*NS+40_000_000},
             0:{1:101*NS+21_000_000,2:101*NS+41_000_000}}
    empty={8:{},0:{}}
    def classify(p=base,frames=packets,other=empty):
        return assess_latch(p,bounds,frames,other,2)["kind"]
    require(classify()=="SAME_ROW_STALE_REFRESH_RECOVERS","stale latch")
    require(classify({**base,"same":12})=="SAME_READ_FRESH_CONSISTENT","fresh latch")
    require(classify({**base,"refreshed":11})=="BOTH_READS_DEFICIENT","both deficient")
    require(classify({**base,"same":9})=="NONMONOTONIC_COUNTERS","nonmonotonic")
    require(classify(other=packets)=="PACKET_PATH_MISMATCH","wrong NIC")
    require(classify(frames={8:packets[8],0:{}})=="PACKET_PATH_MISMATCH","missing packet")
    late={8:{k:v+200_000_000 for k,v in packets[8].items()},
          0:{k:v+200_000_000 for k,v in packets[0].items()}}
    require(classify(frames=late)=="INSUFFICIENT_TIMED_TRAFFIC","late packets")
    crossing={8:{1:101*NS,2:101*NS},0:packets[0]}
    require(classify(frames=crossing)=="INSUFFICIENT_TIMED_TRAFFIC","old requests")
    require(parse_probe("prefix wave7-mib-probe port=6 row=190 "+" ".join(
        f"{k}={v}" for k,v in base.items()))==base,"log parser")
    require(clock_bounds([{"lower":offset-1,"upper":offset+1}],
                         [{"lower":offset-2,"upper":offset+2}])==
            (offset-5_000_002,offset+5_000_002),"clock bracket")
    print("MIB_LATCH_ACCOUNTING_SELFTEST_PASS")


def selftest():
    base=dict.fromkeys(FIELDS,0)
    counters={p:{**base,**{k:1000 for k in FIELDS[:4]}} for p in MACS}
    mac={**dict.fromkeys(XGMAC,0),"rx_frames":2,"tx_frames":2,
         "rx_unicast_g":2,"tx_unicast":2}
    phase={"id":48102,"path":"switch","count":2,"payload":64,"ping_rc":0,
           "delta":counters,"repeat_delta":counters,
           "xgmac_delta":mac,"repeat_xgmac_delta":mac}
    packets={8:[(1,106),(2,106)],0:[(1,106),(2,106)]}
    captures={"switch":{48102:packets},"direct":{}}
    require(assess(phase,captures)["kind"]=="FRESH_FIRST_READ","fresh")
    zero={p:dict(base) for p in MACS}
    require(assess({**phase,"delta":zero},captures)["kind"]=="FRESH_ONLY_ON_REPEAT","repeat")
    require(assess({**phase,"delta":zero,"repeat_delta":zero},captures)["kind"]=="COUNTER_DEFICIT","deficit")
    require(assess({**phase,"repeat_delta":zero},captures)["kind"]=="NONMONOTONIC_COUNTERS","decreasing")
    require(assess(phase,{**captures,"direct":{48102:packets}})["kind"]=="PACKET_PATH_MISMATCH","wrong NIC")
    require(assess(phase,{"switch":{},"direct":{}})["kind"]=="PACKET_PATH_MISMATCH","missing")
    bad_mac={**mac,"rx_unicast_g":1}
    require(assess({**phase,"xgmac_delta":bad_mac},captures)["kind"]=="XGMAC_COUNTER_DEFICIT","XGMAC deficit")
    require(assess({**phase,"repeat_xgmac_delta":{**mac,"rx_crc_err":1}},captures)["kind"]=="XGMAC_ERRORS","XGMAC errors")
    require(parse_xgmac("".join(f"{k}: {v}\n" for k,v in mac.items()))==mac,"XGMAC parser")
    print("MIB_PHYSICAL_ACCOUNTING_SELFTEST_PASS")
    latch_selftest()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("selftest")
    p=sub.add_parser("capture")
    p.add_argument("variant",choices=PINS)
    p.add_argument("out",type=Path)
    c=sub.add_parser("clock-check")
    c.add_argument("variant",choices=PINS)
    c.add_argument("out",type=Path)
    q=sub.add_parser("latch")
    q.add_argument("out",type=Path)
    args=parser.parse_args()
    if args.command=="selftest":
        selftest()
    else:
        expected=BASE/"mib-refresh-dhcp-guard8"/"observations"
        require(args.out.parent.resolve()==expected.resolve(),"output must be in MIB observations")
        if args.command=="latch":
            latch(args.out)
        elif args.command=="clock-check":
            clock_check(args.variant,args.out)
        else:
            capture(args.variant,args.out)
