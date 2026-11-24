#!/usr/bin/env -S uv run --no-project python
"""Witness TCP connection setup across both physical Ethernet links.

Use fresh endpoint addresses and TCP ports for every policy. Capture only
handshakes/teardown and counters, never bulk payload. Failed cases are
observations, not a reason to skip the paired control.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bridge_bench", HERE/"bench-bridge.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


@contextmanager
def capture(out, name):
    jobs = []
    try:
        for label, dev, prefix in (("direct", b.DIRECT, []),
                                    ("switch", b.SWITCH, []),
                                    ("endpoint", b.DEV, ["ip", "netns", "exec", b.NS])):
            with (out/f"{name}-{label}.err").open("x") as err:
                proc = subprocess.Popen(prefix+["tcpdump", "-p", "-n", "-U", "-i", dev,
                    "-s", "96", "-w", str(out/f"{name}-{label}.pcap"), "tcp", "and",
                    "host", b.PEER, "and", "port", str(b.PORT), "and",
                    "tcp[13] & 7 != 0"], stderr=err)
            jobs.append(proc)
        deadline=time.monotonic()+3
        while not all((out/f"{name}-{label}.pcap").exists() for label in ("direct","switch","endpoint")):
            b.require(time.monotonic()<deadline and all(p.poll() is None for p in jobs),
                      "capture readiness failed")
            time.sleep(.1)
        yield
    finally:
        for p in jobs:
            if p.poll() is None:
                p.send_signal(signal.SIGINT)
            p.wait(timeout=5)


def trial(out, name, boot, mode):
    before=b.snapshot(out,name+"-before",boot)
    result={"case":name,"peer":b.PEER,"port":b.PORT,"mode":mode}
    with capture(out,name):
        with (out/f"{name}-server.json").open("x") as stdout, (out/f"{name}-server.err").open("x") as stderr:
            server=subprocess.Popen(["ip","netns","exec",b.NS,"timeout","24","iperf3","-s","-1",
                                     "-B",b.PEER,"-p",str(b.PORT),"-J"],stdout=stdout,stderr=stderr)
            try:
                time.sleep(.4)
                with (out/f"{name}-client.json").open("x") as co, (out/f"{name}-client.err").open("x") as ce:
                    client=subprocess.Popen(["iperf3","-c",b.PEER,"-B",b.DIRECT_IP,"--bind-dev",b.DIRECT,
                                             "-p",str(b.PORT),"-t","5","-P","4","-b","100000000",
                                             "--connect-timeout","3000","-J",*b.MODES[mode]],stdout=co,stderr=ce)
                    try:
                        result["client_exit"]=client.wait(timeout=16)
                    except subprocess.TimeoutExpired:
                        result["client_timeout"]=True
                        client.send_signal(signal.SIGINT)
                        try:
                            client.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            client.kill()
                            client.wait(timeout=3)
                try:
                    result["server_exit"]=server.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    server.terminate()
                    server.wait(timeout=5)
                    result["server_timeout"]=True
            finally:
                if server.poll() is None:
                    server.terminate()
                    server.wait(timeout=5)
    after=b.snapshot(out,name+"-after",boot)
    result["mac_delta"]=b.analyze(before,after,{})["mac_delta"]
    for side in ("client","server"):
        try:
            raw=json.loads((out/f"{name}-{side}.json").read_text())
            result[side]={"error":raw.get("error"),"connections":len(raw.get("start",{}).get("connected",[])),
                          "intervals":len(raw.get("intervals",[])),
                          "received":{k:v["bits_per_second"]/1e6 for k,v in raw.get("end",{}).items()
                                      if k in ("sum_received","sum_received_bidir_reverse")}}
        except (ValueError,KeyError) as exc:
            result[side]={"parse_error":str(exc)}
    for label in ("direct","switch","endpoint"):
        raw=b.run(["tcpdump","-n","-tt","-r",str(out/f"{name}-{label}.pcap")])
        (out/f"{name}-{label}.txt").write_text(raw)
    print(json.dumps(result),flush=True)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("run",type=Path)
    p.add_argument("label")
    args=p.parse_args()
    b.require(os.getuid()==0,"run on Asus as root")
    b.require(args.label.isalnum(),"invalid label")
    run_dir=args.run.resolve(strict=True)
    b.require(run_dir.is_relative_to(b.BASE),"run outside lab")
    record=json.loads(b.jan_python('import runpy,sys,json; p=runpy.run_path("report-ordering-cohort.py"); print(json.dumps(p["load_run"](__import__("pathlib").Path(sys.argv[1]))))',str(run_dir)))
    b.require(record["outcome"]=="clean" and record["direct_mbps"]==2500 and record["switch_mbps"]==1000,"wrong source")
    boot=record["boot"]
    for dev,speed in ((b.DIRECT,2500),(b.SWITCH,1000)):
        b.require(int(Path(f"/sys/class/net/{dev}/speed").read_text())==speed,"wrong speed")
    def interrupt(signum, _):
        signal.signal(signum,signal.SIG_IGN)
        raise InterruptedError(f"signal {signum}")
    for signum in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):
        signal.signal(signum,interrupt)
    with (b.BASE/".lab-control.lock").open("r+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        out=run_dir/("bridge-setup-"+args.label)
        out.mkdir(mode=0o700)
        report={"boot":boot,"cases":[]}
        try:
            for i,policy in enumerate(("baseline","native","native-posttag","baseline")):
                b.PEER=f"192.168.76.{240+i}"
                b.MAC=f"02:76:07:24:03:{240+i:02x}"
                with b.endpoint(), b.steering(boot,policy):
                    for j,mode in enumerate(("reverse","bidir")):
                        b.PORT=52300+2*i+j
                        report["cases"].append(trial(out,f"{i}-{policy}-{mode}",boot,mode))
            report["status"]="COMPLETE"
        except BaseException as exc:
            report.update(status="FAILED",error=str(exc))
            raise
        finally:
            (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
            (out/"SHA256SUMS").write_text("".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n"
                                                   for f in sorted(out.iterdir()) if f.is_file()))
            subprocess.run(["chown","-R","jan:jan",str(out)],check=True)


if __name__=="__main__":
    main()
