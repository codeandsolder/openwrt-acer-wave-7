#!/usr/bin/env python3
"""Read-only, time-bracketed AP peer statistics for the dedicated Wyse lab client."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time

BASE=Path("/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8")
BOOT="195982f4-b227-4cd1-85e7-31f843cacd49"
REVISION="r0+38346-f9aa3e1fa3-ap-dhcp-guard8"
PEER="28:2e:89:bb:b9:8a"
# The remote observer does not change any control, capture traffic, or read keys.
REMOTE=r"""
set -eu
peer=28:2e:89:bb:b9:8a
p=/sys/kernel/debug/ieee80211/phy0/netdev:ap-mld0/stations/$peer
printf 'READY %s %s\n' "$(cat /proc/sys/kernel/random/boot_id)" "$(cat /etc/openwrt_version)"
while IFS= read -r seq; do
    case "$seq" in *[!0-9]*|'') exit 2;; esac
    printf 'BEGIN %s ' "$seq"
    cat /proc/uptime
    if [ -d "$p" ]; then
        iw dev ap-mld0 station get "$peer" 2>/dev/null || echo NO_STATION
        for name in flags num_ps_buf_frames driver_buffered_tids tx_filtered; do
            if [ -r "$p/$name" ]; then
                printf 'FIELD %s\n' "$name"
                cat "$p/$name"
            fi
        done
        for link in 0 1; do
            for name in rx_duplicates rx_fragments; do
                if [ -r "$p/link-$link/$name" ]; then
                    printf 'FIELD link-%s/%s\n' "$link" "$name"
                    cat "$p/link-$link/$name"
                fi
            done
        done
    else
        echo NO_STATION
    fi
    printf 'END %s\n' "$seq"
done
"""

def decode(lines):
    stats={}
    debug={}
    field=None
    for line in lines:
        if line=="NO_STATION":
            return {"present":False}
        if line.startswith("FIELD "):
            field=line[6:]
            debug[field]=[]
        elif field is not None:
            debug[field].append(line)
        else:
            m=re.match(r"^\s*(rx packets|tx packets|tx retries|tx failed|rx drop misc|rx bytes|tx bytes|inactive time|signal|signal avg|last ack signal|connected time|authorized|authenticated|associated):\s*(.*)$",line)
            if m:
                stats[m[1]]=m[2]
    if not {"rx packets","tx packets","tx failed","associated"}<=stats.keys():
        return {"present":False,"incomplete":True,"raw_stats":stats}
    return {"present":True,"station":stats,"debug":debug}

def selftest():
    assert decode(["NO_STATION"])=={"present":False}
    data=decode(["\trx packets: 10","\ttx packets: 12","\ttx failed: 0",
                 "\tassociated: yes","FIELD flags","AUTH","ASSOC","FIELD num_ps_buf_frames","AC0: 0"])
    assert data["present"] and data["station"]["tx packets"]=="12"
    assert data["debug"]["flags"]==["AUTH","ASSOC"]
    assert data["debug"]["num_ps_buf_frames"]==["AC0: 0"]
    assert decode(["\trx packets: 10"])["incomplete"]
    print("AP_CLIENT_OBSERVER_SELFTEST_PASS")

def observe(tag,duration):
    if os.getuid()==0 or not re.fullmatch(r"0498-\d{8}-\d{6}",tag) or not 10<=duration<=240:
        raise ValueError("invalid user, tag or duration")
    if Path("/sys/class/net/enp4s0f4u2u2u4/address").read_text().strip()!="00:e0:4c:68:01:45":
        raise ValueError("wrong Asus switch device")
    if Path("/sys/class/net/enp4s0f4u2u2u4/carrier").read_text().strip()!="1":
        raise ValueError("no switch carrier")
    if subprocess.check_output(["timedatectl","show","-p","NTPSynchronized","--value"],text=True).strip()!="yes":
        raise ValueError("observer clock not synchronized")
    if subprocess.run(["systemctl","is-active","--quiet","wave7-lab-upstream-guard8.service"]).returncode:
        raise ValueError("upstream lab helper not active")
    lock=open(BASE/".lab-control.lock","r+")
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    out=BASE/"client-validation"/(tag+"-ap-observer")
    out.mkdir(mode=0o700,parents=False,exist_ok=False)
    cmd=["ssh","-T","-i","/home/jan/.ssh/wave7-root-rsa",
         "-o","BindInterface=enp4s0f4u2u2u4","-o","BindAddress=192.168.76.250",
         "-o","BatchMode=yes","-o","IdentitiesOnly=yes","-o","StrictHostKeyChecking=yes",
         "-o",f"UserKnownHostsFile={BASE/'known_hosts'}","-o","ConnectTimeout=4",
         "-o","ServerAliveInterval=4","-o","ServerAliveCountMax=2","root@192.168.76.1",REMOTE]
    # Binary reads avoid buffered TextIO interfering with readiness selection.
    raw=open(out/"samples.jsonl","x",buffering=1)
    stderr=open(out/"ssh-stderr.txt","xb")
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,bufsize=0)
    sel=selectors.DefaultSelector()
    sel.register(proc.stdout,selectors.EVENT_READ)
    pending=bytearray()
    def line(deadline):
        while True:
            idx=pending.find(b"\n")
            if idx>=0:
                value=bytes(pending[:idx])
                del pending[:idx+1]
                return value.decode("utf-8","strict")
            timeout=deadline-time.monotonic()
            if timeout<=0 or not sel.select(timeout):
                raise TimeoutError("AP response deadline")
            block=os.read(proc.stdout.fileno(),4096)
            if not block:
                raise EOFError("AP observer ended")
            pending.extend(block)
            if len(pending)>262144:
                raise ValueError("oversized response")
    count=0
    try:
        ready=line(time.monotonic()+8)
        if ready!=f"READY {BOOT} {REVISION}":
            raise ValueError(f"wrong firmware: {ready}")
        (out/"ready.txt").write_text(ready+"\n")
        print("AP_OBSERVER_READY",flush=True)
        start=time.monotonic()
        scheduled=start
        while time.monotonic()-start<duration:
            time.sleep(max(0,scheduled-time.monotonic()))
            if time.monotonic()-start>=duration:
                break
            scheduled=time.monotonic()+.25
            seq=str(count)
            t0=time.time_ns()
            proc.stdin.write((seq+"\n").encode())
            deadline=time.monotonic()+2
            head=line(deadline).split()
            if len(head)!=4 or head[:2]!=["BEGIN",seq]:
                raise ValueError("mismatched sample header")
            lines=[]
            while True:
                entry=line(deadline)
                if entry==f"END {seq}":
                    break
                lines.append(entry)
                if len(lines)>150:
                    raise ValueError("oversized sample")
            t1=time.time_ns()
            raw.write(json.dumps({"seq":count,"before_ns":t0,"after_ns":t1,
                "router_uptime_s":head[2],"data":decode(lines)},separators=(",",":"))+"\n")
            count+=1
        (out/"status.txt").write_text(f"complete samples={count}\n")
    finally:
        sel.close()
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=3)
        raw.close()
        stderr.close()
        files=sorted(out.iterdir())
        (out/"SHA256SUMS").write_text("".join(
            f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n" for f in files if f.is_file()))
        lock.close()
        print(f"AP_OBSERVATION_DIR={out} samples={count}",flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag",nargs="?")
    parser.add_argument("--seconds",type=int,default=220)
    parser.add_argument("--selftest",action="store_true")
    args=parser.parse_args()
    if args.selftest:
        selftest()
    else:
        observe(args.tag,args.seconds)
