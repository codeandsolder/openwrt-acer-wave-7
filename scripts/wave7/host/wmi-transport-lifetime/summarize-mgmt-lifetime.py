#!/usr/bin/env python3
"""Correlate cfg80211 management submission, status, and station lifecycle."""
import argparse
import hashlib
import json
from pathlib import Path
import re

LINE = re.compile(r'^\s*.*-(\d+)\s+\[\d+\]\s+\S+\s+(\d+\.\d+): (\w+): (.*)$')
WDEV = re.compile(r'\bwdev\((\d+)\)')
RETURN = re.compile(r'\breturned (-?\d+), cookie: (\d+)')
STATUS = re.compile(r'\bcookie: (\d+), ack: (true|false)')
STATE = re.compile(r'\bsta:([0-9a-f:]+) state: (\d+)->(\d+)')
LOSS = re.compile(r'^(?:overrun|commit overrun|dropped events):\s*(\d+)$', re.M)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def verify_trace(trial, band):
    name = f'band-{band}.ap-control-trace.txt'
    manifest = {}
    for line in (trial / 'SHA256SUMS').read_text().splitlines():
        digest, member = line.split(maxsplit=1)
        member = member.removeprefix('./')
        require(re.fullmatch(r'[0-9a-f]{64}', digest) and '/' not in member and member not in manifest, 'invalid seal')
        manifest[member] = digest
    require(name in manifest, 'trace not sealed')
    path = trial / name
    require(path.is_file() and not path.is_symlink(), 'invalid trace file')
    with path.open('rb') as f:
        require(hashlib.file_digest(f, 'sha256').hexdigest() == manifest[name], 'trace digest mismatch')
    return path.read_text()


def parse_trace(text):
    boot = re.findall(r'^AP_CONTROL_TRACE_READY boot=([a-f0-9-]{36})$', text, re.M)
    require(len(boot) == 1 and text.count('AP_CONTROL_TRACE_END rc=0') == 1, 'incomplete trace')
    loss = LOSS.findall(text)
    require(loss and len(loss) % 3 == 0 and not any(map(int, loss)), 'trace loss or missing stats')
    pending = {}
    submissions = {}
    failures = []
    no_ack = []
    completions = {}
    states = []
    requests = []
    latest = 0.0
    for line in text.splitlines():
        m = LINE.match(line)
        if not m:
            continue
        pid, stamp, event, body = m.groups()
        t = float(stamp)
        require(t >= latest, 'trace clock regressed')
        latest = t
        if event == 'rdev_mgmt_tx':
            wdev = WDEV.search(body)
            require(wdev and pid not in pending, 'unpaired management submission')
            pending[pid] = dict(submitted_at=t, wdev=int(wdev[1]),
                                expect_ack='dont wait for ack: true' not in body)
        elif event == 'rdev_return_int_cookie' and pid in pending:
            ret = RETURN.search(body)
            require(ret, 'malformed management return')
            row = pending.pop(pid)
            row.update(returned_at=t, ret=int(ret[1]), cookie=int(ret[2]))
            if row['ret']:
                failures.append(row)
                continue
            # mac80211 deliberately reuses 0xffffffff for no-ACK requests;
            # such calls do not represent unique status-bearing transactions.
            if not row['expect_ack']:
                no_ack.append(row)
                continue
            key = row['wdev'], row['cookie']
            require(key not in submissions, f'duplicate management cookie {key}')
            submissions[key] = row
        elif event == 'cfg80211_mgmt_tx_status':
            wdev, status = WDEV.search(body), STATUS.search(body)
            require(wdev and status, 'malformed management status')
            key = int(wdev[1]), int(status[1])
            require(key not in completions, f'duplicate management status {key}')
            completions[key] = dict(wdev=key[0], cookie=key[1], completed_at=t, ack=status[2] == 'true')
        elif event == 'drv_sta_state':
            state = STATE.search(body)
            require(state, 'malformed station state')
            states.append(dict(time=t, station=state[1], old=int(state[2]), new=int(state[3])))
        elif event in ('rdev_add_station', 'rdev_change_station', 'rdev_del_station'):
            requests.append(dict(time=t, event=event, metadata=body))
    rows = []
    for key in sorted(submissions.keys() | completions.keys()):
        row = dict(wdev=key[0], cookie=key[1])
        row.update(submissions.get(key, {}))
        row.update(completions.get(key, {}))
        if key in submissions and key in completions:
            require(row['completed_at'] >= row['submitted_at'], 'completion precedes submission')
            row['latency_s'] = round(row['completed_at'] - row['submitted_at'], 6)
        rows.append(row)
    paired = [r for r in rows if 'latency_s' in r]
    return dict(boot=boot[0], submission_trace_available=bool(submissions or failures or pending or no_ack),
                observed_until=latest, submissions=len(submissions), failed_submissions=failures, no_ack_submissions=no_ack,
                unresolved_calls=list(pending.values()), statuses=len(completions),
                acked=sum(r['ack'] for r in completions.values()),
                unacked=sum(not r['ack'] for r in completions.values()),
                paired=len(paired), missing_status=[r for r in rows if 'submitted_at' in r and 'completed_at' not in r and r['expect_ack']],
                status_without_submission=[r for r in rows if 'completed_at' in r and 'submitted_at' not in r],
                maximum_latency_s=max((r['latency_s'] for r in paired), default=None),
                station_transitions=states, station_requests=requests, transactions=rows)


