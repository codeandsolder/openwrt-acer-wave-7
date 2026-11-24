#!/usr/bin/env -S uv run --no-project python
"""Compare MLO bridge goodput, latency, CPU and radio backlog."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

spec=importlib.util.spec_from_file_location("bridge_bench",Path(__file__).resolve().with_name("bench-bridge.py"))
b=importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
WIFI_RPS="/sys/class/net/ap-mld0/queues/rx-0/rps_cpus"
POLICIES={"baseline":("baseline","0"),"native":("native","0"),"distributed":("native","e"),"irq-distributed":("native","e")}
PEER="192.168.76.248"
PORT=52229


@contextmanager
def radio_irq_affinity(boot,policy):
    if policy!="irq-distributed":
        yield
        return
    with b.irq_affinity(boot,r"pci2_wlan_dp_(\d+)",range(12),lambda group:1+group%3):
        yield


@contextmanager
def steering(boot,policy):
    wired,wifi=POLICIES[policy]
    old=b.remote("cat "+WIFI_RPS).strip()
    b.require(old=="0","unexpected Wi-Fi RPS starting state")
    def apply(value):
        b.remote(f'test "$(cat /proc/sys/kernel/random/boot_id)" = {boot} && printf %s {value} > {WIFI_RPS}')
        b.require(b.remote("cat "+WIFI_RPS).strip()==value,"Wi-Fi RPS readback mismatch")
    with b.steering(boot,wired):
        try:
            apply(wifi)
            with radio_irq_affinity(boot,policy):
                yield
        finally:
            apply(old)


def wait_radio(boot,width,timeout,station=False):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        raw=b.remote("cat /proc/sys/kernel/random/boot_id; iw dev ap-mld0 info; iw dev ap-mld0 station dump")
        b.require(raw.splitlines()[0]==boot,"boot changed during radio setup")
        if (re.search(r"channel \d+ \(5\d+ MHz\), width: "+str(width)+r" MHz,",raw)
                and re.search(r"link ID\s+1\b",raw,re.I) and re.search(r"link ID\s+0\b",raw,re.I)
                and (not station or "Station " in raw)):
            try:
                h=json.loads(b.remote("ubus call hostapd.ap-mld0 get_status"))
                w=json.loads(b.remote("ubus call network.wireless status"))["radio1"]
            except (ValueError, KeyError, subprocess.CalledProcessError):
                time.sleep(2)
                continue
            if (h.get("status")=="ENABLED" and not h.get("dfs",{}).get("cac_active",True)
                    and w.get("up") and not w.get("pending")):
                return raw+"\n"+json.dumps({"hostapd":h,"radio1_up":w.get("up"),"radio1_pending":w.get("pending")})+"\n"
        time.sleep(2)
    raise TimeoutError(f"radio did not reach {width} MHz, station={station}")


@contextmanager
def radio_width(out,boot,width):
    if width==80:
        yield
        return
    initial=b.remote("cat /proc/sys/kernel/random/boot_id; uci get wireless.radio1.country; "
                     "uci get wireless.radio1.channel; uci get wireless.radio1.htmode; "
                     "uci changes wireless; iw dev ap-mld0 station dump")
    b.require(initial.splitlines()==[boot,"PL","36","EHT80"],
              "temporary width test requires idle channel-36 PL EHT80 lab AP and no UCI changes")
    (out/"radio-config-before.txt").write_text(initial)
    wait_radio(boot,80,15)
    try:
        b.remote(f'test "$(cat /proc/sys/kernel/random/boot_id)" = {boot} && '
                 'uci set wireless.radio1.htmode=EHT160 && wifi reload')
        ready=wait_radio(boot,160,180)
        (out/"radio-width-ready.txt").write_text(ready)
        print("EHT160_READY",flush=True)
        # No client before the regulatory CAC has completed. The operator
        # starts the independent wired-managed endpoint after this marker.
        (out/"radio-client-ready.txt").write_text(wait_radio(boot,160,100,station=True))
        yield
    finally:
        b.remote(f'test "$(cat /proc/sys/kernel/random/boot_id)" = {boot} && '
                 'uci revert wireless.radio1.htmode && wifi reload')
        (out/"radio-config-restored.txt").write_text(wait_radio(boot,80,120))
        b.require(b.remote("uci changes wireless").strip()=="","wireless changes remain")


def radio_snapshot(out,name,boot,width):
    raw=b.remote(
        "cat /proc/sys/kernel/random/boot_id; iw dev ap-mld0 info; "
        "iw dev ap-mld0 station dump; cat /proc/stat | head -5; cat /proc/softirqs; "
        "cat /proc/interrupts; for f in /sys/kernel/debug/ath12k/*/device_dp_stats; do "
        "echo ==== $f; cat $f; done; cat /sys/kernel/debug/ieee80211/phy0/aql_pending; "
        "cat /proc/sys/kernel/random/boot_id; dmesg | grep -c 'NOC ERROR DETECTED' || :")
    (out/(name+".txt")).write_text(raw)
    b.require(raw.splitlines()[0]==boot and raw.splitlines()[-2:]==[boot,"0"],"boot or NoC changed")
    b.require(re.search(r"channel \d+ \(5\d+ MHz\), width: "+str(width)+r" MHz,",raw),"unexpected AP width")
    b.require("Station " in raw,"no associated station")
    return raw


def case(out,boot,width,policy,mode,pace):
    name=f"{policy}-{mode}-{pace}"
    before=b.snapshot(out,name+"-before",boot)
    radio_snapshot(out,name+"-radio-before",boot,width)
    with (out/(name+"-client.json")).open("x") as stdout,(out/(name+"-client.err")).open("x") as err,(out/(name+"-ping.txt")).open("x") as pingout:
        args=["iperf3","-c",PEER,"-B",b.DIRECT_IP,"--bind-dev",b.DIRECT,"-p",str(PORT),
              "-t","12","-P","4","--connect-timeout","4000","-J",*b.MODES[mode]]
        if pace:
            args+=["-b",str(pace*250000)]
        proc=subprocess.Popen(args,stdout=stdout,stderr=err)
        ping=subprocess.Popen(["ping","-I",b.DIRECT_IP,"-i",".1","-c","120","-W","1",PEER],stdout=pingout)
        try:
            deadline=time.monotonic()+25
            idx=0
            while proc.poll() is None:
                b.require(time.monotonic()<deadline,"iperf timeout")
                radio_snapshot(out,f"{name}-sample-{idx:02}",boot,width)
                idx+=1
                time.sleep(.7)
            b.require(proc.returncode==0,"iperf failed")
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
            if ping.poll() is None:
                ping.send_signal(signal.SIGINT)
                ping.wait(timeout=5)
    after=b.snapshot(out,name+"-after",boot)
    radio_snapshot(out,name+"-radio-after",boot,width)
    raw=json.loads((out/(name+"-client.json")).read_text())
    row=raw["end"]["sum_received"]
    result=b.analyze(before,after,{})
    direct=result["mac_delta"]["LAN"]
    b.require(direct["rx_bytes_g" if mode=="forward" else "tx_bytes_g"]>=row["bytes"],"no wired payload witness")
    rtt=(out/(name+"-ping.txt")).read_text()
    pending=[int(x) for p in out.glob(name+"-sample-*.txt") for x in re.findall(r"radio0 tx_pending: (\d+)",p.read_text().split("==== /sys/kernel/debug/ath12k/ahb-soc@0:wifi/device_dp_stats")[-1])]
    summary={"case":name,"receiver_mbps":row["bits_per_second"]/1e6,"bytes":row["bytes"],
             "cpu":result["cpu"],"mac_delta":result["mac_delta"],"radio_pending_peak":max(pending,default=0),
             "ping_summary":rtt.splitlines()[-2:]}
    print(json.dumps(summary),flush=True)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("run",type=Path)
    p.add_argument("label")
    p.add_argument("--width",type=int,choices=(80,160),default=80)
    p.add_argument("--policy",choices=POLICIES,action="append",required=True)
    p.add_argument("--case",nargs=2,action="append",metavar=("MODE","MBPS"),required=True)
    args=p.parse_args()
    specs=[(mode,int(pace)) for mode,pace in args.case]
    b.require(os.getuid()==0 and args.label.isalnum() and all(mode in ("forward","reverse") and 0<=pace<=2500 for mode,pace in specs),"invalid arguments")
    b.require(len(args.policy)==len(set(args.policy)) and len(specs)==len(set(specs)),"duplicate cases")
    run_dir=args.run.resolve(strict=True)
    b.require(run_dir.is_relative_to(b.BASE),"outside lab")
    record=json.loads(b.jan_python('import runpy,sys,json; p=runpy.run_path("report-ordering-cohort.py"); print(json.dumps(p["load_run"](__import__("pathlib").Path(sys.argv[1]))))',str(run_dir)))
    b.require(record["outcome"]=="clean" and record["variant"]=="edma-tx-queue","wrong candidate")
    boot=record["boot"]
    b.require(int(Path(f"/sys/class/net/{b.DIRECT}/speed").read_text())==2500,"wrong direct link")
    def interrupted(signum,_):
        signal.signal(signum,signal.SIG_IGN)
        raise InterruptedError(f"signal {signum}")
    for signum in (signal.SIGHUP,signal.SIGTERM,signal.SIGINT):
        signal.signal(signum,interrupted)
    with (b.BASE/".lab-control.lock").open("r+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        out=run_dir/("wifi-bridge-"+args.label)
        out.mkdir(mode=0o700)
        report={"boot":boot,"width_mhz":args.width,"cases":[],"status":"RUNNING"}
        try:
            b.require(f"dev {b.DIRECT} " in b.run(["ip","route","get",PEER,"from",b.DIRECT_IP]),"wrong route")
            with radio_width(out,boot,args.width):
                for policy in args.policy:
                    with steering(boot,policy):
                        for mode,pace in specs:
                            report["cases"].append(case(out,boot,args.width,policy,mode,pace))
            report["status"]="PASS"
        except BaseException as exc:
            report.update(status="FAILED",error=str(exc))
            raise
        finally:
            (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
            (out/"SHA256SUMS").write_text("".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n" for f in sorted(out.iterdir()) if f.is_file()))
            subprocess.run(["chown","-R","jan:jan",str(out)],check=True)


if __name__=="__main__":
    main()
