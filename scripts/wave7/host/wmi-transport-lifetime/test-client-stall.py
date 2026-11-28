#!/usr/bin/env python3
"""Exercise incomplete ping logs, duplicates, common silence and clock bounds."""
from decimal import Decimal as D
import runpy
from pathlib import Path
m=runpy.run_path(str(Path(__file__).with_name('report-client-stall.py')))
ping=m['ping']
silence=m['silence']
def log(t, seq):
    return f'[{t}] 64 bytes from fd76:7::2: icmp_seq={seq} ttl=64 time=5 ms\n'
def warn(t,seq):
    return f'[{t}] no answer yet for icmp_seq={seq}\n'
p=ping(log('100.00',1)+log('100.10',2)+log('100.12',2)+warn('100.40',3)+warn('101.00',3))
assert p['summary']==dict(sent=None,received=None,missing_sequences=None,
                         unique_replies_observed=2,duplicate_replies_observed=1)
assert silence(dict.fromkeys(m['PATHS'],p))[2]==[
    dict(start=D('100.12'),end=D('101.00'),duration_s=D('.88'),left_censored=False,right_censored=True)]
p=ping(log('100.00',1)+warn('100.10',2)+log('100.70',3)+log('100.75',2)+
       '3 packets transmitted, 3 received, 0% packet loss\n')
assert p['summary']['missing_sequences']==[]
assert silence(dict.fromkeys(m['PATHS'],p))[2][0]['duration_s']==D('.70')
# Trace with three bounded same-host anchors, one TX descriptor and return.
header='CLIENT_CONTROL_TRACE_READY boot=fixture\n[mono]\n'
header+='ANCHOR 0 99.0000 99.0001\nANCHOR 1 101.0000 101.0001\nANCHOR 2 103.0000 103.0001\n'
header+='overrun: 0\ncommit overrun: 0\ndropped events: 0\nTRACE_DATA\n'
body='# entries-in-buffer/entries-written: 6/6\n'
def event(t,msg):
    return f'  task-1 [000] .... {t}: {msg}\n'
body+=event('1.000000','tracing_mark_write: wave7_anchor=0')
body+=event('2.300000','mt7925_lab_data_txd: cookie=abcd length=90 protocol=0x0800 wcid=2 link=0 band=1 qid=0')
body+=event('2.400000','mt7925_lab_absence: bss=1 tag=0 len=8 absent=1 quota=2')
body+=event('2.500000','mt7925_lab_data_tx_free: cookie=abcd token=1 desc_wcid=2 fw_wcid=2 header_valid=1 header=40000000')
body+=event('3.000000','tracing_mark_write: wave7_anchor=1')
body+=event('5.000000','tracing_mark_write: wave7_anchor=2')
# Anchor times chosen to share offset 98s.
text=header+body+'TRACE_END\nTRACE_CLEANUP rc=0\nCLIENT_CONTROL_TRACE_END rc=0\n'
files={f'short-hold-{k}.txt':log('100.00',1)+log('100.10',2)+warn('100.40',3)+warn('101.00',3)
       for k in m['PATHS']}
r=m['summarize'](files,text)
g=r['common_silence'][0]
assert g['descriptor_submissions']==1
assert g['eventual_token_return_histogram']=={'attempt_field=0 status=0':1}
assert g['token_returned_definitely_inside']==1
assert g['nearby_state_transitions'][0]['event']=='mt7925_lab_absence'
for bad in (text.replace('overrun: 0','overrun: 1',1),
            text.replace('ANCHOR 2 103.0000 103.0001','ANCHOR 2 104.0000 104.0001'),
            text.replace('TRACE_CLEANUP rc=0','TRACE_CLEANUP rc=1')):
    try: m['summarize'](files,bad)
    except ValueError: pass
    else: raise AssertionError('invalid trace accepted')
print('CLIENT_STALL_REPORT_PASS')