def selftest():
    boot = '12345678-1234-1234-1234-123456789abc'
    def trace(*lines):
        return f'AP_CONTROL_TRACE_READY boot={boot}\n' + '\n'.join(lines) + '\noverrun: 0\ncommit overrun: 0\ndropped events: 0\nAP_CONTROL_TRACE_END rc=0\n'
    def event(pid, t, name, body):
        return f'hostapd-{pid} [001] ..... {t:.6f}: {name}: {body}'
    tx = lambda pid, t: event(pid,t,'rdev_mgmt_tx','phy0, wdev(1), dont wait for ack: false')
    ret = lambda pid,t,c: event(pid,t,'rdev_return_int_cookie',f'phy0, returned 0, cookie: {c}')
    status = lambda t,c,a: event(0,t,'cfg80211_mgmt_tx_status',f'wdev(1), cookie: {c}, ack: {a}')
    data = parse_trace(trace(tx(12,1), status(1.1,7,'true'), ret(12,1.2,7), tx(13,2), ret(13,2.1,8), tx(12,3), ret(12,3.1,9), status(3.2,9,'false'), status(8,8,'false'), tx(12,9), ret(12,9.1,10)))
    require(data['paired'] == 3 and data['maximum_latency_s'] == 6 and len(data['missing_status']) == 1 and data['acked'] == 1 and data['unacked'] == 2, 'wrong transaction result')
    no_ack_tx = lambda t: event(12,t,'rdev_mgmt_tx','phy0, wdev(1), dont wait for ack: true')
    no_ack = parse_trace(trace(no_ack_tx(1), ret(12,1.1,4294967295), no_ack_tx(2), ret(12,2.1,4294967295)))
    require(len(no_ack['no_ack_submissions']) == 2 and not no_ack['missing_status'], 'no-ACK cookie reuse')
    old = parse_trace(trace(status(1,5,'true'),status(2,6,'false')))
    require(not old['submission_trace_available'] and old['paired'] == 0 and old['maximum_latency_s'] is None, 'inferred unavailable latency')
    for bad in (trace(tx(1,1),tx(1,2)), trace(status(1,5,'true'),status(2,5,'false')), trace(status(2,5,'true'),status(1,6,'true')), trace(status(1,5,'true')).replace('overrun: 0','overrun: 1',1)):
        try:
            parse_trace(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid trace accepted')
    print('MGMT_LIFETIME_SELFTEST_PASS')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trial', type=Path, nargs='?')
    parser.add_argument('--band', choices=('24','5'))
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    if args.selftest:
        selftest()
    elif args.trial and args.band:
        print(json.dumps(parse_trace(verify_trace(args.trial,args.band)),indent=2))
    else:
        parser.error('trial and band or --selftest required')


if __name__ == '__main__':
    main()
