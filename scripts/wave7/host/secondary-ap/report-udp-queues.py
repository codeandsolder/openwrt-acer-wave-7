#!/usr/bin/env python3
"""Account for observed datagram loss against the exact receiver's socket queue."""
import argparse
import importlib.util
import ipaddress
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location("throughput",Path(__file__).with_name("report-serial-throughput.py"))
bench=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

def snmp(path):
    rows=[l.split()[1:] for l in path.read_text().splitlines() if l.startswith("Udp: ")]
    assert len(rows)==2 and len(rows[0])==len(rows[1])
    result={k:int(v) for k,v in zip(*rows)}
    assert {"RcvbufErrors","InErrors","SndbufErrors","InDatagrams"}<=result.keys()
    return result

def softnet(path):
    text=path.read_text().splitlines()
    a=text.index("softnet")+1
    b=text.index("socket_buffers")
    rows=[list(map(lambda v:int(v,16),l.split())) for l in text[a:b]]
    assert rows and all(len(r)>=3 for r in rows)
    return dict(processed=sum(r[0] for r in rows),dropped=sum(r[1] for r in rows),time_squeeze=sum(r[2] for r in rows))

def endpoint(value):
    ip,port=value.split(":")
    assert len(ip)==8 and len(port)==4
    return str(ipaddress.IPv4Address(bytes.fromhex(ip)[::-1])),int(port,16)

def sample_socket(path,local,remote):
    history=[]
    for line in path.read_text().splitlines():
        if not re.match(r"^\s*\d+:\s+[A-F0-9]{8}:[A-F0-9]{4}\s+[A-F0-9]{8}:[A-F0-9]{4}\s",line):
            continue
        fields=line.split()
        if endpoint(fields[1])!=local or endpoint(fields[2])!=remote:continue
        history.append((int(fields[9]),int(fields[-1]),int(fields[4].split(":")[1],16)))
    assert history,"no matched UDP data socket sampled"
    assert len({h[0] for h in history})==1,"socket replaced during benchmark"
    assert all(y[1]>=x[1] for x,y in zip(history,history[1:])),"socket counter regression"
    return dict(samples=len(history),socket_inode=history[0][0],max_drops=max(h[1] for h in history),max_rx_queue_bytes=max(h[2] for h in history))

def qualify(directory,entries,boot,name):
    result=bench.qualify_case(directory,entries,boot,2500,name)
    path,_,direction,mode=name.split("-")
    client=json.loads((directory/(name+".json")).read_text())
    conn=client["start"]["connected"][0]
    local=(conn["local_host"],conn["local_port"])
    remote=(conn["remote_host"],conn["remote_port"])
    reverse=direction=="tx"
    receiving="host" if reverse else "router"
    endpts={}
    for side in ("host","router"):
        def f(when):
            fname=f"{name}-{side}-stack-{when}.txt"
            assert fname in entries
            return directory/fname
        before,after=f("before"),f("after")
        delta=bench.diff(snmp(before),snmp(after))
        soft=bench.diff(softnet(before),softnet(after))
        assert min(*delta.values(),*soft.values())>=0
        a,b=(local,remote) if side=="host" else (remote,local)
        endpts[side]=dict(udp_delta=delta,softnet_delta=soft,socket=sample_socket(f("during"),a,b))
    lost=result["udp"]["lost_packets"]
    r=endpts[receiving]
    s=endpts["router" if reverse else "host"]
    exact=(r["udp_delta"]["RcvbufErrors"]==lost and r["udp_delta"]["InErrors"]==lost and
           s["udp_delta"]["RcvbufErrors"]==0 and not s["udp_delta"]["SndbufErrors"] and
           r["socket"]["max_drops"]<=lost)
    # Sampling may miss the final socket drop count if the socket closes
    # between observations. Keep that limitation explicit.
    result.update(buffer_mode=mode,receiver=receiving,endpoint_stats=endpts,
                  exact_receiver_rcvbuf_accounting=exact,
                  socket_drop_count_complete=r["socket"]["max_drops"]==lost)
    return result

def main():
    assert __debug__
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory",type=Path)
    p.add_argument("boot")
    a=p.parse_args()
    entries=bench.seal(a.directory)
    names=[f"{prefix}-{mode}" for mode in ("default","largebuf") for prefix in ("direct-udp-tx","switch-udp-rx","switch-udp-tx") if f"{prefix}-{mode}.json" in entries]
    assert len(names) in (3,6)
    results=[qualify(a.directory,entries,a.boot,n) for n in names]
    print(json.dumps(dict(boot=a.boot,
         input_manifest_sha256=bench.digest(a.directory/"SHA256SUMS"),
         path_verified=all(r["path_verified"] for r in results),
         clean_error_counters=all(r["clean_error_counters"] for r in results),
         exact_receiver_rcvbuf_accounting=all(r["exact_receiver_rcvbuf_accounting"] for r in results),
         larger_socket_loss_free=all(r["udp"]["loss_free"] for r in results if r["buffer_mode"]=="largebuf") if len(names)==6 else None,
         results=results),indent=2))
if __name__=="__main__":main()
