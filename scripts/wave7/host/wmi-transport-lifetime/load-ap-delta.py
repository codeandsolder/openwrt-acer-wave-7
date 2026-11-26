#!/usr/bin/env python3
"""Attribute per-case radio/CPU/interrupt counters to guarded load intervals."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess

spec = importlib.util.spec_from_file_location("rx_delta", Path(__file__).with_name("rx-counter-delta.py"))
rx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rx)
MODES = ("uplink", "downlink", "bidirectional")
CPU = re.compile(r"^cpu(\d+)\s+([\d ]+)$")
IRQ = re.compile(r"^\s*(\d+):\s+(.*)$")
STATION = re.compile(r"^Station ([\da-f:]+) \(on (\S+)\)$")
SCALAR = re.compile(r"^\s*([^:]+):\s*(\d+)(?:\s+us)?$")
MATRIX = re.compile(r"^(\w+):\s+((?:\d+:\d+\s*)+)$")
TX_MATRIX = {"tx_wbm_rel_source", "tqm_rel_reason", "fw_tx_status", "tx_enqueued", "tx_completed"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sections(text):
    lines = text.splitlines()
    require(len(lines) >= 4 and rx.BOOT.fullmatch(lines[0]) and lines[-1] == lines[0],
            "boot identity changed during snapshot")
    result = {}
    section = None
    for line in lines[2:]:
        if line.startswith("==== "):
            section = line[5:]
            require(section not in result, "duplicate section")
            result[section] = []
        else:
            require(section is not None, "missing section marker")
            result[section].append(line)
    require(result.pop("END") == [lines[0]], "bad closing boot seal")
    return lines[:2], result


LINK_COUNTERS = {"rx bytes", "rx packets", "tx bytes", "tx packets",
                 "tx retries", "tx failed", "rx drop misc", "tx duration",
                 "rx duration", "beacon rx", "beacon loss"}
LINK_RATES = {"signal", "signal avg", "tx bitrate", "rx bitrate",
              "last ack signal", "avg ack signal"}


def parse_link_station(lines, sta, links):
    """Parse multipart nl80211 link replies, not the aggregate station rate."""
    result = {}
    current = None
    for line in lines:
        if line.startswith("Station"):
            current = None
            require(line in (f"Station {sta[0]} (on {sta[1]})",
                             f"Station links {sta[0]} (on {sta[1]})"),
                    "unexpected link station identity")
        elif m := re.fullmatch(r"\tLink (\d+):", line):
            current = int(m[1])
            require(current not in result, "duplicate station link reply")
            result[current] = {"address": None, "counters": {}, "rates": {}}
        elif current is not None and line.startswith("\t\t"):
            key, value = map(str.strip, line.strip().split(":", 1))
            entry = result[current]
            if key == "address":
                require(entry["address"] is None, "duplicate link address")
                entry["address"] = value
            elif key in LINK_COUNTERS:
                require(key not in entry["counters"], "duplicate link counter")
                entry["counters"][key] = int(value.split()[0])
            elif key in LINK_RATES:
                require(key not in entry["rates"], "duplicate link rate")
                entry["rates"][key] = value
    require(result.keys() == links.keys(), "missing per-link station reply")
    for k, v in result.items():
        require(v["address"] == links[k]["addr"], "link address mismatch")
        require({"rx bytes", "rx packets", "tx bytes", "tx packets"} <= v["counters"].keys(),
                "missing per-link packet/byte counters")
    return result


def parse_link_datapath(lines, links):
    result = {}
    for line in lines:
        if not line or set(line) == {"-"}:
            continue
        m = re.fullmatch(r"link\[(\d+)\] (.+?)\s*=\s*(.*)", line)
        require(m, "unparsed link datapath counter")
        link, key, value = int(m[1]), m[2], m[3]
        entry = result.setdefault(link, {})
        if value.isdigit():
            require(key not in entry, "duplicate link datapath counter")
            entry[key] = int(value)
        else:
            for pair in value.split():
                name, count = pair.split(":")
                subkey = f"{key}/{name}"
                require(subkey not in entry, "duplicate link datapath counter")
                entry[subkey] = int(count)
    require(result.keys() == links.keys(), "missing link datapath counters")
    for v in result.values():
        require({"Tx Unicast Frames Enqueued", "Tx Broadcast Frames Enqueued",
                 "Tx Frames Completed", "Tx Frames Dropped"} <= v.keys(),
                "incomplete link datapath counters")
    return result


def parse(text):
    header, sections_ = sections(text)
    required = {"CPU", "SOFTIRQ", "IRQ", "STATION", "AQL"}
    require(required <= sections_.keys(), "missing required telemetry")
    cpus = {}
    for line in sections_["CPU"]:
        if m := CPU.fullmatch(line):
            values = tuple(map(int, m[2].split()))
            require(len(values) >= 8, "truncated CPU counters")
            # guest/guest_nice are already included in user/nice.
            cpus[int(m[1])] = values[:8]
    require(cpus and sorted(cpus) == list(range(len(cpus))), "noncontiguous CPU IDs")
    ncpu = len(cpus)

    def indexed(lines, regex):
        result = {}
        for line in lines:
            m = regex.fullmatch(line)
            if not m:
                continue
            fields = m[2].split()
            require(len(fields) >= ncpu and all(v.isdigit() for v in fields[:ncpu]),
                    "invalid per-CPU counter")
            key = f"{m[1]}:{' '.join(fields[ncpu:])}".rstrip(":")
            require(key not in result, "duplicate per-CPU counter")
            result[key] = tuple(map(int, fields[:ncpu]))
        return result

    softirqs = indexed(sections_["SOFTIRQ"], re.compile(r"^\s*(\w+):\s+(.*)$"))
    irqs = indexed(sections_["IRQ"], IRQ)
    sta_lines = sections_["STATION"]
    sta = [m.groups() for line in sta_lines if (m := STATION.fullmatch(line))]
    require(len(sta) == 1 and sta[0][1] == "ap-mld0", "expected exactly one lab station")
    fields = {}
    for line in sta_lines:
        if line.startswith("\t"):
            key, value = line.strip().split(":", 1)
            fields[key.strip()] = value.strip()
    require(all(fields[k] == "yes" for k in ("authorized", "authenticated", "associated")),
            "station lost authorization")
    sta_counters = {k: int(fields[k].split()[0]) for k in
                    ("rx bytes", "rx packets", "tx bytes", "tx packets",
                     "tx retries", "tx failed", "rx drop misc", "tx duration", "rx duration")}
    sta_rates = {k: fields[k] for k in ("signal", "signal avg", "tx bitrate", "rx bitrate")}
    aql = {}
    for line in sections_["AQL"]:
        if m := re.fullmatch(r"(\S+)\s+(\d+) us", line):
            aql[m[1]] = int(m[2])
    require("total" in aql, "missing AQL pending")
    radio = {k: v for k, v in sections_.items() if k.startswith("/sys/kernel/debug/ath12k/")}
    rx_text = "\n".join(header + [line for k, v in radio.items() for line in ["===" + k, *v]])
    tx = {}
    for k, lines in radio.items():
        device = k.split("/")[-2]
        tx[device] = {}
        for line in lines:
            if (m := MATRIX.fullmatch(line)) and m[1] in TX_MATRIX:
                for pair in m[2].split():
                    index, value = pair.split(":")
                    tx[device][f"{m[1]}/{index}"] = int(value)
            elif (m := SCALAR.fullmatch(line)) and m[1] == "Misc Transmit Failures":
                tx[device][m[1]] = int(m[2])
        require(TX_MATRIX == {k.split("/")[0] for k in tx[device] if "/" in k},
                "incomplete TX matrices")
    extra = {}
    if "AGGREGATION" in sections_:
        agg = sections_["AGGREGATION"]
        require(agg[0].endswith("/stations/" + sta[0][0]), "wrong aggregation station")
        tids = {}
        links = {}
        link = None
        for line in agg[1:]:
            if m := re.fullmatch(r"(\d+)\s+([01])\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+([01])\s+(0x[0-9a-f]+)\s+(\d+)", line):
                tid = int(m[1])
                require(tid not in tids, "duplicate aggregation TID")
                tids[tid] = {"rx": bool(int(m[2])), "rx_token": int(m[3], 16),
                             "rx_ssn": int(m[4], 16), "tx": bool(int(m[5])),
                             "tx_token": int(m[6], 16), "pending": int(m[7])}
            elif m := re.fullmatch(re.escape(agg[0]) + r"/link-(\d+)", line):
                link = int(m[1])
                require(link not in links, "duplicate station link")
                links[link] = {}
            elif link is not None:
                key, value = line.split("=", 1)
                require(key not in links[link], "duplicate link metadata")
                links[link][key] = value if key == "addr" else int(value)
        require(set(tids) == set(range(16)) and set(links) == {0, 1} and
                all(set(v) == {"addr", "rx_duplicates", "rx_fragments"} for v in links.values()),
                "incomplete aggregation or MLO link data")
        extra["aggregation"] = {"tids": tids, "links": links}
    require(("LINK_STATION" in sections_) == ("LINK_DATAPATH" in sections_),
            "incomplete per-link telemetry")
    if "LINK_STATION" in sections_:
        require("aggregation" in extra, "missing independent link identity")
        links = extra["aggregation"]["links"]
        extra["link_station"] = parse_link_station(sections_["LINK_STATION"], sta[0], links)
        extra["link_datapath"] = parse_link_datapath(sections_["LINK_DATAPATH"], links)
    if "AFFINITY" in sections_:
        affinity = {int(irq): cpulist for irq, cpulist in
                    (line.split() for line in sections_["AFFINITY"])}
        require(len(affinity) == len(sections_["AFFINITY"]) == 12,
                "incomplete QCN6432 DP IRQ affinities")
        extra["affinity"] = affinity
    if "CPUFREQ" in sections_:
        freq = {}
        for line in sections_["CPUFREQ"]:
            path, khz = line.split()
            m = re.fullmatch(r"/sys/devices/system/cpu/cpu(\d+)/cpufreq/scaling_cur_freq", path)
            require(m and int(m[1]) not in freq and int(khz) > 0, "bad CPU frequency sample")
            freq[int(m[1])] = int(khz)
        require(freq.keys() == cpus.keys(), "incomplete CPU frequency sample")
        extra["frequency_khz"] = freq
    return dict(rx=rx_text, cpu=cpus, softirq=softirqs, irq=irqs, sta=sta[0],
                assoc=fields["associated at [boottime]"], sta_counters=sta_counters,
                rates=sta_rates, aql=aql, tx=tx, extra=extra)


def subtract(a, b):
    require(a.keys() == b.keys(), "counter identities changed")
    result = {}
    for k, v in a.items():
        w = b[k]
        if isinstance(v, tuple):
            require(len(v) == len(w) and all(x <= y for x, y in zip(v, w)),
                    f"counter reset: {k}")
            result[k] = [y - x for x, y in zip(v, w)]
        else:
            require(v <= w, f"counter reset: {k}")
            result[k] = w - v
    return result


def compare(before, after):
    a, b = parse(before), parse(after)
    require(a["sta"] == b["sta"] and a["assoc"] == b["assoc"], "station re-associated")
    radio = rx.compare(a["rx"], b["rx"])
    cpu = {}
    for k, values in subtract(a["cpu"], b["cpu"]).items():
        total = sum(values)
        require(total > 0, "empty CPU interval")
        cpu[str(k)] = {"busy_pct": 100 * (total - values[3] - values[4]) / total,
                       "softirq_pct": 100 * values[6] / total,
                       "irq_pct": 100 * values[5] / total}
    require(a["extra"].keys() == b["extra"].keys(), "telemetry schema changed")
    extra = {}
    if "aggregation" in a["extra"]:
        aa, bb = a["extra"]["aggregation"], b["extra"]["aggregation"]
        link_delta = {}
        for k, link in aa["links"].items():
            later = bb["links"][k]
            require(link["addr"] == later["addr"], "station link changed")
            link_delta[k] = subtract({k: v for k, v in link.items() if k != "addr"},
                                     {k: v for k, v in later.items() if k != "addr"})
        extra["aggregation"] = {"before": aa, "after": bb, "link_delta": link_delta}
    if "link_station" in a["extra"]:
        before_links = a["extra"]["link_station"]
        after_links = b["extra"]["link_station"]
        require(before_links.keys() == after_links.keys(), "link set changed")
        extra["link_station"] = {}
        for k, v in before_links.items():
            later = after_links[k]
            require(v["address"] == later["address"], "link peer changed")
            extra["link_station"][k] = {
                "address": v["address"],
                "delta": subtract(v["counters"], later["counters"]),
                "rates": {"before": v["rates"], "after": later["rates"]},
            }
        extra["link_datapath_delta"] = {
            k: subtract(v, b["extra"]["link_datapath"][k])
            for k, v in a["extra"]["link_datapath"].items()
        }
    if "affinity" in a["extra"]:
        require(a["extra"]["affinity"] == b["extra"]["affinity"],
                "IRQ affinity changed during case")
        extra["affinity"] = a["extra"]["affinity"]
    if "frequency_khz" in a["extra"]:
        extra["frequency_khz"] = {"before": a["extra"]["frequency_khz"],
                                  "after": b["extra"]["frequency_khz"]}
    return {"radio": radio, "cpu": cpu, "extra": extra,
            "softirq_delta": subtract(a["softirq"], b["softirq"]),
            "irq_delta": subtract(a["irq"], b["irq"]),
            "station_delta": subtract(a["sta_counters"], b["sta_counters"]),
            "station_rates": {"before": a["rates"], "after": b["rates"]},
            "aql_pending_us": {"before": a["aql"], "after": b["aql"]},
            "tx_delta": {k: subtract(v, b["tx"][k]) for k, v in a["tx"].items()}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--band", choices=("24", "5"), required=True)
    args = p.parse_args()
    subprocess.run(["sha256sum", "-c", "SHA256SUMS", "--status"], cwd=args.run, check=True)
    prefix = args.run / f"band-{args.band}"
    result = {}
    for mode in MODES:
        result[mode] = compare(Path(f"{prefix}.load-{mode}-ap-before.txt").read_text(),
                               Path(f"{prefix}.load-{mode}-ap-after.txt").read_text())
    event = re.compile(r"(\d+\.\d+): drv_ampdu_action: .* tid (\d+), ssn (\d+), buf_size (\d+), amsdu (\d+), timeout (\d+) action (\d+)")
    actions = ("rx_start", "rx_stop", "tx_start", "tx_stop_cont",
               "tx_stop_flush", "tx_stop_flush_cont", "tx_operational")
    for endpoint in ("ap", "client"):
        trace = Path(f"{prefix}.{endpoint}-control-trace.txt").read_text()
        events = []
        for m in event.finditer(trace):
            ts, tid, ssn, size, amsdu, timeout, action = m.groups()
            events.append(dict(monotonic_s=float(ts), tid=int(tid), ssn=int(ssn),
                               window=int(size), amsdu=bool(int(amsdu)), timeout=int(timeout),
                               action=actions[int(action)]))
        result[f"{endpoint}_ba_events"] = events
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
