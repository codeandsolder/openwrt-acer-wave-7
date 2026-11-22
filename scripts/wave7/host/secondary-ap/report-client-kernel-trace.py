#!/usr/bin/env python3
"""Join a private kernel trace with measured common reply-silence intervals.

Function calls are evidence of control flow, not successful operations.
Network tracepoints identify packet submission/receive, not RF delivery.
No payloads or missing-probe send times are reconstructed.
"""
import argparse
from collections import Counter
from decimal import Decimal as D
import json
from pathlib import Path
import re

LINE=re.compile(r"^\s*(.*?)\s+\[(\d+)\]\s+\S+\s+(\d+\.\d+):\s+(.*)$")
ANCHOR=re.compile(r"^ANCHOR (\d+) (\d+\.\d+) (\d+\.\d+)$")
MARKER=re.compile(r"(?:tracing_mark_write: |print: )?wave7_anchor=(\d+)$")
FUNCTION=re.compile(r"(?:function: )?([A-Za-z0-9_.$]+)\s+<-.*$")
COUNTS=re.compile(r"entries-in-buffer/entries-written:\s*(\d+)/(\d+)")

def parse(text):
    if text.count("TRACE_DATA\n")!=1 or text.count("TRACE_END\n")!=1 or "TRACE_CLEANUP rc=0" not in text:
        raise ValueError("incomplete trace or cleanup failure")
    header,body=text.split("TRACE_DATA\n")
    body=body.split("TRACE_END\n")[0]
    if "[mono]" not in header:
        raise ValueError("unexpected trace clock")
    anchors={}
    for line in header.splitlines():
        m=ANCHOR.fullmatch(line)
        if m:
            idx,a,b=m.groups()
            if idx in anchors or not D(a)<=D(b):
                raise ValueError("invalid anchor bracket")
            anchors[idx]=(D(a),D(b))
    stats=[int(v) for v in re.findall(r"(?m)^\s*(?:overrun|commit overrun|dropped events):\s*(\d+)",header)]
    if not stats or any(stats):
        raise ValueError(f"lost trace records: {stats}")
    counters=COUNTS.search(body)
    if counters is None or counters[1]!=counters[2]:
        raise ValueError("trace ring overwritten")
    events=[]
    offsets=[]
    seen=set()
    for line in body.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m=LINE.fullmatch(line)
        if m is None:
            raise ValueError(f"unparseable trace line: {line[:180]}")
        task,cpu,t,payload=m.groups()
        when=D(t)
        marker=MARKER.fullmatch(payload)
        if marker:
            idx=marker[1]
            if idx in seen or idx not in anchors:
                raise ValueError("missing or duplicate clock anchor")
            seen.add(idx)
            before,after=anchors[idx]
            offsets.append((before-when,after-when,when))
            continue
        f=FUNCTION.fullmatch(payload)
        if f:
            name=f[1]
        else:
            name,sep,_=payload.partition(": ")
            if not sep:
                raise ValueError(f"unknown trace payload: {payload[:180]}")
        events.append((when,name,task,payload,int(cpu)))
    if len(seen)!=len(anchors) or len(seen)<3:
        raise ValueError("insufficient or missing clock anchor records")
    lo=min(a for a,b,t in offsets)
    hi=max(b for a,b,t in offsets)
    if hi-lo>D(".025"):
        raise ValueError(f"clock conversion uncertainty too wide: {hi-lo}s")
    # Include 1ms quantization/scheduling guard beyond observed brackets.
    lo-=D(".001")
    hi+=D(".001")
    lo_t=min(t for a,b,t in offsets)
    hi_t=max(t for a,b,t in offsets)
    return {"events":sorted(events),"offset_lo":lo,"offset_hi":hi,
            "first_anchor":lo_t,"last_anchor":hi_t,"anchors":len(seen),
            "trace_count":int(counters[1]),"zero_loss_stats":stats}

# Source-backed Connac3 definitions in mt76_connac_mcu.h and
# mt76_connac3_mac.h; preserve raw values for unknown event/status codes.
EIDS={3:"HIF_CTRL",4:"FW_LOG",10:"COREDUMP",12:"BEACON_LOSS",
      13:"PS_SYNC",14:"SCAN_DONE",39:"ROC",40:"MBMC",45:"TX_DONE",
      65:"RSSI_MONITOR",86:"NAN"}

