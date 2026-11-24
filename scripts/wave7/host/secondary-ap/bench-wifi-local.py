#!/usr/bin/env -S uv run --no-project python
"""Matched local/bridge Wi-Fi TCP measurements on one association."""
import argparse
from contextlib import contextmanager, nullcontext
import re
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import time

w=runpy.run_path(str(Path(__file__).with_name("bench-wifi-bridge.py")))
b=w["b"]
@contextmanager
def standalone(out,boot,enabled,channel,width):
    if not enabled:
        yield "ap-mld0"
        return
    initial=b.remote("cat /proc/sys/kernel/random/boot_id; "
                     "uci get wireless.radio1.channel; uci get wireless.radio1.htmode; uci get wireless.radio1.country; "
                     "uci get wireless.wave7_mlo_lab.device; uci get wireless.wave7_mlo_lab.mlo; "
                     "uci get wireless.wave7_mlo_lab.ssid; uci changes wireless; iw dev ap-mld0 station dump")
    b.require(initial.splitlines()==[boot,"36","EHT80","PL","radio0 radio1","1","Wave7-MLO-Lab"],
              "requires idle exact MLO baseline")
    (out/"radio-before.txt").write_text(initial)
    try:
        b.remote(f'test "$(cat /proc/sys/kernel/random/boot_id)" = {boot} && '
                 f'uci set wireless.radio1.channel={channel} && uci set wireless.radio1.htmode=EHT{width} && '
                 'uci set wireless.wave7_mlo_lab.device=radio1 && '
                 'uci delete wireless.wave7_mlo_lab.mlo && '
                 'uci set wireless.wave7_mlo_lab.ssid=Wave7-5G-Lab && wifi reload')
        deadline=time.monotonic()+(720 if width==160 and channel==100 else 150)
        iface=None
        while time.monotonic()<deadline:
            raw=b.remote("iw dev")
            matches=re.findall(r"Interface ([a-zA-Z0-9_.-]+)",raw)
            if len(matches)==1 and "ssid Wave7-5G-Lab" in raw and f"channel {channel} ({5000+5*channel} MHz), width: {width} MHz" in raw and "MLD with links:" not in raw:
                candidate=matches[0]
                try:
                    status=json.loads(b.remote(f"ubus call hostapd.{candidate} get_status"))
                    if status.get("status")=="ENABLED" and not status.get("dfs",{}).get("cac_active",False):
                        iface=candidate
                        break
                except (ValueError,subprocess.CalledProcessError):
                    pass
            time.sleep(1)
        b.require(iface,"standalone AP did not become ready")
        (out/"standalone-ready.txt").write_text(raw)
        deadline=time.monotonic()+110
        marker=out/"endpoint-ready.txt"
        while not marker.is_file() and time.monotonic()<deadline:
            time.sleep(1)
        b.require(marker.is_file() and marker.read_text().strip()==w["PEER"],"client not ready")
        yield iface
    finally:
        b.remote(f'test "$(cat /proc/sys/kernel/random/boot_id)" = {boot} && '
                 'uci revert wireless.wave7_mlo_lab && uci revert wireless.radio1 && wifi reload')
        (out/"radio-restored.txt").write_text(w["wait_radio"](boot,80,120))
        b.require(b.remote("uci changes wireless").strip()=="","wireless changes remain")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("run",type=Path)
    p.add_argument("label")
    p.add_argument("--policy",choices=w["POLICIES"],default="baseline")
    p.add_argument("--local-only",action="store_true")
    p.add_argument("--standalone",action="store_true")
    p.add_argument("--channel",type=int,choices=(36,100),default=36)
    p.add_argument("--width",type=int,choices=(80,160),default=80)
    args=p.parse_args()
    b.require(args.standalone or (args.channel,args.width)==(36,80),"nonbaseline width requires standalone")
    b.require(not args.standalone or (args.local_only and args.policy=="baseline"),"standalone baseline only")
    b.require(os.getuid()==0 and args.label.isalnum(),"invalid invocation")
    run=args.run.resolve(strict=True)
    b.require(run.is_relative_to(b.BASE),"outside lab")
    record=json.loads(b.jan_python('import runpy,sys,json; p=runpy.run_path("report-ordering-cohort.py"); print(json.dumps(p["load_run"](__import__("pathlib").Path(sys.argv[1]))))',str(run)))
    b.require(record["variant"]=="edma-tx-queue" and record["outcome"]=="clean","wrong source")
    boot=record["boot"]
    runtime=Path("/home/jan/firmware/wave7/trials/20261115-deferred-regression/iperf-runtime")
    remote_dir="/tmp/wave7-wifi-local-"+args.label
    opts=["-i","/home/jan/.ssh/wave7-root-rsa","-o","BindInterface="+b.SWITCH,"-o","BindAddress=192.168.76.250","-o","BatchMode=yes","-o","IdentitiesOnly=yes","-o","StrictHostKeyChecking=yes","-o","UserKnownHostsFile="+str(b.BASE/"known_hosts"),"-o","ConnectTimeout=4"]
    def interrupt(signum,_):
        signal.signal(signum,signal.SIG_IGN)
        raise InterruptedError(f"signal {signum}")
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):
        signal.signal(sig,interrupt)
    with (b.BASE/".lab-control.lock").open("r+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        out=run/("wifi-local-"+args.label)
        out.mkdir(mode=0o700)
        report={"boot":boot,"policy":args.policy,"standalone":args.standalone,"channel":args.channel,"width":args.width,"cases":[],"status":"RUNNING"}
        created=False
        try:
            b.require(b.remote("cat /proc/sys/kernel/random/boot_id").strip()==boot,"wrong boot")
            b.run(["sha256sum","-c",str(runtime/"sha256sums")])
            b.remote(f"mkdir -m 700 {remote_dir}")
            created=True
            for f in ("iperf3","libiperf.so.0","libatomic.so.1"):
                b.run(["runuser","-u","jan","--","scp","-q","-O",*opts,str(runtime/f),"root@192.168.76.1:"+remote_dir+"/"],timeout=15)
                b.require(b.remote(f"sha256sum {remote_dir}/{f}").split()[0]==hashlib.sha256((runtime/f).read_bytes()).hexdigest(),"runtime digest mismatch")
            (out/"runtime-version.txt").write_text(b.remote(f"LD_LIBRARY_PATH={remote_dir} {remote_dir}/iperf3 --version"))
            (out/"route.txt").write_text(b.remote("ip route get 192.168.76.248 from 192.168.76.1; bridge fdb show 2>/dev/null || :; iw dev ap-mld0 survey dump"))
            cases=(("local","reverse"),("local","forward")) if args.local_only else (("local","reverse"),("bridge","reverse"),("local","forward"),("bridge","forward"),("local","reverse"),("local","forward"))
            with standalone(out,boot,args.standalone,args.channel,args.width) as iface, (nullcontext() if args.standalone else w["steering"](boot,args.policy)):
                for i,(path,mode) in enumerate(cases):
                    name=f"{i}-{path}-{mode}"
                    before=b.snapshot(out,name+"-before",boot)
                    w["radio_snapshot"](out,name+"-radio-before",boot,args.width,iface)
                    flags=["-R"] if mode=="reverse" else []
                    if path=="local":
                        cmd=f"timeout 22 env LD_LIBRARY_PATH={remote_dir} {remote_dir}/iperf3 -c 192.168.76.248 -B 192.168.76.1 -p 52229 -P 4 -t 12 --connect-timeout 4000 -J "+" ".join(flags)
                        argv=["runuser","-u","jan","--","ssh","-nT",*opts,"root@192.168.76.1",cmd]
                    else:
                        argv=["iperf3","-c",w["PEER"],"-B",b.DIRECT_IP,"--bind-dev",b.DIRECT,"-p","52229","-P","4","-t","12","--connect-timeout","4000","-J",*flags]
                    with (out/(name+".json")).open("x") as f,(out/(name+".err")).open("x") as e:
                        child=subprocess.Popen(argv,stdout=f,stderr=e)
                        try:
                            idx=0
                            deadline=time.monotonic()+28
                            while child.poll() is None:
                                b.require(time.monotonic()<deadline,"iperf timeout")
                                w["radio_snapshot"](out,f"{name}-sample-{idx:02}",boot,args.width,iface)
                                idx+=1
                                time.sleep(0.8)
                            b.require(child.returncode==0,"iperf failed")
                        finally:
                            if child.poll() is None:
                                child.terminate()
                                child.wait(timeout=5)
                    after=b.snapshot(out,name+"-after",boot)
                    w["radio_snapshot"](out,name+"-radio-after",boot,args.width,iface)
                    r=json.loads((out/(name+".json")).read_text())
                    row=r["end"]["sum_received"]
                    result=b.analyze(before,after,{})
                    wired=result["mac_delta"]["LAN"]["rx_bytes_g" if mode=="forward" else "tx_bytes_g"]
                    b.require(wired>=row["bytes"] if path=="bridge" else wired<row["bytes"]//20,"wrong physical path")
                    item={"case":name,"mbps":row["bits_per_second"]/1e6,"bytes":row["bytes"],"retransmits":r["end"]["sum_sent"].get("retransmits"),"wired_bytes":wired,"cpu":result["cpu"]}
                    print(json.dumps(item),flush=True)
                    report["cases"].append(item)
            report["status"]="PASS"
        except BaseException as exc:
            report.update(status="FAILED",error=str(exc))
            raise
        finally:
            try:
                if created:
                    b.remote(f'test "$(cat /proc/sys/kernel/random/boot_id)" = {boot} && rm -f {remote_dir}/iperf3 {remote_dir}/libiperf.so.0 {remote_dir}/libatomic.so.1 && rmdir {remote_dir}')
            finally:
                (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
                (out/"SHA256SUMS").write_text("".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n" for f in sorted(out.iterdir()) if f.is_file()))
                subprocess.run(["chown","-R","jan:jan",str(out)],check=True)

if __name__=="__main__":
    main()
