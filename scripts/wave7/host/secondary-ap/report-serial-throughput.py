#!/usr/bin/env python3
"""Qualify sealed router-endpoint throughput using both NICs and physical counters."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

NICS={"direct":"enp4s0f4u2u4","switch":"enp4s0f4u2u2u4"}
IPS={"direct":"192.168.76.2","switch":"192.168.76.250"}
ROUTER="192.168.76.1"
HOST_FIELDS=("rx_bytes","tx_bytes","rx_packets","tx_packets","rx_errors","tx_errors","rx_dropped","tx_dropped")
MAC_FIELDS=("rx_bytes_g","tx_bytes_g","rx_frames","tx_frames","rx_crc_err","rx_frag_err","rx_drop_frames","rx_fifo_overflow","rx_len_err","rx_wdog_err","tx_underflow_err")
SWITCH_FIELDS=("ifInOctets","ifOutOctets","dot3StatsFCSErrors","etherStatsFragments","etherStatsDropEvents")

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def seal(directory):
    entries={}
    for line in (directory/"SHA256SUMS").read_text().splitlines():
        sha,name=line.split("  ",1)
        name=name.removeprefix("./")
        assert Path(name).name==name and name not in entries
        assert re.fullmatch(r"[a-f0-9]{64}",sha) and digest(directory/name)==sha
        entries[name]=sha
    return entries

def parse_host(path):
    result={}
    for line in path.read_text().splitlines():
        nic,*fields=line.split()
        name=next(n for n,d in NICS.items() if d==nic)
        assert name not in result
        vals=dict(x.split("=",1) for x in fields)
        assert set(vals)==set(HOST_FIELDS)
        result[name]={k:int(v) for k,v in vals.items()}
    assert set(result)==set(NICS)
    return result

def parse_router(path,boot):
    lines=path.read_text().splitlines()
    assert lines[0]==boot
    uptime=float(lines[1].split()[0])
    assert math.isfinite(uptime) and uptime>=0
    sections=path.read_text().split("NIC statistics:")
    assert len(sections)==4
    def counters(section,prefix,names):
        result={}
        for line in section.splitlines():
            if m:=re.fullmatch(r"\s*"+prefix+r"(\w+):\s*(\d+)\s*",line):
                k=m[1]
                if k in names:
                    assert k not in result
                    result[k]=int(m[2])
        assert set(result)==set(names),(prefix,result)
        return result
    return dict(uptime=uptime,switch=counters(sections[1],"s00_p06_",SWITCH_FIELDS),
                switch_mac=counters(sections[1],"",MAC_FIELDS),
                direct=counters(sections[2],"",MAC_FIELDS))

def diff(a,b):
    assert a.keys()==b.keys()
    return {k:b[k]-a[k] for k in a}

def qualify_case(directory,entries,boot,rate,name):
    path,proto,router_dir,*variant=name.split("-")
    assert variant in ([],["default"],["largebuf"])
    reverse=router_dir=="tx"
    assert path in NICS and proto in ("tcp","udp") and router_dir in ("rx","tx")
    def read(suffix):
        f=name+suffix
        assert f in entries
        return directory/f
    client=json.loads(read(".json").read_text())
    server=json.loads(read("-server.json").read_text())
    for data,local,remote in ((client,IPS[path],ROUTER),(server,ROUTER,IPS[path])):
        assert not data.get("error"),data.get("error")
        start=data["start"]["test_start"]
        assert start["protocol"]==proto.upper() and start["reverse"]==int(reverse) and not start["bidir"]
        assert start["duration"]==(30 if proto=="tcp" else 15)
        assert start["num_streams"]==(4 if proto=="tcp" else 1)
        assert len(data["start"]["connected"])==start["num_streams"]
        assert all(c["local_host"]==local and c["remote_host"]==remote for c in data["start"]["connected"])
    cend=client["end"]
    send,receive=cend["sum_sent"],cend["sum_received"]
    sender=server["end"]["sum_sent"] if reverse else send
    receiver=receive if reverse else server["end"]["sum_received"]
    assert sender["bytes"]==send["bytes"] and receiver["bytes"]==receive["bytes"]
    for s in (sender,receiver):
        assert s["seconds"]>=client["start"]["test_start"]["duration"]-1 and s["bytes"]>0
        assert math.isfinite(s["bits_per_second"]) and s["bits_per_second"]>0
        assert abs(s["bits_per_second"]-s["bytes"]*8/s["seconds"])<1e-6*s["bits_per_second"]
    before=parse_host(read("-host-before.txt"))
    after=parse_host(read("-host-after.txt"))
    rb=parse_router(read("-router-before.txt"),boot)
    ra=parse_router(read("-router-after.txt"),boot)
    assert ra["uptime"]>rb["uptime"]
    host={n:diff(before[n],after[n]) for n in NICS}
    mac={n:diff(rb[n],ra[n]) for n in ("direct","switch_mac","switch")}
    all_deltas=[v for ds in (*host.values(),*mac.values()) for v in ds.values()]
    assert min(all_deltas)>=0,"counter reset/wrap"
    peer_direction="rx" if reverse else "tx"
    other="switch" if path=="direct" else "direct"
    payload=min(sender["bytes"],receiver["bytes"])
    match=host[path][peer_direction+"_bytes"]
    unrelated=max(host[other]["rx_bytes"],host[other]["tx_bytes"])
    # Include L2 overhead and the omitted warmup interval. The alternate
    # management path may carry bounded SSH/ARP traffic, not bulk data.
    router_bytes=mac[path][(router_dir+"_bytes_g") if path=="direct" else ("ifInOctets" if reverse else "ifOutOctets")]
    path_ok=match>=payload*.95 and router_bytes>=payload*.95 and unrelated<=max(2**20,payload*.02)
    errors={n:{k:v for k,v in ds.items() if k not in ("rx_bytes","tx_bytes","rx_packets","tx_packets","rx_bytes_g","tx_bytes_g","rx_frames","tx_frames","ifInOctets","ifOutOctets") and v} for n,ds in {**{("host_"+n):v for n,v in host.items()},**{("router_"+n):v for n,v in mac.items()}}.items()}
    clean=not any(errors.values())
    udp=None
    if proto=="udp":
        loss=receiver
        assert {"packets","lost_packets","lost_percent","jitter_ms"}<=loss.keys()
        assert loss["packets"]>0 and 0<=loss["lost_packets"]<=loss["packets"]
        target=min(rate//2,150)*1e6 if path=="direct" else 150e6
        assert client["start"]["test_start"]["target_bitrate"]==target
        udp={k:loss[k] for k in ("packets","lost_packets","lost_percent","jitter_ms")}
        udp["target_bps"]=target
        udp["loss_free"]=not loss["lost_packets"] and loss["lost_percent"]==0
    return dict(case=name,receiver_mbps=receiver["bits_per_second"]/1e6,
                sender_mbps=sender["bits_per_second"]/1e6,
                retransmits=sender["retransmits"] if proto=="tcp" else None,
                udp=udp,data_bytes=payload,path_verified=path_ok,
                matched_host_bytes=match,alternate_host_bytes=unrelated,router_bytes=router_bytes,
                clean_error_counters=clean,error_deltas=errors,
                host_deltas=host,router_deltas=mac)

def main():
    assert __debug__
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory",type=Path)
    p.add_argument("boot")
    p.add_argument("rate",type=int,choices=(10,100,1000,2500))
    a=p.parse_args()
    assert re.fullmatch(r"[a-f0-9-]{36}",a.boot)
    entries=seal(a.directory)
    cases=[f"{path}-{proto}-{direction}" for path in (NICS if a.rate==2500 else ("direct",)) for proto in ("tcp","udp") for direction in ("rx","tx")]
    results=[qualify_case(a.directory,entries,a.boot,a.rate,case) for case in cases]
    print(json.dumps(dict(boot=a.boot,direct_rate=a.rate,
          input_manifest_sha256=digest(a.directory/"SHA256SUMS"),
          endpoint_only=True,path_verified=all(r["path_verified"] for r in results),
          clean_error_counters=all(r["clean_error_counters"] for r in results),
          udp_loss_free=all(r["udp"]["loss_free"] for r in results if r["udp"] is not None),
          results=results),indent=2))
if __name__=="__main__":
    main()
