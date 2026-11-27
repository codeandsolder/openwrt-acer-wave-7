#!/usr/bin/env python3
"""Compare independently clocked authorization windows at lab data boundaries."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

LINE = re.compile(r"\[\d+\]\s+\S+\s+(\d+\.\d+): (\w+): (.*)")
FIELD = re.compile(r"(\w+)=([^\s]+)")
STATE = re.compile(r"\bsta:([0-9a-f:]+) state: (\d+)->(\d+)")
LOSS = re.compile(r"^(?:overrun|commit overrun|dropped events):\s*(\d+)$", re.M)
NET = {
    "net_dev_start_xmit", "netif_receive_skb_entry",
    "netif_receive_skb_list_entry", "napi_gro_receive_entry", "netif_rx_entry",
}
RX = {"mt7925_lab_rxdesc", "mt7925_lab_rx_frame", "mt7925_lab_txs_peer_data",
      "mt7925_lab_absence"}
PROTOCOLS = {0x800: "IPv4", 0x806: "ARP", 0x86dd: "IPv6"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_seal(path):
    seen = set()
    for line in (path / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.removeprefix("./")
        require("/" not in name and name not in seen, "invalid seal path")
        with (path / name).open("rb") as f:
            require(hashlib.file_digest(f, "sha256").hexdigest() == digest,
                    f"seal mismatch: {name}")
        seen.add(name)
    return seen


def parse_trace(text, side, min_associations=2, allow_open_peer=False):
    marker = {"client": "CLIENT_CONTROL_TRACE", "ap": "AP_CONTROL_TRACE"}[side]
    require(text.count(marker + "_READY ") == 1 and
            text.count(marker + "_END rc=0") == 1, f"{side}: incomplete trace")
    loss = LOSS.findall(text)
    require(loss and len(loss) % 3 == 0 and not any(map(int, loss)),
            f"{side}: trace losses or missing stats")
    windows = []
    active = {}
    observations = []
    wtbl = []
    last_time = 0.0
    for line in text.splitlines():
        m = LINE.search(line)
        if not m:
            continue
        timestamp, event, body = m.groups()
        time = float(timestamp)
        last_time = max(last_time, time)
        if event == "drv_sta_state":
            state = STATE.search(body)
            require(state, f"{side}: malformed station state")
            address, old, new = state.groups()
            if old == "3" and new == "4":
                require(address not in active, f"{side}: duplicate authorization")
                active[address] = time
            elif old == "4" and new == "3":
                require(address in active, f"{side}: unpaired deauthorization")
                windows.append((active.pop(address), time, address, True))
        elif event == "mt7925_lab_wtbl_peer":
            fields = dict(FIELD.findall(body))
            dw28 = int(fields["dw28"], 16)
            # MediaTek MT7925 CODA wf_ds_lwtbl.h, DW28/DW29.
            related = [{"wcid": (dw28 >> shift) & 0xfff,
                        "band": (dw28 >> (shift + 12)) & 3}
                       for shift in (0, 16)]
            wtbl.append({"time": time, "stage": int(fields["stage"]),
                         "wcid": int(fields["wcid"]), "link": int(fields["link"]),
                         "bss": int(fields["bss"]), "host_band": int(fields["host_band"]),
                         "hardware_band": (int(fields["dw0"], 16) >> 26) & 3,
                         "valid_peer": bool((int(fields["dw0"], 16) >> 28) & 1),
                         "cipher": int(fields["cipher"]),
                         "own_mld_id": int(fields["mld"]), "dw28": fields["dw28"],
                         "related": related,
                         "primary_mld_band": (dw28 >> 14) & 3,
                         "secondary_mld_band": (dw28 >> 30) & 3})
        elif event in NET | RX:
            fields = dict(FIELD.findall(body))
            if event in NET:
                dev = fields["dev"]
                allowed = {"wlp2s0"} if side == "client" else {"ap-mld0", "br-lan"}
                protocol = int(fields["protocol"], 16)
                require(dev in allowed and protocol in PROTOCOLS, f"{side}: bad filter")
                key = (event, dev, PROTOCOLS[protocol], fields["len"])
            elif event == "mt7925_lab_rxdesc":
                key = (event, fields["result"], fields["resolved_wcid"],
                       fields["link"], fields["valid"], fields["freq"], fields["encap"])
            elif event == "mt7925_lab_rx_frame":
                require(fields["data"] == "1", "non-data RX frame")
                key = (event, fields["wcid"], fields["freq"], fields["raw_bss"],
                       fields["encap"], fields["u2m"])
            elif event == "mt7925_lab_txs_peer_data":
                key = (event, fields["wcid"], fields["link"], fields["band"],
                       fields["ack_error"], fields["encap"])
            else:
                key = (event, fields["bss"], fields["absent"], fields["quota"])
            observations.append((time, key))
    require(not active or allow_open_peer, f"{side}: unclosed authorized peer lifetime")
    for address, start in active.items():
        windows.append((start, last_time, address, False))
    require(len(windows) >= min_associations,
            f"{side}: insufficient authorized lifetimes: {len(windows)} < {min_associations}")
    windows.sort()
    require(len({w[2] for w in windows}) == 1, f"{side}: unrelated stations in trace")
    # Count every tracepoint separately; RX paths may see the same skb at
    # multiple layers. Counts are not unique packets or RF transmission counts.
    results = []
    for start, stop, address, closed in windows:
        require(stop > start, f"{side}: inverted window")
        rows = {}
        for name, end in (("first_2s", min(stop, start + 2)),
                          ("first_8s", min(stop, start + 8)),
                          ("whole", stop)):
            counts = Counter()
            first = {}
            last = {}
            for timestamp, key in observations:
                if start <= timestamp < end or (not closed and timestamp == end == stop):
                    counts[key] += 1
                    first[key] = min(first.get(key, timestamp), timestamp)
                    last[key] = max(last.get(key, timestamp), timestamp)
            rows[name] = [
                {"fields": list(key), "count": count,
                 "first_s": round(first[key] - start, 6),
                 "last_s": round(last[key] - start, 6)}
                for key, count in sorted(counts.items())
            ]
        result = {"authorized_at": start,
                  "deauthorized_at": stop if closed else None,
                  "observed_until": stop, "right_censored": not closed,
                  "duration_s": stop - start, "station": address, **rows}
        if side == "client":
            result["wtbl"] = [row for row in wtbl if start <= row["time"] < stop]
        results.append(result)
    require(any(row["fields"][0] in NET for row in results[0]["whole"]),
            f"{side}: initial association lacks net trace")
    if side == "client":
        require(any(row["fields"][0] == "mt7925_lab_rx_frame"
                    for row in results[0]["whole"]), "missing initial RX-frame trace")
    return results



def data_token_submissions(text):
    """Pair each submitted descriptor with its eventual token return."""
    events = []
    for line in text.splitlines():
        m = LINE.search(line)
        if m and m[2] in {"mt7925_lab_data_txd", "mt7925_lab_data_tx_free"}:
            events.append((float(m[1]), m[2], dict(FIELD.findall(m[3]))))
    pending = {}
    submissions = []
    unmatched_free = 0
    for time, event, fields in sorted(events, key=lambda row: row[0]):
        cookie = fields["cookie"]
        require(cookie not in {"0000000000000000", "(null)"}, "invalid skb cookie")
        if event == "mt7925_lab_data_txd":
            require(cookie not in pending, "duplicate outstanding skb cookie")
            row = {"submitted_at": time, **fields}
            submissions.append(row)
            pending[cookie] = row
        else:
            row = pending.pop(cookie, None)
            if row is None:
                # Return tracing also covers data outside the MLD station.
                unmatched_free += 1
                continue
            require(row["wcid"] == fields["desc_wcid"], "descriptor WCID mismatch")
            header = int(fields["header"], 16)
            row["return"] = {
                "time": time,
                "latency_ms": round((time - row["submitted_at"]) * 1000, 3),
                **fields,
                "header_count": (header >> 24) & 15 if fields["header_valid"] == "1" else None,
                "header_status": (header >> 28) & 3 if fields["header_valid"] == "1" else None,
            }
    return submissions, unmatched_free


def teardown_tx_windows(control, lifecycle, windows):
    """Match protected deauth/disassoc descriptors and status in local time.

    A successful TX status is not itself proof that the AP retired the peer.
    ROC evidence is positive-only because lifecycle and control are separate
    streams; a missing grant must not be interpreted as a rejected grant.
    """
    events = []
    for line in control.splitlines():
        m = LINE.search(line)
        if m and m[2] in {'mt7925_lab_mgmt_txd', 'mt7925_lab_mgmt_txs',
                          'mt7925_lab_mgmt_tx_free'}:
            f = dict(FIELD.findall(m[3]))
            fc = int(f['fc'], 16)
            if fc & 0x4000 and fc & 0x00fc in (0x00a0, 0x00c0):
                events.append((float(m[1]), m[2], f))
    rows, latest, unmatched = [], {}, []
    for t, name, f in sorted(events, key=lambda e: e[0]):
        cookie = f['cookie']
        key = (cookie, f['seq'], f['fc'])
        if name == 'mt7925_lab_mgmt_txd':
            require(cookie not in {'0000000000000000', '(null)'}, 'invalid management cookie')
            require(key not in latest or 'return' in latest[key], 'duplicate live teardown descriptor')
            row = dict(f, submitted_at=t)
            rows.append(row)
            latest[key] = row
            continue
        row = latest.get(key)
        if row is None:
            unmatched.append(dict(f, event=name, time=t))
            continue
        if name == 'mt7925_lab_mgmt_tx_free':
            require('return' not in row and f['desc_wcid'] == row['wcid'],
                    'duplicate/mismatched teardown return')
            header = int(f['header'], 16)
            row['return'] = dict(f, time=t, latency_ms=round((t-row['submitted_at'])*1000, 3),
                                 count=(header >> 24) & 15 if f['header_valid'] == '1' else None)
        else:
            require(f['wcid'] == row['wcid'] and f['link'] == row['link'], 'teardown TXS identity mismatch')
            row.setdefault('tx_status', []).append(dict(f, time=t,
                latency_ms=round((t-row['submitted_at'])*1000, 3)))
    grants = []
    active = {}
    if lifecycle:
        events = []
        for line in lifecycle.splitlines():
            m = LINE.search(line)
            if m and m[2] in {'mt7925_lab_roc_wire', 'mt7925_lab_roc_sync', 'mt7925_lab_roc_abort'}:
                events.append((float(m[1]), m[2], dict(FIELD.findall(m[3]))))
        for t, name, f in sorted(events, key=lambda e: e[0]):
            key = (f['bss'], f['token'])
            if name == 'mt7925_lab_roc_wire':
                # Any new grant using this token invalidates an old generation.
                active.pop(key, None)
                if f['type'] == '2' and f['status'] == '0' and f['token'] == f['expected']:
                    row = dict(f, granted_at=t)
                    active[key] = row
                    grants.append(row)
            elif name == 'mt7925_lab_roc_sync':
                if key in active and f['phase'] == '1' and f['granted'] == '1' and f['result'] == '0':
                    active[key]['confirmed_at'] = t
            elif key in active:
                row = active.pop(key)
                row['abort'] = dict(f, time=t)
    for row in rows:
        t = row['submitted_at']
        # A grant must be confirmed before TX and have a matching successful
        # exact-band abort after it. Never guess which of multiple grants owns TX.
        candidates = [g for g in grants if g.get('confirmed_at', float('inf')) <= t
                      and g['dbdc'] == row['band'] and 'abort' in g
                      and g['abort']['time'] >= t and g['abort']['band'] == row['band']
                      and g['abort']['result'] == '0']
        row['privilege_witness'] = candidates[0] if len(candidates) == 1 else None
        row['privilege_candidates'] = len(candidates)
        row['acked'] = any(x['ack_error'] == '0' for x in row.get('tx_status', []))
    per_window = []
    for w in windows:
        matches = [r for r in rows if w['authorized_at'] <= r['submitted_at'] < w['observed_until']]
        per_window.append({'authorized_at': w['authorized_at'], 'frames': matches,
                           'acked': sum(r['acked'] for r in matches),
                           'zero_attempts': sum(r.get('return', {}).get('count') == 0 for r in matches)})
    return {'windows': per_window, 'unassigned': [r for r in rows if not any(
            w['authorized_at'] <= r['submitted_at'] < w['observed_until'] for w in windows)],
            'unmatched': unmatched}


def token_windows(text, windows):
    submissions, unmatched_free = data_token_submissions(text)
    result = []
    for window in windows:
        start, stop = window["authorized_at"], window["deauthorized_at"]
        rows = [row for row in submissions if start <= row["submitted_at"] < stop]
        counts = Counter()
        for row in rows:
            returned = row.get("return")
            key = (row["protocol"], row["wcid"], row["band"],
                   "missing" if returned is None else str(returned["header_count"]),
                   "missing" if returned is None else
                   "after_deauthorize" if returned["time"] >= stop else "before_deauthorize")
            counts[key] += 1
        result.append({
            "authorized_at": start, "deauthorized_at": stop,
            "submitted": len(rows),
            "returned": sum("return" in row for row in rows),
            "groups": [{"fields": list(key), "count": count}
                       for key, count in sorted(counts.items())],
            "descriptors": rows,
        })
    return {"unmatched_free": unmatched_free, "windows": result}

def startup_tx_windows(text, token_report):
    """Report contiguous nonempty firmware-token periods after authorization.

    A period is based on actual outstanding descriptors, not a latency
    threshold or assumed correspondence between an absence event and RF TX.
    Include both host-TXS-requested and other data, exclude EAPOL.
    Follow periods starting within the existing first-8s analysis window
    until they drain or authorization ends.
    """
    absence = []
    for line in text.splitlines():
        m = LINE.search(line)
        if m and m[2] == "mt7925_lab_absence":
            fields = dict(FIELD.findall(m[3]))
            absence.append(dict(time=float(m[1]), **fields))
    absence.sort(key=lambda e: e["time"])
    results = []
    for window in token_report["windows"]:
        start, stop = window["authorized_at"], window["deauthorized_at"]
        horizon = min(start + 8, stop)
        events = []
        for i, d in enumerate(window["descriptors"]):
            if int(d["protocol"], 16) not in PROTOCOLS:
                continue
            events.append((d["submitted_at"], 0, i, d))
            if "return" in d and d["return"]["time"] < stop:
                events.append((d["return"]["time"], 1, i, d))
        pending = set()
        episodes = []
        current = None
        for time, phase, i, d in sorted(events, key=lambda e: e[:3]):
            if phase == 0:
                if not pending:
                    if time >= horizon:
                        break
                    current = {"start": time, "first_return": None,
                               "submitted": 0, "returned": 0, "peak_pending": 0,
                               "host_status_requested": 0, "host_status_not_requested": 0,
                               "unknown_status_request": 0, "protocols": Counter(),
                               "bands": Counter(), "zero_attempts": 0}
                require(current is not None, "missing startup episode")
                pending.add(i)
                current["submitted"] += 1
                current["peak_pending"] = max(current["peak_pending"], len(pending))
                current["protocols"][PROTOCOLS[int(d["protocol"], 16)]] += 1
                current["bands"][d["band"]] += 1
                if "d5" not in d:
                    current["unknown_status_request"] += 1
                elif int(d["d5"], 16) & (1 << 10):  # MT_TXD5_TX_STATUS_HOST
                    current["host_status_requested"] += 1
                else:
                    current["host_status_not_requested"] += 1
            else:
                require(i in pending and current is not None, "startup token return without submit")
                pending.remove(i)
                if current["first_return"] is None:
                    current["first_return"] = time
                    current["pending_at_first_return"] = len(pending) + 1
                current["returned"] += 1
                current["zero_attempts"] += d["return"]["header_count"] == 0
                if not pending:
                    current["end"] = time
                    current["right_censored"] = False
                    episodes.append(current)
                    current = None
        if current is not None:
            current["end"] = stop
            current["right_censored"] = True
            episodes.append(current)
        for e in episodes:
            e["duration_ms"] = round((e["end"] - e["start"]) * 1000, 3)
            e["first_return_ms"] = (None if e["first_return"] is None else
                                    round((e["first_return"] - e["start"]) * 1000, 3))
            e["drain_ms"] = (None if e["first_return"] is None or e["right_censored"] else
                             round((e["end"] - e["first_return"]) * 1000, 3))
            e["absence_during"] = [a for a in absence if e["start"] <= a["time"] <= e["end"]]
        results.append({"authorized_at": start, "analysis_horizon": horizon,
                        "episodes": episodes})
    return results


def control_port_windows(text, windows):
    """Report PAE descriptor completion relative to host authorization.

    cfg80211 cookies are a different namespace from skb cookies. Keep
    cfg80211 request/status events as independent timestamped evidence;
    never pair them by assuming FIFO status delivery.
    """
    submissions, _ = data_token_submissions(text)
    control = []
    starts = []
    for line in text.splitlines():
        m = LINE.search(line)
        if not m:
            continue
        time, event, body = m.groups()
        time = float(time)
        if event == "drv_sta_state":
            state = STATE.search(body)
            if state and state.group(2, 3) == ("0", "1"):
                starts.append(time)
        elif event == "rdev_tx_control_port" and "proto: 0x888e" in body:
            control.append({"time": time, "event": "request"})
        elif event == "cfg80211_rx_control_port" and "proto: 0x888e" in body:
            match = re.search(r"len=(\d+).*link: (-?\d+)", body)
            require(match, "malformed control-port RX")
            control.append({"time": time, "event": "receive",
                            "length": int(match[1]), "link": int(match[2])})
        elif event == "cfg80211_control_port_tx_status":
            match = re.search(r"cookie: (\d+), ack: (true|false)", body)
            require(match, "malformed control-port status")
            control.append({"time": time, "event": "status",
                            "cookie": int(match[1]), "acked": match[2] == "true"})
    result = []
    for i, window in enumerate(windows):
        auth, stop = window["authorized_at"], window["deauthorized_at"]
        preceding = [t for t in starts if t <= auth]
        if not preceding:
            continue
        start = preceding[-1]
        next_start = min((t for t in starts if t > auth), default=float("inf"))
        pae = [row for row in submissions if row["protocol"] == "0x888e"
               and start <= row["submitted_at"] < stop]
        pending = [row for row in pae if row["submitted_at"] < auth and
                   ("return" not in row or row["return"]["time"] >= auth)]
        result.append({"start": start, "authorized_at": auth,
                       "pre_authorize_pending": len(pending),
                       "descriptors": pae,
                       "control_events": [row for row in control
                                          if start <= row["time"] < next_start]})
    return result


def mld_records(text):
    """Keep snapshots outside authorization windows, including teardown."""
    records = []
    current = None
    for line in text.splitlines():
        m = LINE.search(line)
        if not m or m[2] not in {
            "mt7925_lab_mld_record_result", "mt7925_lab_mld_record",
            "mt7925_lab_mld_record_link",
        }:
            continue
        time, event, body = m.groups()
        fields = {k: int(v) for k, v in FIELD.findall(body)}
        if event.endswith("_result"):
            if current is not None:
                check_mld_record(current)
            current = {"time": float(time), "query_band": 0, **fields, "links": []}
            records.append(current)
        else:
            require(current is not None and current["ret"] == 0 and
                    current["stage"] == fields.pop("stage"),
                    "unpaired MLD record")
            if event.endswith("_link"):
                current["links"].append(fields)
            else:
                require("record" not in current, "duplicate MLD record")
                current["record"] = fields
    if current is not None:
        check_mld_record(current)
    return records


def check_mld_record(row):
    if row["ret"] == 0:
        require("record" in row and row["record"]["index"] == 0 and
                sorted(link["slot"] for link in row["links"]) == [0, 1],
                "incomplete MT7925 MLD record")
    else:
        require("record" not in row and not row["links"],
                "failed MLD query has payload")


def mld_command_windows(lifecycle, control, windows):
    """Compare metadata emitted for actual MLD MCU commands, not TX contents."""
    require(lifecycle.count("CRASH_STREAM_END rc=0") == 1,
            "incomplete lifecycle trace")
    loss = LOSS.findall(lifecycle)
    require(loss and len(loss) % 3 == 0 and not any(map(int, loss)),
            "lifecycle trace losses or missing stats")
    boot = re.search(r"STACK_CANDIDATE_PASS .* boot=([0-9a-f-]+)", lifecycle)
    control_boot = re.search(r"CLIENT_CONTROL_TRACE_READY boot=([0-9a-f-]+)", control)
    require(boot and control_boot and boot[1] == control_boot[1],
            "lifecycle/control boot mismatch")
    require(re.search(r"CRASH_STREAM_CLOCK .*\[mono\]", lifecycle),
            "lifecycle clock is not monotonic")
    starts = []
    for line in control.splitlines():
        m = LINE.search(line)
        if m and m[2] == "drv_sta_state":
            state = STATE.search(m[3])
            if state and state.group(2, 3) == ("0", "1"):
                starts.append(float(m[1]))
    events = []
    kinds = {"mt7925_lab_bss_mld", "mt7925_lab_sta_mld_slot",
             "mt7925_lab_sta_mld_update", "mt7925_lab_sta_eht_mld"}
    for line in lifecycle.splitlines():
        m = LINE.search(line)
        if m and m[2] in kinds:
            events.append((float(m[1]), m[2], dict(FIELD.findall(m[3]))))
    rows = []
    for window in windows:
        auth, stop = window["authorized_at"], window["deauthorized_at"]
        preceding = [t for t in starts if t <= auth]
        if not preceding:
            continue
        start = preceding[-1]
        commands = [{"event": event, "fields": fields}
                    for time, event, fields in events if start <= time < stop]
        groups = sorted({int(c["fields"]["group"]) for c in commands
                         if c["event"] == "mt7925_lab_bss_mld"})
        rows.append({"authorized_at": auth, "commands": commands,
                     "bss_group_ids": groups})

    def without_bss_group(row):
        return [{"event": c["event"], "fields": {
            key: value for key, value in c["fields"].items()
            if not (c["event"] == "mt7925_lab_bss_mld" and key == "group")}}
                for c in row["commands"]]

    reset_observed = bool(re.search(r"^CRASH_PROBE_FORMAT reset_work$", lifecycle, re.M))
    resets = []
    if reset_observed:
        for line in lifecycle.splitlines():
            m = LINE.search(line)
            if m and m[2] == "reset_work":
                resets.append(float(m[1]))
    return {"windows": rows,
            "firmware_reset_work": resets if reset_observed else None,
            "same_sequence": len(rows) >= 2 and
                             all(r["commands"] == rows[0]["commands"] for r in rows[1:]),
            "same_sequence_except_bss_group": len(rows) >= 2 and all(
                without_bss_group(r) == without_bss_group(rows[0]) for r in rows[1:])}


def band_group_refresh_windows(lifecycle, control, windows):
    """Match BSS BASIC, optional MLD tag and synchronous ACK by lifetime.

    Only a successful update between two concrete hardware bands counts
    as migration. An AUTO assignment or a different peer is not a move.
    """
    starts = []
    for line in control.splitlines():
        m = LINE.search(line)
        if m and m[2] == "drv_sta_state":
            state = STATE.search(m[3])
            if state and state.group(2, 3) == ("0", "1"):
                starts.append(float(m[1]))
    kinds = {"mt7925_lab_bss_basic", "mt7925_lab_bss_mld",
             "mt7925_lab_bss_result", "mt7925_lab_sta_mld_update"}
    events = [(float(m[1]), m[2], {k: int(v) for k, v in FIELD.findall(m[3])})
              for line in lifecycle.splitlines() if (m := LINE.search(line))
              and m[2] in kinds]
    rows = []
    for window in windows:
        auth, stop = window["authorized_at"], window["deauthorized_at"]
        start = max((t for t in starts if t <= auth), default=None)
        relevant = [e for e in events if start is not None and start <= e[0] < stop]
        pending, previous, moves = {}, {}, []
        for t, kind, f in relevant:
            if kind == "mt7925_lab_sta_mld_update":
                continue
            key = (f["bss"], f["link"])
            if kind == "mt7925_lab_bss_basic":
                pending[key] = {"time": t, "basic": f, "tags": []}
            elif kind == "mt7925_lab_bss_mld" and key in pending:
                pending[key]["tags"].append({"time": t, **f})
            elif kind == "mt7925_lab_bss_result" and key in pending:
                request = pending.pop(key)
                basic = request["basic"]
                if (f["result"] != 0 or f["wcid"] != basic["peer"]
                        or f["enabled"] != basic["enabled"]):
                    continue
                # Disconnect or reassignment of the BSS invalidates
                # its previous concrete peer-band binding.
                old = previous.pop(key, None)
                if not basic["enabled"] or not basic.get("active") or basic.get("peer_link") == 255:
                    continue
                if basic["band"] not in (0, 1):
                    continue
                previous[key] = basic
                if (old is None or old["peer"] != basic["peer"]
                        or old["band"] == basic["band"]):
                    continue
                tags = request["tags"]
                first_sta = min((time for time, event, fields in relevant
                                 if event == "mt7925_lab_sta_mld_update"
                                 and time >= request["time"]), default=None)
                moves.append({"bss": key[0], "link": key[1], "wcid": basic["peer"],
                              "from_band": old["band"], "to_band": basic["band"],
                              "basic_at": request["time"], "ack_at": t, "mld_tags": tags,
                              "first_sta_mld_update_at": first_sta,
                              "group_refresh_before_sta": len(tags) == 1 and
                              first_sta is not None and request["time"] <= tags[0]["time"]
                              <= t < first_sta})
        rows.append({"authorized_at": auth, "migrations": moves})
    return rows


def band_retirement_windows(lifecycle, control, windows):
    """Observe peer disconnect, station removal and DEV deactivation in order.

    Called only after the lifecycle/control trace clock and boot checks.
    Missing witnesses are distinct from a wrong band or a failed command.
    """
    starts = []
    for line in control.splitlines():
        m = LINE.search(line)
        if m and m[2] == "drv_sta_state":
            state = STATE.search(m[3])
            if state and state.group(2, 3) == ("0", "1"):
                starts.append(float(m[1]))
    kinds = {"mt7925_lab_bss_basic", "mt7925_lab_bss_result",
             "mt7925_lab_sta_result", "mt7925_lab_band_retire",
             "mt7925_lab_bss_mld", "mt7925_lab_chanctx_unassign",
             "mt7925_lab_group_retire", "mt7925_lab_group_detach_active"}
    events = []
    for line in lifecycle.splitlines():
        m = LINE.search(line)
        if m and m[2] in kinds:
            fields = dict(FIELD.findall(m[3]))
            events.append((float(m[1]), m[2],
                           {key: int(value) for key, value in fields.items()}))
    result = []
    for window in windows:
        stop = window["deauthorized_at"]
        end = min((t for t in starts if t > stop), default=float("inf"))
        peers = [p for p in window["wtbl"] if p["stage"] == 7]
        details = []
        for peer in peers:
            bss, link, wcid = peer["bss"], peer["link"], peer["wcid"]
            band = peer["host_band"]
            relevant = [(t, kind, f) for t, kind, f in events
                        if stop <= t < end and f["bss"] == bss and f["link"] == link]

            def matching(kind, predicate):
                return [{"time": t, **f} for t, event, f in relevant
                        if event == kind and predicate(f)]

            disconnect = matching("mt7925_lab_bss_basic",
                                  lambda f: not f["enabled"] and f["peer"] == wcid)
            bss_ack = matching("mt7925_lab_bss_result",
                               lambda f: not f["enabled"] and f["wcid"] == wcid)
            remove = matching("mt7925_lab_sta_result",
                              lambda f: not f["enabled"] and f["wcid"] == wcid)
            dev = matching("mt7925_lab_band_retire", lambda f: True)
            group = matching("mt7925_lab_group_retire", lambda f: True)
            detach = matching("mt7925_lab_group_detach_active", lambda f: True)
            group_complete = None
            if len(remove) == len(group) == 1:
                group_complete = (remove[0]["result"] == group[0]["result"] == 0
                                  and group[0]["was_active"] == 1
                                  and remove[0]["time"] <= group[0]["time"])
            # Absence or ambiguity is not positive proof of retirement.
            bss_band_ok = (disconnect[0]["band"] == band
                           if len(disconnect) == 1 else None)
            dev_band_ok = (dev[0]["band"] == band if len(dev) == 1 else None)
            complete = None
            if all(len(rows) == 1 for rows in (disconnect, bss_ack, remove, dev)):
                complete = (bss_band_ok and dev_band_ok and dev[0]["was_active"] == 1
                            and all(rows[0]["result"] == 0 for rows in (bss_ack, remove, dev))
                            and disconnect[0]["time"] <= bss_ack[0]["time"]
                            <= remove[0]["time"] <= dev[0]["time"])
            details.append({"bss": bss, "link": link, "wcid": wcid,
                            "expected_band": band, "bss_disconnect": disconnect,
                            "bss_ack": bss_ack, "station_remove": remove,
                            "dev_retire": dev, "bss_band_matches": bss_band_ok,
                            "dev_band_matches": dev_band_ok, "complete": complete,
                            "group_retire": group, "group_retire_complete": group_complete,
                            "active_detach": detach})
        removed_at = None
        if details and all(len(p["station_remove"]) == 1 and
                           p["station_remove"][0]["result"] == 0 for p in details):
            removed_at = max(p["station_remove"][0]["time"] for p in details)
        # Every peer remove must succeed before any standalone detach,
        # and every standalone detach before either BSS/DEV is retired.
        active_detach_complete = None
        if details and all(len(p["station_remove"]) == len(p["active_detach"])
                           == len(p["group_retire"]) == 1 for p in details):
            removes = [p["station_remove"][0] for p in details]
            detaches = [p["active_detach"][0] for p in details]
            retires = [p["group_retire"][0] for p in details]
            active_detach_complete = (
                all(e["result"] == 0 for e in removes + detaches + retires)
                and all(e["was_active"] == 1 for e in detaches + retires)
                and max(e["time"] for e in removes) <= min(e["time"] for e in detaches)
                and max(e["time"] for e in detaches) <= min(e["time"] for e in retires))
        late = []
        unassign = []
        if removed_at is not None:
            tail = [(t, event, f) for t, event, f in events if removed_at <= t < end]
            for i, (t, event, f) in enumerate(tail):
                if event == "mt7925_lab_chanctx_unassign":
                    unassign.append({"time": t, **f})
                if (event != "mt7925_lab_bss_basic" or f["enabled"] or
                        not f.get("active") or f.get("peer_link") != 255 or
                        f.get("conn_state") != 1):
                    continue
                # Match the MLD tag and ACK belonging to this particular
                # BASIC update; do not assume every late BASIC carries MLD.
                tags = []
                replies = []
                for t2, e2, f2 in tail[i + 1:]:
                    if f2["bss"] != f["bss"] or f2["link"] != f["link"]:
                        continue
                    if e2 == "mt7925_lab_bss_basic":
                        break
                    if e2 == "mt7925_lab_bss_mld":
                        tags.append({"time": t2, **f2})
                    if (e2 == "mt7925_lab_bss_result" and not f2["enabled"] and
                            f2["wcid"] == f["peer"]):
                        replies.append({"time": t2, **f2})
                late.append({"time": t, **f, "mld_tags": tags, "acks": replies})
        result.append({"authorized_at": window["authorized_at"],
                       "deauthorized_at": stop, "peers": details,
                       "all_peers_removed_at": removed_at,
                       "active_detach_complete": active_detach_complete,
                       "late_active_bss_updates": late if removed_at is not None else None,
                       "chanctx_unassignments": unassign if removed_at is not None else None})
    return result


def wtbl_pair_bindings(windows):
    """Check the dual-link peer table independently of scheduler records.

    The related-index slots describe other peers, not the current peer.
    Compare their concrete WCID and band against the other active peer.
    This diagnostic deliberately does not assert any fixed group ID.
    """
    result = []
    for window in windows:
        final = [r for r in window["wtbl"] if r["stage"] == 7]
        if len(final) != 2 or len({r["link"] for r in final}) != 2:
            result.append({"authorized_at": window["authorized_at"],
                           "complete_pair": None})
            continue
        details = []
        for peer, other in (final, final[::-1]):
            refs = [r for r in peer["related"] if r["wcid"] != 4095]
            wanted = {"wcid": other["wcid"], "band": other["host_band"]}
            valid = (peer["valid_peer"] and
                     peer["hardware_band"] == peer["host_band"] and
                     peer["own_mld_id"] == other["own_mld_id"] and
                     refs == [wanted])
            details.append({"link": peer["link"], "wcid": peer["wcid"],
                            "hardware_band": peer["hardware_band"],
                            "own_mld_id": peer["own_mld_id"],
                            "related": refs, "expected_related": wanted,
                            "bound": valid})
        result.append({"authorized_at": window["authorized_at"],
                       "complete_pair": all(row["bound"] for row in details),
                       "peers": details})
    return result


def mld_transitions(records):
    """Report observed firmware record changes and paired band-query results."""
    changes = []
    paired = []
    previous = None
    baseline = None
    for row in records:
        band = row.get("query_band", 0)
        # Failed queries are missing observations, never inactive records.
        value = None
        if row["ret"] == 0:
            value = {"record": row["record"], "links": sorted(row["links"],
                                                               key=lambda x: x["slot"])}
        if band == 0:
            baseline = row
            if value is None:
                previous = None
                continue
            if value != previous:
                changes.append({"time": row["time"], "stage": row["stage"],
                                "previous": previous, "observed": value})
            previous = value
        elif band == 1:
            require(baseline is not None and baseline["stage"] == row["stage"],
                    "unpaired band query")
            compare = None
            if baseline["ret"] == row["ret"] == 0:
                compare = (baseline["record"] == row["record"] and
                           sorted(baseline["links"], key=lambda x: x["slot"]) ==
                           sorted(row["links"], key=lambda x: x["slot"]))
            paired.append({"stage": row["stage"], "time": row["time"],
                           "reply_band_0": baseline.get("reply_band"),
                           "reply_band_1": row.get("reply_band"),
                           "identical": compare})
            baseline = None
    return {"changes": changes, "band_comparisons": paired}


def mld_lifetimes(records, windows, control=""):
    """Compare firmware scheduler bindings to peer WTBL host-band ownership.

    Do not conflate a correctly populated WTBL with an active scheduler
    record. Keep observed differences as data, not trace-parse failures.
    """
    records = [r for r in records if r.get("query_band", 0) == 0]
    # A new STA lifetime starts at 0->1, not at authorization. Failed
    # preauthorization attempts must not contaminate the previous teardown.
    starts = []
    for line in control.splitlines():
        m = LINE.search(line)
        if m and m[2] == "drv_sta_state":
            state = STATE.search(m[3])
            if state and state.group(2, 3) == ("0", "1"):
                starts.append(float(m[1]))
    result = []
    for i, window in enumerate(windows):
        start, stop = window["authorized_at"], window["deauthorized_at"]
        next_auth = windows[i + 1]["authorized_at"] if i + 1 < len(windows) else float("inf")
        next_start = min((t for t in starts if stop < t <= next_auth), default=next_auth)
        post_keys = [r for r in records if r["stage"] == 7 and start <= r["time"] < stop]
        pre_remove = [r for r in records if r["stage"] == 14 and start <= r["time"] < next_start]
        post_remove = [r for r in records if r["stage"] == 15 and start <= r["time"] < next_start]
        # Require exactly one snapshot of each phase when interpreting a
        # complete MLD lifetime. Missing or failed queries stay explicit.
        wt = [row for row in window["wtbl"] if row["stage"] == 7]
        expected = sorted((row["host_band"], row["wcid"]) for row in wt)
        observed = None
        if len(post_keys) == 1 and post_keys[0]["ret"] == 0:
            observed = sorted((link["band"], link["wcid"]) for link in post_keys[0]["links"]
                              if link["active"])
        retired = None
        if len(post_remove) == 1 and post_remove[0]["ret"] == 0:
            r = post_remove[0]
            retired = (r["record"]["state"] == 0 and r["record"]["active_bitmap"] == 0
                       and r["record"]["active_count"] == 0
                       and not any(link["active"] for link in r["links"]))
        result.append({
            "authorized_at": start,
            "expected_band_wcids": expected,
            "observed_band_wcids": observed,
            "membership_matches": observed == expected if observed is not None and expected else None,
            "record_retired": retired,
            "snapshot_counts": {"post_keys": len(post_keys), "pre_remove": len(pre_remove),
                                "post_remove": len(post_remove)},
        })
    return result


def selftest():
    def line(t, e, body):
        return f"worker [001] ..... {t:.6f}: {e}: {body}\n"

    s = "AP_CONTROL_TRACE_READY boot=x\n"
    for start in (10, 20):
        s += line(start, "drv_sta_state", "sta:aa:bb:cc:dd:ee:ff state: 3->4")
        s += line(start + 0.1, "net_dev_start_xmit",
                  "dev=ap-mld0 protocol=0x0800 len=300")
        s += line(start + 1, "drv_sta_state", "sta:aa:bb:cc:dd:ee:ff state: 4->3")
    s += "overrun: 0\ncommit overrun: 0\ndropped events: 0\nAP_CONTROL_TRACE_END rc=0\n"
    result = parse_trace(s, "ap")
    assert len(result) == 2 and result[1]["whole"][0]["count"] == 1
    third = (line(30, "drv_sta_state", "sta:aa:bb:cc:dd:ee:ff state: 3->4")
             + line(30.1, "net_dev_start_xmit", "dev=ap-mld0 protocol=0x0800 len=300")
             + line(31, "drv_sta_state", "sta:aa:bb:cc:dd:ee:ff state: 4->3"))
    three = s.replace("overrun: 0", third + "overrun: 0", 1)
    assert len(parse_trace(three, "ap", 3)) == 3
    try:
        parse_trace(s, "ap", 3)
    except ValueError:
        pass
    else:
        raise AssertionError("missing third lifetime accepted")
    first_only = "\n".join(l for l in s.splitlines() if "20." not in l and "21." not in l)
    assert len(parse_trace(first_only, "ap", 1)) == 1
    try:
        parse_trace(first_only, "ap")
    except ValueError:
        pass
    else:
        raise AssertionError("missing reassociation accepted")
    open_peer = s.replace(line(21, "drv_sta_state", "sta:aa:bb:cc:dd:ee:ff state: 4->3"), "")
    censored = parse_trace(open_peer, "ap", allow_open_peer=True)[1]
    assert censored["right_censored"] and censored["deauthorized_at"] is None
    assert censored["whole"][0]["count"] == 1
    for broken in (open_peer, s.replace("overrun: 0", "overrun: 1", 1),
                   s.replace("AP_CONTROL_TRACE_END rc=0", ""),
                   s.replace("dev=ap-mld0", "dev=lan1")):
        try:
            parse_trace(broken, "ap")
        except ValueError:
            pass
        else:
            raise AssertionError("bad trace accepted")
    txd = "cookie=00000000abcd1234 protocol=0x0800 wcid=2 band=1"
    free = "cookie=00000000abcd1234 desc_wcid=2 header_valid=1 header=40000000"
    token_trace = line(10.1, "mt7925_lab_data_txd", txd)
    token_trace += line(11.2, "mt7925_lab_data_tx_free", free)
    token_trace += line(20.1, "mt7925_lab_data_txd", txd)
    token_trace += line(20.2, "mt7925_lab_data_tx_free", free)
    tokens = token_windows(token_trace, result)["windows"]
    assert tokens[0]["groups"][0]["fields"][-1] == "after_deauthorize"
    assert tokens[0]["descriptors"][0]["return"]["header_count"] == 0
    assert tokens[1]["returned"] == 1
    rec = line(10, "mt7925_lab_mld_record_result", "stage=14 ret=0")
    rec += line(10, "mt7925_lab_mld_record", "stage=14 index=0 state=1")
    rec += line(10, "mt7925_lab_mld_record_link", "stage=14 slot=0 wcid=2")
    rec += line(10, "mt7925_lab_mld_record_link", "stage=14 slot=1 wcid=0")
    rec += line(11, "mt7925_lab_mld_record_result", "stage=15 ret=-71")
    assert len(mld_records(rec)) == 2
    assert mld_records(rec)[0]["links"][0]["wcid"] == 2
    try:
        mld_records(rec.replace("slot=1", "slot=0"))
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate MLD slot accepted")
    w = [{"authorized_at": 10, "deauthorized_at": 20,
          "wtbl": [{"stage": 7, "host_band": 0, "wcid": 3},
                   {"stage": 7, "host_band": 1, "wcid": 2}]}]
    live = {"time": 11, "stage": 7, "ret": 0,
            "links": [{"band": 0, "wcid": 2, "active": 1},
                      {"band": 1, "wcid": 0, "active": 0}]}
    stale = {"time": 21, "stage": 15, "ret": 0,
             "record": {"state": 1, "active_bitmap": 1, "active_count": 1},
             "links": live["links"]}
    row = mld_lifetimes([live, stale], w)[0]
    assert row["membership_matches"] is False and row["record_retired"] is False
    live["links"] = [{"band": 0, "wcid": 3, "active": 1},
                     {"band": 1, "wcid": 2, "active": 1}]
    stale["record"] = {"state": 0, "active_bitmap": 0, "active_count": 0}
    stale["links"] = [{"active": 0}, {"active": 0}]
    row = mld_lifetimes([live, stale], w)[0]
    assert row["membership_matches"] is True and row["record_retired"] is True
    assert mld_lifetimes([], w)[0]["record_retired"] is None
    assert mld_lifetimes([live, stale, {**stale, "query_band": 1}], w)[0]["record_retired"] is True
    # Subsequent unassociated retries each produce their own snapshots.
    retry = line(30, "drv_sta_state", "sta:aa:bb:cc:dd:ee:ff state: 0->1")
    retry_records = [live, stale, {**stale, "time": 31}]
    assert mld_lifetimes(retry_records, w)[0]["record_retired"] is None
    assert mld_lifetimes(retry_records, w, retry)[0]["record_retired"] is True
    ctl = line(9, "drv_sta_state", "sta:aa:bb:cc:dd:ee:ff state: 0->1")
    ctl += line(9.5, "mt7925_lab_data_txd", txd.replace("0x0800", "0x888e"))
    ctl += line(10.2, "mt7925_lab_data_tx_free", free)
    ctl += line(10.3, "cfg80211_control_port_tx_status", "wdev(1), cookie: 9, ack: false")
    cr = control_port_windows(ctl, [{"authorized_at": 10, "deauthorized_at": 11}])[0]
    assert cr["pre_authorize_pending"] == 1
    assert cr["control_events"][0]["acked"] is False
    assert cr["descriptors"][0]["return"]["header_count"] == 0
    inactive = {"time": 9, "stage": 20, "ret": 0, "query_band": 0,
                "reply_band": 0, "record": {"state": 0}, "links": []}
    created = {**inactive, "stage": 23, "time": 10, "record": {"state": 1}}
    trans = mld_transitions([inactive, {**inactive, "query_band": 1},
                             created, {**created, "query_band": 1},
                             {**created, "stage": 7, "time": 11}])
    assert [x["stage"] for x in trans["changes"]] == [20, 23]
    assert all(x["identical"] for x in trans["band_comparisons"])
    failed = {**inactive, "stage": 22, "ret": -71}
    assert mld_transitions([failed, {**failed, "query_band": 1}])["band_comparisons"][0]["identical"] is None
    assert mld_transitions([inactive, {**created, "stage": 20, "query_band": 1}])["band_comparisons"][0]["identical"] is False
    p = {"stage": 7, "link": 0, "wcid": 2, "host_band": 1,
         "hardware_band": 1, "valid_peer": True, "own_mld_id": 0,
         "related": [{"wcid": 3, "band": 0}, {"wcid": 4095, "band": 2}]}
    q = {**p, "link": 1, "wcid": 3, "host_band": 0, "hardware_band": 0,
         "related": [{"wcid": 2, "band": 1}, {"wcid": 4095, "band": 2}]}
    windows = [{"authorized_at": 10, "wtbl": [p, q]}]
    assert wtbl_pair_bindings(windows)[0]["complete_pair"] is True
    q["own_mld_id"] = 33
    q["related"] = [{"wcid": 4095, "band": 1}, {"wcid": 4095, "band": 2}]
    assert wtbl_pair_bindings(windows)[0]["complete_pair"] is False
    lifecycle = ("STACK_CANDIDATE_PASS variant=fixture boot=abc\n"
                 "CRASH_STREAM_CLOCK [mono]\n"
                 "overrun: 0\ncommit overrun: 0\ndropped events: 0\n"
                 "CRASH_STREAM_END rc=0\n")
    lifecycle += line(10, "mt7925_lab_sta_mld_slot", "target=3 slot=0 count=2")
    lifecycle += line(20, "mt7925_lab_sta_mld_slot", "target=3 slot=0 count=2")
    ctl = "CLIENT_CONTROL_TRACE_READY boot=abc\n"
    ctl += line(9, "drv_sta_state", "sta:aa:bb:cc:dd:ee:ff state: 0->1")
    ctl += line(19, "drv_sta_state", "sta:aa:bb:cc:dd:ee:ff state: 0->1")
    w = [{"authorized_at": t, "deauthorized_at": t+1} for t in (10, 20)]
    assert mld_command_windows(lifecycle, ctl, w)["same_sequence"] is True
    assert mld_command_windows(lifecycle.replace("20.000000: mt7925_lab_sta_mld_slot: target=3",
                                                "20.000000: mt7925_lab_sta_mld_slot: target=4"),
                               ctl, w)["same_sequence"] is False
    groups = lifecycle + line(10, "mt7925_lab_bss_mld", "bss=0 group=0")
    groups += line(20, "mt7925_lab_bss_mld", "bss=0 group=1")
    changed = mld_command_windows(groups, ctl, w)
    assert [r["bss_group_ids"] for r in changed["windows"]] == [[0], [1]]
    assert not changed["same_sequence"] and changed["same_sequence_except_bss_group"]
    assert not mld_command_windows(groups.replace("bss=0 group=1", "bss=1 group=1"),
                                   ctl, w)["same_sequence_except_bss_group"]
    three_groups = groups + line(30, "mt7925_lab_sta_mld_slot", "target=3 slot=0 count=2")
    three_groups += line(30, "mt7925_lab_bss_mld", "bss=0 group=0")
    three_ctl = ctl + line(29, "drv_sta_state", "sta:aa:bb:cc:dd:ee:ff state: 0->1")
    three_windows = w + [{"authorized_at": 30, "deauthorized_at": 31}]
    rotated = mld_command_windows(three_groups, three_ctl, three_windows)
    assert [r["bss_group_ids"] for r in rotated["windows"]] == [[0], [1], [0]]
    assert rotated["same_sequence_except_bss_group"]
    assert rotated["firmware_reset_work"] is None
    reset_probe = three_groups + "CRASH_PROBE_FORMAT reset_work\n"
    assert mld_command_windows(reset_probe, three_ctl, three_windows)["firmware_reset_work"] == []
    reset_probe += line(25, "reset_work", "mt7925_mac_reset_work")
    assert mld_command_windows(reset_probe, three_ctl, three_windows)["firmware_reset_work"] == [25.0]
    assert not mld_command_windows(
        three_groups.replace("30.000000: mt7925_lab_sta_mld_slot: target=3",
                             "30.000000: mt7925_lab_sta_mld_slot: target=4"),
        three_ctl, three_windows)["same_sequence_except_bss_group"]
    basic = "bss=0 link=0 peer=2 peer_link=0 enabled=1 active=1 band="
    ack = "bss=0 link=0 wcid=2 enabled=1 result=0"
    migration = (
        line(9.1, "mt7925_lab_bss_basic", basic + "0")
        + line(9.2, "mt7925_lab_bss_result", ack)
        + line(9.3, "mt7925_lab_bss_basic", basic + "1")
        + line(9.4, "mt7925_lab_bss_mld", "bss=0 link=0 group=0 own=32")
        + line(9.5, "mt7925_lab_bss_result", ack)
        + line(9.6, "mt7925_lab_sta_mld_update", "bss=1 wcid=3 result=0")
    )
    def moves(trace):
        return band_group_refresh_windows(trace, ctl, w[:1])[0]["migrations"]
    assert moves(migration)[0]["group_refresh_before_sta"]
    assert not moves(migration.replace("mt7925_lab_bss_mld", "other"))[0]["group_refresh_before_sta"]
    assert not moves(migration.replace("band=0", "band=255"))
    assert not moves(migration.replace("result=0", "result=-5"))
    assert not moves(migration.replace("peer=2 peer_link=0", "peer=2 peer_link=255"))
    peer = {"stage": 7, "bss": 1, "link": 1, "wcid": 3, "host_band": 0}
    retire_window = [{"authorized_at": 10, "deauthorized_at": 11, "wtbl": [peer]}]
    retirement = (
        line(11.1, "mt7925_lab_bss_basic", "bss=1 link=1 enabled=0 peer=3 band=0")
        + line(11.2, "mt7925_lab_bss_result", "bss=1 link=1 enabled=0 wcid=3 result=0")
        + line(11.3, "mt7925_lab_sta_result", "bss=1 link=1 enabled=0 wcid=3 result=0")
        + line(11.4, "mt7925_lab_band_retire", "bss=1 link=1 band=0 was_active=1 result=0")
    )
    def retire_result(trace):
        return band_retirement_windows(trace, ctl, retire_window)[0]["peers"][0]
    assert retire_result(retirement)["complete"] is True
    assert retire_result(retirement.replace("band=0", "band=255"))["complete"] is False
    assert retire_result(retirement.replace("was_active=1", "was_active=0"))["complete"] is False
    assert retire_result(retirement.replace("result=0", "result=-5"))["complete"] is False
    assert retire_result(retirement.replace("11.400000", "20.000000"))["complete"] is None
    assert retire_result(retirement + retirement)["complete"] is None
    assert retire_result(retirement.replace("mt7925_lab_band_retire", "other"))["complete"] is None
    detached = retirement + line(11.45, "mt7925_lab_group_retire",
                                 "bss=1 link=1 was_active=1 result=0")
    assert retire_result(detached)["group_retire_complete"] is True
    assert retire_result(detached.replace("was_active=1 result=0", "was_active=0 result=0"))["group_retire_complete"] is False
    assert retire_result(detached.replace("result=0", "result=-5"))["group_retire_complete"] is False
    assert retire_result(detached.replace("11.450000", "11.250000"))["group_retire_complete"] is False
    assert retire_result(retirement)["group_retire_complete"] is None
    assert retire_result(detached + detached)["group_retire_complete"] is None
    active = detached + line(11.35, "mt7925_lab_group_detach_active",
                              "bss=1 link=1 was_active=1 result=0")
    assert band_retirement_windows(active, ctl, retire_window)[0]["active_detach_complete"] is True
    assert band_retirement_windows(detached, ctl, retire_window)[0]["active_detach_complete"] is None
    assert band_retirement_windows(active.replace("11.350000", "11.250000"), ctl,
                                   retire_window)[0]["active_detach_complete"] is False
    assert band_retirement_windows(active.replace("11.350000", "11.550000"), ctl,
                                   retire_window)[0]["active_detach_complete"] is False
    assert band_retirement_windows(active.replace("was_active=1 result=0", "was_active=0 result=0"),
                                   ctl, retire_window)[0]["active_detach_complete"] is False
    late = retirement + (
        line(11.5, "mt7925_lab_bss_basic",
             "bss=1 link=1 enabled=0 peer=18 peer_link=255 active=1 conn_state=1 band=255")
        + line(11.51, "mt7925_lab_bss_mld", "bss=1 link=1 group=0 own=33")
        + line(11.52, "mt7925_lab_bss_result", "bss=1 link=1 enabled=0 wcid=18 result=0")
    )
    retired = band_retirement_windows(late, ctl, retire_window)[0]
    assert retired["all_peers_removed_at"] == 11.3
    assert len(retired["late_active_bss_updates"]) == 1
    update = retired["late_active_bss_updates"][0]
    assert update["mld_tags"][0]["group"] == 0 and update["acks"][0]["result"] == 0
    skipped = retirement + line(11.5, "mt7925_lab_chanctx_unassign",
                                "bss=1 link=1 active=0 skipped=1 result=0")
    retired = band_retirement_windows(skipped, ctl, retire_window)[0]
    assert retired["late_active_bss_updates"] == []
    assert retired["chanctx_unassignments"][0]["skipped"] == 1
    assert band_retirement_windows(late.replace("mt7925_lab_sta_result", "other"),
                                   ctl, retire_window)[0]["late_active_bss_updates"] is None
    f = "cookie=0000000012345678 fc=0x40c0 seq=16"
    teardown = (line(10.2, "mt7925_lab_mgmt_txd", f + " wcid=2 link=0 band=1")
                + line(10.201, "mt7925_lab_mgmt_txs", f + " wcid=2 link=0 band=1 ack_error=0")
                + line(10.202, "mt7925_lab_mgmt_tx_free", f + " desc_wcid=2 header_valid=1 header=41000000")
                + line(20.2, "mt7925_lab_mgmt_txd", f + " wcid=2 link=0 band=1")
                + line(20.4, "mt7925_lab_mgmt_tx_free", f + " desc_wcid=2 header_valid=1 header=40000000"))
    grant = (line(10.1, "mt7925_lab_roc_wire", "bss=0 token=1 expected=1 type=2 status=0 dbdc=1")
             + line(10.11, "mt7925_lab_roc_sync", "bss=0 token=1 phase=1 granted=1 result=0")
             + line(10.3, "mt7925_lab_roc_abort", "bss=0 token=1 band=1 result=0"))
    txs = teardown_tx_windows(teardown, grant, result)["windows"]
    assert txs[0]["acked"] == 1 and txs[0]["zero_attempts"] == 0
    assert txs[0]["frames"][0]["privilege_witness"]["token"] == "1"
    assert txs[1]["acked"] == 0 and txs[1]["zero_attempts"] == 1
    assert txs[1]["frames"][0]["privilege_witness"] is None
    assert teardown_tx_windows(teardown, grant.replace("dbdc=1", "dbdc=0"),
                               result)["windows"][0]["frames"][0]["privilege_witness"] is None
    # Contiguous token occupancy must include ordinary and sampled IP
    # packets, without inventing a firmware scheduling cause.
    def ip_desc(t, end, protocol, d5):
        row = dict(submitted_at=t, protocol=protocol, band="1", d5=d5)
        if end is not None:
            row["return"] = dict(time=end, header_count=1)
        return row
    report = {"windows": [{"authorized_at": 10, "deauthorized_at": 20,
                          "descriptors": [ip_desc(10.2, 14.2, "0x0800", "00000403"),
                                          ip_desc(11.0, 14.3, "0x86dd", "00000001"),
                                          ip_desc(14.5, 14.51, "0x0806", "00000001"),
                                          ip_desc(17.9, None, "0x0800", "00000001"),
                                          ip_desc(10.1, 10.11, "0x888e", "00000403")]}]}
    early = startup_tx_windows(line(14.19, "mt7925_lab_absence",
                                   "bss=1 absent=0 quota=0"), report)[0]["episodes"]
    assert len(early) == 3 and early[0]["first_return_ms"] == 4000
    assert early[0]["peak_pending"] == early[0]["pending_at_first_return"] == 2
    assert early[0]["host_status_requested"] == early[0]["host_status_not_requested"] == 1
    assert early[0]["drain_ms"] == 100 and early[0]["absence_during"][0]["bss"] == "1"
    assert early[1]["duration_ms"] == 10 and early[2]["right_censored"]
    assert early[2]["drain_ms"] is None and early[2]["returned"] == 0
    print("RECONNECT_DATAPATH_SELFTEST_PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial", type=Path, nargs="?")
    parser.add_argument("--band", choices=("24", "5"))
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--allow-open-ap-peer", action="store_true",
                        help="report AP authorization still open at trace end, not a synthetic deauth")
    parser.add_argument("--min-associations", type=int, choices=(1, 2, 3), default=2,
                        help="use 1 for an initial-hold failure before reconnect")
    args = parser.parse_args()
    if args.selftest:
        selftest()
    else:
        require(args.trial and args.band, "trial and band required")
        sealed = verify_seal(args.trial)
        result = {}
        for side in ("client", "ap"):
            name = f"band-{args.band}.{side}-control-trace.txt"
            require(name in sealed, f"unsealed {side} trace")
            text = (args.trial / name).read_text()
            result[side] = parse_trace(text, side, args.min_associations,
                                       args.allow_open_ap_peer and side == "ap")
            if side == "client":
                result["wtbl_bindings"] = wtbl_pair_bindings(result[side])
                lifecycle = None
                lifecycle_name = f"band-{args.band}.client-trace.txt"
                if lifecycle_name in sealed:
                    lifecycle = (args.trial / lifecycle_name).read_text()
                    result["mld_commands"] = mld_command_windows(lifecycle, text, result[side])
                    result["band_retirement"] = band_retirement_windows(
                        lifecycle, text, result[side])
                    result["band_group_refresh"] = band_group_refresh_windows(
                        lifecycle, text, result[side])
                if "mt7925_lab_mgmt_txd:" in text:
                    result["teardown_tx"] = teardown_tx_windows(text, lifecycle, result[side])
            if side == "client" and "mt7925_lab_mld_record_result:" in text:
                result["mld_records"] = mld_records(text)
                result["mld_lifetimes"] = mld_lifetimes(result["mld_records"], result[side], text)
                result["mld_transitions"] = mld_transitions(result["mld_records"])
            if side == "client" and "mt7925_lab_data_txd:" in text:
                result["data_tokens"] = token_windows(text, result[side])
                result["startup_tx"] = startup_tx_windows(text, result["data_tokens"])
                result["control_port"] = control_port_windows(text, result[side])
        print(json.dumps(result, indent=2))
