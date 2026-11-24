#!/usr/bin/env -S uv run --no-project python
"""Matched local/bridge Wi-Fi TCP measurements on one association."""
import argparse
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
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("run",type=Path)
    p.add_argument("label")
    args=p.parse_args()
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
        report={"boot":boot,"cases":[],"status":"RUNNING"}
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
            for i,(path,mode) in enumerate((("local","reverse"),("bridge","reverse"),("local","forward"),("bridge","forward"),("local","reverse"),("local","forward"))):
                name=f"{i}-{path}-{mode}"
                before=b.snapshot(out,name+"-before",boot)
                w["radio_snapshot"](out,name+"-radio-before",boot,80)
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
                            w["radio_snapshot"](out,f"{name}-sample-{idx:02}",boot,80)
                            idx+=1
                            time.sleep(0.8)
                        b.require(child.returncode==0,"iperf failed")
                    finally:
                        if child.poll() is None:
                            child.terminate()
                            child.wait(timeout=5)
                after=b.snapshot(out,name+"-after",boot)
                w["radio_snapshot"](out,name+"-radio-after",boot,80)
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
