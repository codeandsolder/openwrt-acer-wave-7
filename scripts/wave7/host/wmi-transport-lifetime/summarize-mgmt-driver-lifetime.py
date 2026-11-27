#!/usr/bin/env python3
"""Join metadata-only management TX events by cookie and descriptor generation.

Firmware residence starts at successful host transport acceptance, not a
claimed RF transmission time. Boundary-censored and orphan events are retained.
"""
import argparse
import json
from pathlib import Path
import re
import runpy

helpers = runpy.run_path(str(Path(__file__).with_name('summarize-mgmt-lifetime.py')))
LINE, require = helpers['LINE'], helpers['require']
ACK = re.compile(r'^([^ ]+) id=(\d+) cookie=(\d+) attach=([01]) acked=([01]) dropped=([01])$')
PHASES = {'queue', 'prepare', 'prepare_fail', 'submit', 'submitted', 'complete',
          'cancel', 'drop', 'orphan', 'flush_begin', 'flush_end'}
FIELDS = {'device', 'wiphy', 'phase', 'pdev', 'desc', 'vdev', 'result', 'freq',
          'agnostic', 'ack_id', 'link', 'fc', 'seq', 'len', 'pending'}
SUBTYPES = {0:'assoc-request',1:'assoc-response',2:'reassoc-request',3:'reassoc-response',
            4:'probe-request',5:'probe-response',8:'beacon',9:'atim',10:'disassoc',
            11:'auth',12:'deauth',13:'action',14:'action-no-ack'}


def event_fields(body):
    pairs = [part.split('=', 1) for part in body.split()]
    require(all(len(p)==2 for p in pairs), 'malformed driver event')
    row = dict(pairs)
    require(len(row)==len(pairs) and row.keys()==FIELDS and row['phase'] in PHASES, 'driver event schema')
    for key in FIELDS-{'device','wiphy','phase'}:
        row[key] = int(row[key],16 if key in ('fc','seq') else 10)
    require(row['agnostic'] in (0,1) and row['desc']>=-1 and row['ack_id']>=-1 and row['len']>=0, 'driver field range')
    return row


def interval(a,b):
    return None if a is None or b is None else round((b-a)*1000,3)


