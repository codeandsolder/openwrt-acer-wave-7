#!/usr/bin/env -S uv run --no-project python
"""Physical packet/counter accounting on the guarded Wave7 lab.

No flash, reset, configuration or register writes. The existing lab-control
lock excludes other captures/trials. Observe ordinary driver stats reads,
not the indirect SRAM bus itself. Background traffic is allowed, so the
number of physically observed probe frames is a lower bound on MIB deltas.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

BASE = Path("/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8")
ROUTER = "192.168.76.1"
PATHS = {
    "direct": ("192.168.76.2", "enp4s0f4u2u4", "762", "00:e0:4c:68:00:6d", "2500"),
    "switch": ("192.168.76.250", "enp4s0f4u2u2u4", "763", "00:e0:4c:68:01:45", "1000"),
}
PINS = {
    "0498": ("f9aa3e1fa3", "ff6b4c93d9ce2cb71b2b8dfd0053df70cc4a3ad4960bd49c099eceea85d7fe91"),
    "mib-refresh": ("14a0f757e7", "0675df8af2c490bb5957be5cc2d2124c6500cdcf01d09cef02b744d5e090a485"),
    "stock-order": ("472043f203", "2d0da46a3bb51ebc52d4b70c3e31a4808bcf3a82955bf1b4414375d407aff319"),
    "force-order": ("b9db617b17", "bea25a2aafd1bc236740ad089bc9500b4f064034fd11cec959abd9bb208d322e"),
}
FIELDS = ("ifInUcastPkts", "ifOutUcastPkts", "ifInOctets", "ifOutOctets",
          "dot3StatsFCSErrors", "etherStatsFragments", "etherStatsDropEvents")
ERRORS = FIELDS[4:]
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
    commit, module = PINS[variant]
    expected = {"rev": f"r0+38346-{commit}-ap-dhcp-guard8",
                "peer": PATHS["direct"][0], "bootfail":"0", "keep":"1",
                "q6":"3", "lan":"2500", "lan1":"1000",
                "module":module, "module_rom":module, "module_live":"live",
                "module_upper_clear":"1"}
    require(BOOT.fullmatch(fields["boot"]) and fields["end_boot"] == fields["boot"], "mixed boot")
    require(all(fields.get(k)==v for k,v in expected.items()), "snapshot identity or link mismatch")
    require(fields["noc"].isdecimal(), "invalid NoC count")
    for port in MACS:
        require(set(sections[port]) == set(FIELDS), f"missing {port} MIB fields")
    return {"fields":fields,"counters":sections,"wall":time.time()}


def snapshot(out, name, variant):
    ip,dev,*_ = PATHS["direct"]
    raw = run(["ssh","-nT","-i","/home/jan/.ssh/wave7-root-rsa",
               "-o",f"BindInterface={dev}","-o",f"BindAddress={ip}",
               "-o","BatchMode=yes","-o","IdentitiesOnly=yes",
               "-o","StrictHostKeyChecking=yes","-o",f"UserKnownHostsFile={BASE/'known_hosts'}",
               "-o","ConnectTimeout=4","-o","ConnectionAttempts=1",f"root@{ROUTER}",REMOTE],20)
    (out/f"{name}.txt").write_text(raw)
    return parse_snapshot(raw,variant)


def delta(before, after):
    require(before["fields"]["boot"] == after["fields"]["boot"], "boot changed")
    require(before["fields"]["noc"] == after["fields"]["noc"], "new NoC fault")
    require(float(after["fields"]["uptime"]) >= float(before["fields"]["uptime"]), "uptime decreased")
    return {port:{k:after["counters"][port][k]-before["counters"][port][k] for k in FIELDS}
            for port in MACS}


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
    monotonic = all(repeat[p][k]>=first[p][k]>=0 for p in MACS for k in FIELDS)
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
    elif lower is None:
        kind = "DIRECT_CONTROL"
    elif sufficient(first):
        kind = "FRESH_FIRST_READ"
    elif sufficient(repeat):
        kind = "FRESH_ONLY_ON_REPEAT"
    else:
        kind = "COUNTER_DEFICIT"
    return {"id":ident,"path":path,"count":count,"payload":phase["payload"],
            "kind":kind,"requests":len(packets[8]),"replies":len(packets[0]),
            "wrong_path_frames":sum(map(len,other.values())),
            "lower_bounds":lower,"delta":first,"repeat_delta":repeat}


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


def capture(variant,out):
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
        procs={}
        logs={}
        phase_data=[]
        try:
            for name,(_,dev,*_) in PATHS.items():
                logs[name]=(out/f"{name}-capture.log").open("xb")
                filt="icmp and host 192.168.76.1 and (host 192.168.76.2 or host 192.168.76.250) and icmp[4:2] >= 48101 and icmp[4:2] <= 48106"
                procs[name]=subprocess.Popen(["dumpcap","-q","-p","-i",dev,"-f",filt,
                    "-s","160","-a","duration:180","-w",str(out/f"{name}.pcapng")],
                    stdout=logs[name],stderr=subprocess.STDOUT)
            deadline=time.monotonic()+5
            while not all((out/f"{n}.pcapng").exists() and p.poll() is None
                          for n,p in procs.items()):
                require(time.monotonic()<deadline,"capture failed to arm")
                time.sleep(.1)
            time.sleep(.3)
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
                    "repeat_delta":delta(before,repeat)})
                delta(initial,repeat)
                (out/"phases.json").write_text(json.dumps(phase_data,indent=2)+"\n")
            routes_after=routes()
            (out/"routes-after.json").write_text(json.dumps(routes_after,indent=2)+"\n")
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
        captures={name:extract(out,name) for name in PATHS}
        report=[assess(p,captures) for p in phase_data]
        summary={"variant":variant,"boot":initial["fields"]["boot"],
            "historical_noc":int(initial["fields"]["noc"]),"phases":report}
        (out/"report.json").write_text(json.dumps(summary,indent=2)+"\n")
        files=sorted(p for p in out.iterdir() if p.is_file())
        (out/"SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in files))
        print(json.dumps(summary,indent=2))


def selftest():
    base=dict.fromkeys(FIELDS,0)
    counters={p:{**base,**{k:1000 for k in FIELDS[:4]}} for p in MACS}
    phase={"id":48102,"path":"switch","count":2,"payload":64,"ping_rc":0,
           "delta":counters,"repeat_delta":counters}
    packets={8:[(1,106),(2,106)],0:[(1,106),(2,106)]}
    captures={"switch":{48102:packets},"direct":{}}
    require(assess(phase,captures)["kind"]=="FRESH_FIRST_READ","fresh")
    zero={p:dict(base) for p in MACS}
    require(assess({**phase,"delta":zero},captures)["kind"]=="FRESH_ONLY_ON_REPEAT","repeat")
    require(assess({**phase,"delta":zero,"repeat_delta":zero},captures)["kind"]=="COUNTER_DEFICIT","deficit")
    require(assess({**phase,"repeat_delta":zero},captures)["kind"]=="NONMONOTONIC_COUNTERS","decreasing")
    require(assess(phase,{**captures,"direct":{48102:packets}})["kind"]=="PACKET_PATH_MISMATCH","wrong NIC")
    require(assess(phase,{"switch":{},"direct":{}})["kind"]=="PACKET_PATH_MISMATCH","missing")
    print("MIB_PHYSICAL_ACCOUNTING_SELFTEST_PASS")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("selftest")
    p=sub.add_parser("capture")
    p.add_argument("variant",choices=PINS)
    p.add_argument("out",type=Path)
    args=parser.parse_args()
    if args.command=="selftest":
        selftest()
    else:
        expected=BASE/"mib-refresh-dhcp-guard8"/"observations"
        require(args.out.parent.resolve()==expected.resolve(),"output must be in MIB observations")
        capture(args.variant,args.out)