def metadata(selection,lo,hi,start):
    mcu=Counter()
    frees=Counter()
    txs=Counter()
    samples=[]
    for when,name,task,payload,cpu in selection:
        if not name.startswith("mt7925_lab_"):
            continue
        kv={k:int(v) for k,v in re.findall(r"(\w+)=(\d+)",payload)}
        if name=="mt7925_lab_mcu_rx":
            eid,option=kv["eid"],kv["option"]
            label=EIDS.get(eid,"UNKNOWN") if option&4 else "solicited_or_other"
            mcu[(eid,option,label)]+=1
            if option&4 and eid!=45:
                samples.append({"offset_s":when+(lo+hi)/2-start,"name":name,**kv})
        elif name=="mt7925_lab_txfree":
            frees[(kv["wcid"],kv["status"],kv["count"])]+=1
        elif name=="mt7925_lab_txs":
            word=kv["word0"]
            txs[(kv["wcid"],(word>>16)&7,bool(word&(1<<22)),
                 bool(word&(1<<21)),bool(word&(1<<20)),bool(word&(1<<19)))]+=1
        else:
            samples.append({"offset_s":when+(lo+hi)/2-start,"name":name,**kv})
    return {"mcu":[{"eid":e,"option":o,"kind":k,"n":n}
                   for (e,o,k),n in sorted(mcu.items())],
            "txfree":[{"wcid":w,"status":s,"attempt_count_field":c,"n":n}
                      for (w,s,c),n in sorted(frees.items())],
            "txs":[{"wcid":w,"ack_error":a,"ba_error":b,"ps_flag":p,
                     "txop_timeout":t,"bip_error":i,"n":n}
                    for (w,a,b,p,t,i),n in sorted(txs.items())],
            "state_metadata":samples}

def phase(events,lo,hi,start,end):
    # Only count events wholly inside the requested interval for every
    # offset consistent with observed clock brackets.
    selection=[e for e in events if start<=e[0]+lo and e[0]+hi<=end]
    counts=Counter(e[1] for e in selection)
    ping=Counter(e[1] for e in selection if re.search(r"\bping(?:6)?-\d+$",e[2]))
    # Preserve queue transitions and radio-state operations, not thousands
    # of per-packet events. A stop/wake is a reason/refcount observation.
    interesting=[{"offset_from_start_s":e[0]+(lo+hi)/2-start,
                  "event":e[1],"payload":e[3]}
                 for e in selection if e[1] in {
                     "stop_queue","wake_queue","drv_hw_scan","api_scan_completed",
                     "cfg80211_scan_done","drv_remain_on_channel","drv_cancel_remain_on_channel",
                     "api_ready_on_channel","api_remain_on_channel_expired",
                     "drv_change_vif_links","drv_change_sta_links","api_beacon_loss",
                     "api_connection_loss","mt7925_scan_work","mt7925_roc_work",
                     "mt7925_mcu_set_roc","mt7925_mcu_abort_roc","mt7925_set_roc",
                      "mt792x_pm_wake_work","mt792x_pm_power_save_work",
                     "__mt76_set_tx_blocked","mt792x_mcu_drv_pmctrl","mt792x_mcu_fw_pmctrl",
                     "mt76_connac_pm_queue_skb","mt76_connac_pm_dequeue_skbs",
                     "mt7925_mlo_pm_work","mt7925_mcu_uni_bss_ps","mt7925_mcu_set_dbdc"}]
    xmit_rc=Counter()
    for e in selection:
        if e[1]=="net_dev_xmit":
            match=re.search(r"\brc=(-?\d+)",e[3])
            if match is None:
                raise ValueError("missing net_dev_xmit return code")
            xmit_rc[int(match[1])]+=1
    return {"start":start,"end":end,"duration_s":end-start,
            "counts":dict(counts),"ping_task_counts":dict(ping),
            "net_dev_xmit_rc":dict(xmit_rc),
            "state_events":interesting,
            "firmware_metadata":metadata(selection,lo,hi,start)}