def parse(text):
    userspace=helpers['parse_trace'](text)
    marker=re.findall(r'^AP_MGMT_LIFETIME=([01])$',text,re.M)
    require(len(marker)<=1,'duplicate lifetime marker')
    if not marker or marker==['0']:
        require(not any(': ath12k_mgmt_lifetime:' in l or ': ack_status_lifetime:' in l for l in text.splitlines()),'unadvertised driver trace')
        return {'boot':userspace['boot'],'driver_trace_available':False,'driver_trace_captured':False,'userspace':userspace}
    active_acks={}; acks={}; queued={}; descriptors={}; awaiting_return={}; attempts=[]
    flushes=[]; active_flush={}; anomalies=[]; drops=[]; counts={}
    for line in text.splitlines():
        m=LINE.match(line)
        if not m: continue
        _,stamp,name,body=m.groups(); t=float(stamp)
        if name=='ack_status_lifetime':
            a=ACK.fullmatch(body); require(a,'malformed ACK-ID event')
            phy,ack_id,cookie,attach,acked,dropped=a.groups()
            aid=(phy,int(ack_id)); key=(phy,int(cookie))
            if attach=='1':
                require(aid not in active_acks and key not in acks,'duplicate live ACK-ID/cookie')
                active_acks[aid]=key; acks[key]=dict(wiphy=phy,cookie=int(cookie),ack_id=int(ack_id),attached_at=t)
            elif active_acks.get(aid)==key:
                active_acks.pop(aid); acks[key].update(reported_at=t,acked=acked=='1',dropped=dropped=='1')
            else:
                anomalies.append(dict(time=t,kind='unmatched_ack_release',wiphy=phy,ack_id=int(ack_id),cookie=int(cookie)))
            continue
        if name!='ath12k_mgmt_lifetime': continue
        e=event_fields(body); phase=e.pop('phase'); e['time']=t; counts[phase]=counts.get(phase,0)+1
        radio=(e['device'],e['pdev']); desc=(*radio,e['desc']); aid=(e['wiphy'],e['ack_id']); key=active_acks.get(aid)
        if phase=='queue':
            if key is not None: queued.setdefault((*radio,key),[]).append(e)
        elif phase=='prepare':
            require(e['desc']>=0 and desc not in descriptors and desc not in awaiting_return,'duplicate live firmware descriptor')
            q=queued.get((*radio,key),[]) if key is not None else []
            row=dict(device=e['device'],pdev=e['pdev'],wiphy=e['wiphy'],desc=e['desc'],cookie=key[1] if key else None,
                     ack_id=e['ack_id'],link=e['link'],vdev=e['vdev'],fc=e['fc'],seq=e['seq'],len=e['len'],
                     subtype=SUBTYPES.get((e['fc']>>4)&15,'other') if e['len']>=2 and not e['fc']&12 else None,
                     queued_at=q.pop(0)['time'] if q else None,prepared_at=t)
            descriptors[desc]=row; attempts.append(row)
        elif phase=='submit':
            row=descriptors.get(desc)
            if row is None:
                anomalies.append(dict(kind='submit_without_prepare',**e)); continue
            require('submit_at' not in row,'duplicate descriptor submission')
            row.update(submit_at=t,freq=e['freq'],agnostic=bool(e['agnostic'])); awaiting_return[desc]=row
        elif phase=='submitted':
            row=awaiting_return.pop(desc,None)
            if row is None: anomalies.append(dict(kind='return_without_submit',**e)); continue
            row.update(submitted_at=t,submit_result=e['result'])
        elif phase in ('complete','cancel','prepare_fail'):
            row=descriptors.pop(desc,None)
            if row is None: anomalies.append(dict(kind='terminal_without_prepare',phase=phase,**e)); continue
            require(row['ack_id']==e['ack_id'],'descriptor ACK-ID changed')
            row.update(terminal_at=t,terminal_phase=phase,terminal_result=e['result'])
        elif phase=='orphan':
            anomalies.append(dict(kind='firmware_orphan',**e))
        elif phase=='drop':
            drops.append(dict(cookie=key[1] if key else None,**e))
            # A queued frame may be purged without ever receiving a descriptor.
            q=queued.get((*radio,key),[]) if key is not None else []
            if q: q.pop(0)
        elif phase=='flush_begin':
            require(radio not in active_flush,'overlapping radio flush')
            row=dict(device=radio[0],pdev=radio[1],begin_at=t,pending_before=e['pending'])
            active_flush[radio]=row; flushes.append(row)
        elif phase=='flush_end':
            row=active_flush.pop(radio,None)
            if row is None: anomalies.append(dict(kind='flush_end_without_begin',**e)); continue
            row.update(end_at=t,result=e['result'],pending_after=e['pending'],latency_ms=interval(row['begin_at'],t))
    for row in attempts:
        row['queue_ms']=interval(row['queued_at'],row['prepared_at'])
        row['prepare_ms']=interval(row['prepared_at'],row.get('submit_at'))
        row['transport_ms']=interval(row.get('submit_at'),row.get('submitted_at'))
        end=row.get('terminal_at') if row.get('terminal_phase')=='complete' else None
        row['submission_to_completion_ms']=interval(row.get('submit_at'),end)
        returned=row.get('submitted_at') if row.get('submit_result')==0 else None
        row['completion_before_return']=end is not None and returned is not None and end<returned
        row['post_transport_ms']=interval(returned,end) if end is not None and returned is not None and end>=returned else None
        ack=acks.get((row['wiphy'],row['cookie']))
        row['mac80211_report_ms']=interval(end,ack.get('reported_at')) if end is not None and ack and ack.get('reported_at',0)>=end else None
        row['right_censored']='terminal_phase' not in row
    # Cookie is allocated by a wiphy, not globally by device or by firmware ID.
    by_cookie={}
    for row in attempts:
        if row['cookie'] is not None: by_cookie.setdefault((row['wiphy'],row['cookie']),[]).append(row)
    return dict(boot=userspace['boot'],driver_trace_available=True,driver_trace_captured=bool(counts),phase_counts=counts,
                userspace=userspace,ack_lifetimes=list(acks.values()),attempts=attempts,
                flushes=flushes,anomalies=anomalies,drops=drops,
                unmatched_queue_events=[e for q in queued.values() for e in q],
                unresolved_returns=[dict(device=r['device'],pdev=r['pdev'],desc=r['desc'],cookie=r['cookie']) for r in awaiting_return.values()],
                open_ack_ids=[dict(wiphy=k[0],ack_id=k[1],cookie=v[1]) for k,v in active_acks.items()],
                cookie_attempts=[dict(wiphy=k[0],cookie=k[1],attempts=v) for k,v in by_cookie.items()])


