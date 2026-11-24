#!/usr/bin/env -S uv run --no-project python
"""Compare wired bridge goodput with scoped, temporary RX steering.

Root creates a separate endpoint namespace on the switch NIC. The direct
endpoint remains in the initial namespace. Both physical ports are witnessed
by hardware counters; no router-terminated iperf process participates.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
BASE = Path("/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8")
NS = "w7bridge-bench"
DEV = "w7bridge0"
DIRECT = "enp4s0f4u2u4"
SWITCH = "enp4s0f4u2u2u4"
DIRECT_IP = "192.168.76.2"
PEER = "192.168.76.252"
MAC = "02:76:07:24:02:52"
PORT = 52228
PATHS = tuple(f"/sys/class/net/{d}/queues/rx-{i}/rps_cpus"
              for d in ("lan", "switch") for i in range(4)) + (
                  "/sys/class/net/lan1/queues/rx-0/rps_cpus",)
POLICIES = {"baseline": ("1",)*8+("0",),
            "native": ("0",)*9,
            "native-posttag": ("0",)*8+("e",)}
COUNTERS = ("rx_bytes_g", "tx_bytes_g", "rx_crc_err", "rx_frag_err",
            "rx_jabber_err", "rx_len_err", "tx_underflow_err")
MODES = {"forward": [], "reverse": ["-R"], "bidir": ["--bidir"]}


def run(argv, **kw):
    return subprocess.run(argv, check=True, text=True, capture_output=True,
                          timeout=kw.pop("timeout", 20), **kw).stdout


def require(ok, message):
    if not ok:
        raise ValueError(message)


def jan_python(code, *args):
    return run(["runuser", "-u", "jan", "--", "/usr/bin/uv", "run",
                "--no-project", "python", "-B", "-c", code, *args],
               cwd=HERE)


def remote(command):
    return jan_python('import runpy,sys; p=runpy.run_path("probe-mib-freshness.py"); print(p["remote"](sys.argv[1]),end="")', command)


def namespace_exists():
    return NS in [line.split()[0] for line in run(["ip", "netns", "list"]).splitlines()]


def rps_state():
    values = tuple(remote("cat " + " ".join(PATHS)).split())
    require(len(values) == len(PATHS) and all(re.fullmatch("[0-9a-f]+", x) for x in values),
            "invalid RPS readback")
    return values


def apply(boot, values):
    require(re.fullmatch("[0-9a-f-]{36}", boot) and len(values)==len(PATHS)
            and all(re.fullmatch("[0-9a-f]+", x) for x in values), "invalid RPS request")
    remote("set -e; test \"$(cat /proc/sys/kernel/random/boot_id)\" = "+boot+"; "+
           "; ".join(f"printf %s {v} > {p}" for p,v in zip(PATHS,values)))
    require(rps_state()==values, "RPS readback mismatch")


@contextmanager
def steering(boot, policy):
    old=rps_state()
    require(old==POLICIES["baseline"], "unexpected starting steering")
    try:
        apply(boot,POLICIES[policy])
        yield
        require(rps_state()==POLICIES[policy], "steering changed during test")
    finally:
        apply(boot,old)


@contextmanager
def endpoint():
    require(not namespace_exists(), "namespace already exists")
    require(not run(["ip","neigh","show","to",PEER,"dev",DIRECT]).strip(),
            "test neighbor already exists")
    require(not Path("/sys/class/net/"+DEV).exists(), "test interface already exists")
    made=False
    link_made=False
    neighbor=False
    try:
        run(["ip","netns","add",NS]); made=True
        run(["ip","link","add","link",SWITCH,"name",DEV,"address",MAC,"type","macvlan","mode","bridge"]); link_made=True
        run(["ip","link","set",DEV,"netns",NS])
        for dev in ("lo",DEV):
            run(["ip","-n",NS,"link","set",dev,"up"])
        run(["ip","netns","exec",NS,"arping","-D","-c","2","-w","4","-I",DEV,PEER])
        run(["ip","-n",NS,"addr","add",PEER+"/24","dev",DEV])
        direct_mac=Path(f"/sys/class/net/{DIRECT}/address").read_text().strip()
        run(["ip","-n",NS,"neigh","add",DIRECT_IP,"lladdr",direct_mac,"dev",DEV,"nud","permanent"])
        run(["ip","neigh","add",PEER,"lladdr",MAC,"dev",DIRECT,"nud","permanent"]); neighbor=True
        require(f"dev {DIRECT} " in run(["ip","route","get",PEER,"from",DIRECT_IP]),
                "wrong direct route")
        run(["ping","-I",DIRECT_IP,"-c","3","-W","2",PEER])
        yield
    finally:
        if neighbor:
            run(["ip","neigh","del",PEER,"dev",DIRECT])
        if made:
            run(["ip","netns","del",NS])
        if link_made and Path("/sys/class/net/"+DEV).exists():
            run(["ip","link","del",DEV])
        require(not namespace_exists() and not Path("/sys/class/net/"+DEV).exists(),
                "namespace cleanup failed")


def snapshot(out, name, boot):
    command=("cat /proc/sys/kernel/random/boot_id; cat /rom/etc/openwrt_version; "
             "echo ===LAN===; ethtool -S lan; echo ===SWITCH===; ethtool -S switch; "
             "echo ===COPPER===; ethtool -S lan1; echo ===CPU===; cat /proc/stat | head -5; "
             "cat /proc/softirqs; echo ===END===; cat /proc/sys/kernel/random/boot_id; "
             "dmesg | grep -c 'NOC ERROR DETECTED' || :")
    raw=remote(command)
    require(raw.splitlines()[0]==boot and raw.split("===END===\n")[1].split()==[boot,"0"],
            "boot changed or NoC fatal")
    (out/(name+".txt")).write_text(raw)
    return raw


def counters(raw, port):
    section=raw.split("==="+port+"===\n")[1].split("===")[0]
    return {k:int(v) for k,v in re.findall(r"^\s+(\w+):\s*(\d+)\s*$",section,re.M)
            if k in COUNTERS}


def cpu(raw):
    return {p[0]:list(map(int,p[1:])) for l in raw.splitlines() if re.match(r"^cpu[0-3] ",l)
            for p in [l.split()]}


def analyze(before,after,payload):
    result={}
    for port in ("LAN","SWITCH"):
        a,b=counters(before,port),counters(after,port)
        require(set(a)==set(b)==set(COUNTERS),"missing MAC counters")
        delta={k:b[k]-a[k] for k in a}
        require(all(v>=0 for v in delta.values()) and not any(delta[k] for k in COUNTERS[2:]),
                "MAC corruption or reset")
        result[port]=delta
    require(result["LAN"]["rx_bytes_g"]>=payload.get("forward",0)
            and result["SWITCH"]["tx_bytes_g"]>=payload.get("forward",0)
            and result["SWITCH"]["rx_bytes_g"]>=payload.get("reverse",0)
            and result["LAN"]["tx_bytes_g"]>=payload.get("reverse",0),"hardware bytes below delivered payload")
    loads={}
    a,b=cpu(before),cpu(after)
    for k in a:
        d=[y-x for x,y in zip(a[k],b[k])]
        loads[k]={"busy_pct":100*(sum(d[:8])-d[3]-d[4])/max(1,sum(d[:8])),
                  "softirq_pct":100*d[6]/max(1,sum(d[:8]))}
    return {"mac_delta":result,"cpu":loads}


def case(out,boot,policy,streams,mode,pace):
    name=f"{policy}-p{streams}-{mode}-{pace}"
    before=snapshot(out,name+"-before",boot)
    with (out/(name+"-server.json")).open("x") as stdout:
        server=subprocess.Popen(["ip","netns","exec",NS,"timeout","30","iperf3","-s","-1","-B",PEER,
                                 "-p",str(PORT),"-J"],stdout=stdout)
        try:
            time.sleep(.4)
            flags=MODES[mode]+(["-b",str(pace*1_000_000//streams)] if pace else [])
            data=run(["iperf3","-c",PEER,"-B",DIRECT_IP,"--bind-dev",DIRECT,"-p",str(PORT),
                      "-t","12","-P",str(streams),"--connect-timeout","4000","-J",*flags],timeout=25)
            (out/(name+"-client.json")).write_text(data)
            require(server.wait(timeout=8)==0,"server failed")
        finally:
            if server.poll() is None:
                server.terminate()
                server.wait(timeout=5)
    after=snapshot(out,name+"-after",boot)
    r=json.loads(data)["end"]
    rows={"reverse" if mode=="reverse" else "forward":r["sum_received"]}
    if mode=="bidir":
        rows["reverse"]=r["sum_received_bidir_reverse"]
    payload={k:v["bytes"] for k,v in rows.items()}
    result={"case":name,"goodput_mbps":{k:v["bits_per_second"]/1e6 for k,v in rows.items()},
            "payload":payload,**analyze(before,after,payload)}
    print(json.dumps(result),flush=True)
    return result


def replay(out):
    run(["sha256sum","-c","--status","SHA256SUMS"],cwd=out)
    report=json.loads((out/"report.json").read_text())
    require(report["status"]=="PASS","cannot replay incomplete cohort")
    for row in report["cases"]:
        name=row["case"]
        before=(out/(name+"-before.txt")).read_text()
        after=(out/(name+"-after.txt")).read_text()
        require(before.splitlines()[0]==after.splitlines()[0]==report["boot"],
                "replay boot mismatch")
        data=analyze(before,after,row["payload"])
        require(data["mac_delta"]==row["mac_delta"] and data["cpu"]==row["cpu"],
                "replay mismatch")
    print(f"REPLAY_PASS cases={len(report['cases'])}")


def main():
    import sys
    if len(sys.argv)==3 and sys.argv[1]=="--replay":
        replay(Path(sys.argv[2]).resolve(strict=True))
        return
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("run",type=Path)
    p.add_argument("label")
    p.add_argument("--policy",choices=POLICIES,action="append",required=True)
    args=p.parse_args()
    require(os.getuid()==0,"run on Asus as root")
    # Interrupt the bounded benchmark, not its cleanup. A second signal
    # after this one retains the normal process-exit behavior.
    def interrupted(signum, _frame):
        signal.signal(signum, signal.SIG_IGN)
        raise InterruptedError(f"received signal {signum}")
    for signum in (signal.SIGHUP,signal.SIGTERM,signal.SIGINT):
        signal.signal(signum,interrupted)
    require(re.fullmatch(r"[a-zA-Z0-9-]+",args.label),"invalid label")
    run_dir=args.run.resolve(strict=True)
    require(run_dir.is_relative_to(BASE),"run outside lab")
    record=json.loads(jan_python('import runpy,sys,json; p=runpy.run_path("report-ordering-cohort.py"); print(json.dumps(p["load_run"](__import__("pathlib").Path(sys.argv[1]))))',str(run_dir)))
    require(record["outcome"]=="clean" and record["direct_mbps"]==2500 and record["switch_mbps"]==1000,
            "source not sealed clean matched lab")
    boot=record["boot"]
    for dev,speed in ((DIRECT,2500),(SWITCH,1000)):
        require(int(Path(f"/sys/class/net/{dev}/speed").read_text())==speed,"wrong link speed")
    with (BASE/".lab-control.lock").open("r+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        out=run_dir/("bridge-throughput-"+args.label)
        out.mkdir(mode=0o700)
        report={"boot":boot,"policies":args.policy,"cases":[],"status":"RUNNING",
                "source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        try:
            with endpoint():
                for policy in args.policy:
                    with steering(boot,policy):
                        for streams,mode,pace in ((4,"forward",0),(4,"reverse",0),(4,"bidir",0),
                                                  (4,"bidir",800),(4,"bidir",900)):
                            report["cases"].append(case(out,boot,policy,streams,mode,pace))
            report["status"]="PASS"
        except BaseException as exc:
            report.update(status="FAILED",error=str(exc))
            raise
        finally:
            (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
            (out/"SHA256SUMS").write_text("".join(
                f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n" for f in sorted(out.iterdir()) if f.is_file()))
            subprocess.run(["chown","-R","jan:jan",str(out)],check=True)


if __name__=="__main__":
    main()