def analyze(trace,timing):
    lo,hi=trace["offset_lo"],trace["offset_hi"]
    result=[]
    for window in timing["windows"]+timing.get("isolated_unattributed_multichannel",[]):
        w=window["common_arrival_silence"]
        start,end=D(w["last_reply"]),D(w["next_reply"])
        scan_end=start-D(w["last_reply_after_scan_end_s"])
        if end-start<D(".25") or not any(p["missing_sequences"] for p in window["paths"]):
            continue
        if scan_end<trace["first_anchor"]+hi or end+D(".5")>trace["last_anchor"]+lo:
            continue
        span=end-start
        result.append({"label":window.get("label","unattributed-multichannel"),
                       "frequencies_mhz":window["frequencies_mhz"],
                       "scan_end":scan_end,"last_reply":start,"first_recovery_reply":end,
                       "pre_gap":phase(trace["events"],lo,hi,start-span,start),
                       "inside_gap":phase(trace["events"],lo,hi,start,end),
                       "recovery":phase(trace["events"],lo,hi,end,end+span),
                       "scan_to_gap":phase(trace["events"],lo,hi,scan_end,start)})
    return {"trace_events":trace["trace_count"],"anchors":trace["anchors"],
            "clock_offset_lower":lo,"clock_offset_upper":hi,
            "clock_uncertainty_s":hi-lo,"zero_loss_stats":trace["zero_loss_stats"],
            "windows":result,
            "method":"Same-client monotonic trace correlated with realtime ping timestamps using bracketed anchors. Counts only events guaranteed inside phase under observed offset bounds; function entries do not imply successful DMA, RF TX, or RX."}

def selftest():
    t="""TRACE_CLOCK local [mono]
ANCHOR 0 100.000 100.002
ANCHOR 1 101.000 101.002
ANCHOR 2 102.000 102.002
overrun: 0
commit overrun: 0
dropped events: 0
TRACE_DATA
# entries-in-buffer/entries-written: 5/5
  test-1 [000] .... 10.001: tracing_mark_write: wave7_anchor=0
  ping-2 [000] .... 10.500: net_dev_queue: dev=wlp2s0 skbaddr=abc len=98
  kworker-4 [001] .... 10.700: mt7925_scan_work <-process_one_work
  test-1 [000] .... 11.001: tracing_mark_write: wave7_anchor=1
  test-1 [000] .... 12.001: tracing_mark_write: wave7_anchor=2
TRACE_END
TRACE_CLEANUP rc=0
"""
    a=parse(t)
    assert a["anchors"]==3 and a["offset_hi"]-a["offset_lo"]==D(".004")
    x=phase(a["events"],a["offset_lo"],a["offset_hi"],D("100.4"),D("100.8"))
    assert x["counts"]=={"net_dev_queue":1,"mt7925_scan_work":1}
    assert x["ping_task_counts"]=={"net_dev_queue":1}
    assert not phase(a["events"],a["offset_lo"],a["offset_hi"],D("100.500"),D("100.6"))["counts"]
    for bad in (t.replace("overrun: 0","overrun: 1"),t.replace("5/5","5/6"),
                t.replace("wave7_anchor=2","wave7_anchor=1")):
        try:
            parse(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("rejected trace accepted")
    md=metadata([
        (D(1),"mt7925_lab_mcu_rx","x","mt7925_lab_mcu_rx: eid=13 seq=0 option=4 ext_eid=0 length=44",0),
        (D(1),"mt7925_lab_mcu_rx","x","mt7925_lab_mcu_rx: eid=13 seq=2 option=0 ext_eid=0 length=44",0),
        (D(1),"mt7925_lab_txfree","x","mt7925_lab_txfree: wcid=4 count=3 status=2",0),
        (D(1),"mt7925_lab_txs","x","mt7925_lab_txs: wcid=4 pid=7 word0=4325376",0)
    ],D(0),D(0),D(0))
    assert any(x["kind"]=="PS_SYNC" for x in md["mcu"])
    assert any(x["kind"]!="PS_SYNC" for x in md["mcu"])
    assert md["txfree"]==[{"wcid":4,"status":2,"attempt_count_field":3,"n":1}]
    assert md["txs"][0]["ack_error"]==2 and md["txs"][0]["ba_error"]
    print("CLIENT_KERNEL_TRACE_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("trace",type=Path,nargs="?")
    p.add_argument("timing",type=Path,nargs="?")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:
        selftest()
    else:
        if a.trace is None or a.timing is None:
            p.error("supply trace and arrival-timing report")
        print(json.dumps(analyze(parse(a.trace.read_text()),json.loads(a.timing.read_text())),indent=2,default=str))