def selftest():
    def line(t,name,body): return f'worker-1 [000] ..... {t:.6f}: {name}: {body}'
    def ack(t,id,cookie,attach=1,acked=0,dropped=0): return line(t,'ack_status_lifetime',f'phy0 id={id} cookie={cookie} attach={attach} acked={acked} dropped={dropped}')
    def drv(t,phase,desc=-1,aid=3,result=0,device='c000000.wifi',pdev=0):
        return line(t,'ath12k_mgmt_lifetime',f'device={device} wiphy=phy0 phase={phase} pdev={pdev} desc={desc} vdev=1 result={result} freq=0 agnostic=0 ack_id={aid} link=0 fc=0x00b0 seq=0x1000 len=36 pending=1')
    def trace(*lines,marker=1): return f'AP_MGMT_LIFETIME={marker}\nAP_CONTROL_TRACE_READY boot=12345678-1234-1234-1234-123456789abc\n'+'\n'.join(lines)+'\noverrun: 0\ncommit overrun: 0\ndropped events: 0\nAP_CONTROL_TRACE_END rc=0\n'
    data=parse(trace(ack(1,3,7),drv(1.001,'queue'),drv(1.002,'prepare',0),drv(1.003,'submit',0,-1),drv(1.004,'submitted',0,-1),drv(6,'complete',0,result=9),ack(6.001,3,7,0),ack(7,3,8),drv(7.001,'queue'),drv(7.002,'prepare',0),drv(7.003,'submit',0,-1),drv(7.004,'complete',0),drv(7.005,'submitted',0,-1),ack(7.006,3,8,0,1)))
    a,b=data['attempts']; require(a['cookie']==7 and a['queue_ms']==1 and a['post_transport_ms']==4996 and a['terminal_result']==9,'slow path'); require(b['cookie']==8 and b['completion_before_return'] and b['post_transport_ms'] is None,'eager completion/ID reuse'); require(not data['anomalies'] and not data['unresolved_returns'],'false anomalies')
    data=parse(trace(drv(1,'orphan',0,-1,result=4),drv(2,'prepare',0,-1),drv(2.1,'submit',0,-1),drv(2.2,'submitted',0,-1),drv(3,'flush_begin',-1,-1),drv(8,'flush_end',-1,-1,result=-110)))
    require(data['attempts'][0]['right_censored'] and data['flushes'][0]['latency_ms']==5000 and data['anomalies'][0]['kind']=='firmware_orphan','censored/orphan/flush')
    require(not parse(trace(marker=0))['driver_trace_available'],'old trace handling')
    empty=parse(trace(ack(1,3,7),ack(2,3,7,0)))
    require(empty['driver_trace_available'] and not empty['driver_trace_captured'],'enabled event without records')
    require(data['driver_trace_captured'],'recorded driver trace')
    for bad in (trace(drv(1,'prepare',0),drv(2,'prepare',0)), trace(ack(1,3,7),ack(2,3,8)),trace(drv(1,'queue'),marker=0)):
        try: parse(bad)
        except ValueError: pass
        else: raise AssertionError('malformed trace accepted')
    print('MGMT_DRIVER_LIFETIME_SELFTEST_PASS')


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('trial',type=Path,nargs='?'); p.add_argument('--band',choices=('24','5')); p.add_argument('--selftest',action='store_true'); a=p.parse_args()
    if a.selftest: selftest()
    elif a.trial and a.band: print(json.dumps(parse(helpers['verify_trace'](a.trial,a.band)),indent=2))
    else: p.error('trial and band or --selftest required')


if __name__=='__main__': main()
