#!/usr/bin/env python3
"""Audit live credit reservations, not RF delivery or unique packet counts."""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal as D
import importlib.util
from itertools import groupby
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    'absence', Path(__file__).with_name('report-bss-absence.py'))
absence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(absence)

CREDIT = 'mt7925_lab_credit'
REFUND = 'mt7925_lab_credit_refund'


def classify(event):
    _, name, _, payload, _ = event
    k = absence.fields(payload)
    ticket = k['ticket']
    if ticket and not 1 <= (ticket & 255) <= 5:
        raise ValueError('invalid ticket BSS index')
    if name == CREDIT:
        if k['allowed'] not in (0, 1) or (not k['allowed'] and ticket):
            raise ValueError('invalid admission record')
        return ('charged' if ticket else 'unrestricted' if k['allowed'] else 'denied'), ticket
    if name != REFUND or not ticket or k['restored'] not in (0, 1):
        raise ValueError('invalid refund record')
    return ('restored' if k['restored'] else 'stale_refund'), ticket


def ledger(events):
    entries = [(e[0], *classify(e)) for e in events if e[1] in (CREDIT, REFUND)]
    total = Counter(kind for _, kind, _ in entries)
    accounts = defaultdict(lambda: dict(charged=0, restored=0, stale_refund=0,
                                         balance=0, peak_lower=0, peak_upper=0))
    # A printed microsecond can contain events on multiple CPUs. Bounds
    # do not assume an arbitrary order for those ties.
    for _, batch in groupby(entries, key=lambda item: item[0]):
        pending = defaultdict(Counter)
        for _, kind, ticket in batch:
            if ticket:
                pending[ticket][kind] += 1
        for ticket, counts in pending.items():
            a = accounts[ticket]
            old = a['balance']
            new = old + counts['charged'] - counts['restored']
            if new < 0 or a['charged'] + counts['charged'] < a['restored'] + counts['restored'] + a['stale_refund'] + counts['stale_refund']:
                raise ValueError('refund without reservation')
            a['peak_lower'] = max(a['peak_lower'], old, new)
            a['peak_upper'] = max(a['peak_upper'], old + counts['charged'])
            a['balance'] = new
            for kind in ('charged', 'restored', 'stale_refund'):
                a[kind] += counts[kind]
    return entries, total, [dict(ticket=t, bss=(t & 255)-1, epoch=t >> 8, **a)
                            for t, a in sorted(accounts.items())]


def analyze(trace, timing):
    _, records = absence.extract(trace['events'], True)
    entries, total, accounts = ledger(trace['events'])
    if not entries or not total['charged'] or not total['denied']:
        raise ValueError('missing exercised admission policy')
    quotas = sorted({r['quota'] for r in records if r['absent']})
    # There is no epoch at the raw MCU tracepoint, so only claim an
    # exact quota audit when every observed absence uses the same quota.
    quota = quotas[0] if len(quotas) == 1 else None
    lo, hi = trace['offset_lo'], trace['offset_hi']
    windows = []
    for w in timing['windows'] + timing.get('isolated_unattributed_multichannel', []):
        span = w['common_arrival_silence']
        start, end = D(span['last_reply']), D(span['next_reply'])
        if end-start < D('.25') or not any(p['missing_sequences'] for p in w['paths']):
            continue
        if start < trace['first_anchor']+hi or end > trace['last_anchor']+lo:
            continue
        counts = Counter(kind for t, kind, _ in entries if start <= t+lo and t+hi <= end)
        windows.append(dict(label=w.get('label', 'unattributed-multichannel'),
                            frequencies_mhz=w['frequencies_mhz'], duration_s=end-start,
                            counts=dict(counts)))
    definite = [a['ticket'] for a in accounts if quota is not None and a['peak_lower'] > quota]
    ambiguous = [a['ticket'] for a in accounts if quota is not None and a['peak_lower'] <= quota < a['peak_upper']]
    return dict(trace_events=trace['trace_count'], clock_uncertainty_s=hi-lo,
                absence_quotas=quotas, uniform_quota=quota, counts=dict(total),
                epochs=len(accounts), definite_overspent_epochs=definite,
                timestamp_tie_ambiguous_epochs=ambiguous, accounts=accounts, windows=windows,
                method='Reservations/refunds are attempts, not unique packets. Exact budget comparison requires uniform observed quota; raw MCU timestamps do not establish the handler epoch. Peaks bound equal-timestamp ordering.')


def selftest():
    def ev(t, kind, payload):
        return D(t), kind, 'test', payload, 0
    def c(t, ticket, allowed=1):
        return ev(t, CREDIT, f'wcid=1 link=1 allowed={allowed} ticket={ticket}')
    def r(t, ticket, restored=1):
        return ev(t, REFUND, f'ticket={ticket} restored={restored}')
    _, counts, accounts = ledger([c(1,257),c(2,257),r(2,257),c(2,257),c(3,0,0),r(4,257,0),c(5,513)])
    assert counts == {'charged':4,'restored':1,'denied':1,'stale_refund':1}
    assert accounts[0]['balance'] == 2 and accounts[0]['peak_lower'] == 2 and accounts[0]['peak_upper'] == 3
    assert accounts[1]['epoch'] == 2 and accounts[1]['balance'] == 1
    for invalid in ([r(1,257)], [c(1,257,0)], [c(1,256)], [c(1,257),r(2,257),r(3,257,0)]):
        try:
            ledger(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid ledger accepted')
    print('CLIENT_CREDIT_SELFTEST_PASS')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('trace', type=Path, nargs='?')
    p.add_argument('timing', type=Path, nargs='?')
    p.add_argument('--selftest', action='store_true')
    a = p.parse_args()
    if a.selftest:
        selftest()
    else:
        if a.trace is None or a.timing is None:
            p.error('supply trace and timing report')
        print(json.dumps(analyze(absence.trace.parse(a.trace.read_text()), json.loads(a.timing.read_text())), indent=2, default=str))
