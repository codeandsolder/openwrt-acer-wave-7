#!/usr/bin/env python3
"""Compare actual unicast MAC headers with programmed link addresses."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

EVENT = re.compile(r"(\d+\.\d+): mt7925_lab_(rx_header|link_addr): (.*)")
FIELD = re.compile(r"(\w+)=([^\s]+)")
ACTIVATE = re.compile(r"(\d+\.\d+): drv_change_vif_links:.*old_links:0x[0-9a-f]+, new_links:0x[0-9a-f]+")


def parse_records(text):
    for line in text.splitlines():
        match = EVENT.search(line)
        if match:
            yield float(match[1]), match[2], dict(FIELD.findall(match[3]))


def classify(addr, entry, field, mld_field, links):
    if addr == entry[field]:
        return "expected-link"
    if addr == entry[mld_field]:
        return "mld-not-link"
    if any(addr == link[field] for link in links.values()):
        return "other-link"
    return "unmatched"


def summarize(headers, lifecycle, freq_to_link):
    transitions = []
    for line in lifecycle.splitlines():
        match = ACTIVATE.search(line)
        if match:
            old, new = (int(x, 16) for x in re.findall(r"(?:old|new)_links:0x([0-9a-f]+)", line))
            transitions.append((float(match[1]), old, new))
    # Both trace instances use the same monotonic clock. Requested masks,
    # not successful firmware grants, are the transition boundary.
    events = list(parse_records(headers))
    events.extend((ts, "transition", {"old": old, "new": new})
                  for ts, old, new in transitions)
    events.sort(key=lambda event: event[0])
    links = {}
    groups = Counter()
    snapshots = {}
    requested_mask = 0
    association = 0
    for ts, event, fields in events:
        if event == "transition":
            requested_mask = fields["new"]
            if fields["old"] == 0 and requested_mask:
                association += 1
            if requested_mask == 0:
                links.clear()
            continue
        if event == "link_addr":
            link = int(fields["link"])
            links[link] = fields
            snapshots[(association, link)] = fields
            continue
        freq = int(fields["freq"])
        entry = links.get(freq_to_link.get(freq))
        fc = int(fields["fc"], 0)
        ra = classify(fields["ra"], entry, "own", "own_mld", links) if entry else "no-link-context"
        ta = classify(fields["ta"], entry, "peer", "peer_mld", links) if entry else "no-link-context"
        # For FromDS, A3 is an Ethernet source, not necessarily the BSSID.
        phase = ("post" if requested_mask.bit_count() > 1 else
                 "pre" if requested_mask else "unassociated")
        groups[(association, phase, requested_mask, freq, int(fields["wcid"]),
                int(fields["cm"]), int(fields["sec"]), fc & 0x00ff,
                bool(fc & 0x4000), (fc >> 8) & 3, ra, ta,
                fields["ra"], fields["ta"])] += 1
    keys = ("association", "phase", "requested_links", "frequency", "wcid", "cipher_mismatch", "security_mode",
            "frame_type", "protected", "ds", "receiver_match", "transmitter_match",
            "receiver", "transmitter")
    return {"requested_link_transitions": transitions,
            "requested_link_addresses": [dict(fields, association=assoc)
                                         for (assoc, _), fields in snapshots.items()],
            "groups": [dict(zip(keys, group)) | {"count": count}
                       for group, count in groups.most_common()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("header_trace", type=Path)
    parser.add_argument("lifecycle_trace", type=Path)
    parser.add_argument("--link-frequency", action="append", required=True,
                        help="LINK:FREQUENCY_MHZ")
    args = parser.parse_args()
    freq_to_link = {}
    for mapping in args.link_frequency:
        link, freq = map(int, mapping.split(":"))
        if freq in freq_to_link or link in freq_to_link.values():
            parser.error("duplicate link or frequency")
        freq_to_link[freq] = link
    result = summarize(args.header_trace.read_text(), args.lifecycle_trace.read_text(),
                       freq_to_link)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
