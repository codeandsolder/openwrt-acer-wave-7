#!/usr/bin/env -S uv run --no-project python
"""Prove forward progress after nonzero EDMA ring exhaustion on CPU0 IRQs."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess

spec = importlib.util.spec_from_file_location("bridge_bench", Path(__file__).resolve().with_name("bench-bridge.py"))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


def rings(out, label, boot):
    raw = b.remote(
        "cat /proc/sys/kernel/random/boot_id; "
        "cat /sys/kernel/debug/ppe/edma/stats/tx_ring_stats; "
        "cat /sys/kernel/debug/ppe/edma/stats/err_stats; "
        "cat /proc/interrupts; "
        "for i in $(awk '/edma_txcmpl|edma-txcmpl|txcmpl/ {gsub(\":\",\"\",$1);print $1}' /proc/interrupts); do "
        "echo affinity_$i=$(cat /proc/irq/$i/effective_affinity_list); done; "
        "cat /proc/sys/kernel/random/boot_id")
    b.require(raw.splitlines()[0] == raw.splitlines()[-1] == boot, "mixed ring snapshot")
    (out / (label + "-rings.txt")).write_text(raw)
    counts = {int(i):int(n) for i,n in re.findall(r"txdesc\[(\d+)\]:no_desc_avail\s*=\s*(\d+)",raw)}
    b.require(set(range(4,12)) <= counts.keys(), "missing active ring counters")
    return counts


def stop_counts(path):
    raw = path.read_text().split("===SWITCH===\n")[1].split("===")[0]
    counts = {int(i):int(n) for i,n in re.findall(r"tx_queue_stopped_cpu(\d+):\s*(\d+)",raw)}
    b.require(counts.keys() == set(range(4)), "missing queue stop counters")
    return counts


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("run",type=Path)
    p.add_argument("label")
    args=p.parse_args()
    b.require(os.getuid()==0 and args.label.isalnum(),"invalid root invocation")
    run_dir=args.run.resolve(strict=True)
    b.require(run_dir.is_relative_to(b.BASE),"outside lab")
    record=json.loads(b.jan_python('import runpy,sys,json; p=runpy.run_path("report-ordering-cohort.py"); print(json.dumps(p["load_run"](__import__("pathlib").Path(sys.argv[1]))))',str(run_dir)))
    b.require(record["variant"]=="edma-tx-queue" and record["outcome"]=="clean" and record["direct_mbps"]==2500 and record["switch_mbps"]==1000,"wrong candidate")
    boot=record["boot"]
    for dev,speed in ((b.DIRECT,2500),(b.SWITCH,1000)):
        b.require(int(Path(f"/sys/class/net/{dev}/speed").read_text())==speed,"wrong link speed")
    for core in range(1,4):
        b.POLICIES[f"cpu{core}"]=(format(1<<core,"x"),)*8+("0",)
    def interrupted(signum,_):
        signal.signal(signum,signal.SIG_IGN)
        raise InterruptedError(f"signal {signum}")
    for signum in (signal.SIGHUP,signal.SIGTERM,signal.SIGINT):
        signal.signal(signum,interrupted)
    with (b.BASE/".lab-control.lock").open("r+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        out=run_dir/("queue-qualification-"+args.label)
        out.mkdir(mode=0o700)
        report={"boot":boot,"cores":[],"status":"RUNNING"}
        try:
            for core in range(1,4):
                policy=f"cpu{core}"
                b.PEER=f"192.168.76.{230+core}"
                b.MAC=f"02:76:07:24:04:{230+core:02x}"
                b.PORT=52400+core
                with b.endpoint(),b.steering(boot,policy):
                    before=rings(out,policy+"-before",boot)
                    try:
                        load=b.case(out,boot,policy,8,"forward",0)
                    finally:
                        after=rings(out,policy+"-after",boot)
                    stop_before=stop_counts(out/(load["case"]+"-before.txt"))
                    stop_after=stop_counts(out/(load["case"]+"-after.txt"))
                    delta={i:after[i]-v for i,v in before.items()}
                    stops={i:stop_after[i]-v for i,v in stop_before.items()}
                    b.require(all(v>=0 for v in (*delta.values(),*stops.values())),"counter reset")
                    # The post-stress connections still run on the same core,
                    # without resetting or changing its TX rings or IRQs.
                    follow=b.case(out,boot,policy,4,"bidir",400)
                    row={"core":core,"load":load,"follow":follow,
                         "ring_delta":delta,"stop_delta":stops,
                         "exercised":delta[4+core]>0 and stops[core]>0}
                    report["cores"].append(row)
                    print(json.dumps({"core":core,"ring_delta":delta,"stop_delta":stops,
                                      "exercised":row["exercised"]}),flush=True)
            report["status"]="PASS" if all(r["exercised"] for r in report["cores"]) else "INCONCLUSIVE"
        except BaseException as exc:
            report.update(status="FAILED",error=str(exc))
            raise
        finally:
            (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
            (out/"SHA256SUMS").write_text("".join(
                f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n"
                for f in sorted(out.iterdir()) if f.is_file()))
            subprocess.run(["chown","-R","jan:jan",str(out)],check=True)
    print("QUALIFICATION_"+report["status"])


if __name__=="__main__":
    main()
