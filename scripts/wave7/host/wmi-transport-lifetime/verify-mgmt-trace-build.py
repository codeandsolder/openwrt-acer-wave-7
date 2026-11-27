#!/usr/bin/env python3
"""Reject registered-but-compiled-out management lifetime tracepoints."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

CALLERS = {
    'drivers/net/wireless/ath/ath12k/mac.o': 'ath12k_mgmt_lifetime',
    'drivers/net/wireless/ath/ath12k/wmi.o': 'ath12k_mgmt_lifetime',
    'net/mac80211/cfg.o': 'ack_status_lifetime',
    'net/mac80211/tx.o': 'ack_status_lifetime',
    'net/mac80211/status.o': 'ack_status_lifetime',
}
DEFINITIONS = {
    'drivers/net/wireless/ath/ath12k/mgmt_trace.o': 'ath12k_mgmt_lifetime',
    'net/mac80211/trace.o': 'ack_status_lifetime',
    'drivers/net/wireless/ath/ath12k/ath12k.ko': 'ath12k_mgmt_lifetime',
    'net/mac80211/mac80211.ko': 'ack_status_lifetime',
}

def inspect(root, readelf, nm):
    report = []
    for objects, reference in ((CALLERS, True), (DEFINITIONS, False)):
        for name, event in objects.items():
            path = root / name
            symbol = '__tracepoint_' + event
            if reference:
                output = subprocess.check_output([readelf, '-rW', str(path)], text=True)
                found = any(symbol in line.split() for line in output.splitlines())
            else:
                output = subprocess.check_output([nm, '--defined-only', str(path)], text=True)
                found = any(line.split()[-1:] == [symbol] for line in output.splitlines())
            report.append(dict(object=name, symbol=symbol, kind='relocation' if reference else 'definition',
                               present=found, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--readelf', default='readelf')
    parser.add_argument('--nm', default='nm')
    args = parser.parse_args()
    records = inspect(args.source, args.readelf, args.nm)
    valid = all(row['present'] for row in records)
    print(json.dumps(dict(valid=valid, checks=records), indent=2))
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())
