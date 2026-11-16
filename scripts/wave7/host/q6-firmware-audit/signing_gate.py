#!/usr/bin/env python3
"""Compare *embedded X509* roots in Qualcomm MBNv7 q6_fw0.b01 cert sets.

This verifies the embedded chain identity, NOT the signed MBN hash table,
Qualcomm PAS auth, device fuses, or full certificate validity.
"""
import argparse
import json
from pathlib import Path

from certificate_chain import certs


def describe_chain(path: Path):
    entries = certs(path)
    if len(entries) < 3:
        raise ValueError(f"{path}: need root, intermediate and leaf X.509 certificates")
    cert_info = []
    for fingerprint, (_offset, _size, info) in entries.items():
        lines = info.splitlines()
        subject = next((v[len("subject="):] for v in lines if v.startswith("subject=")), None)
        issuer = next((v[len("issuer="):] for v in lines if v.startswith("issuer=")), None)
        if not subject or not issuer:
            raise ValueError(f"{path}: X.509 subject/issuer missing")
        cert_info.append({"fingerprint": fingerprint, "subject": subject, "issuer": issuer})
    roots = [c for c in cert_info if c["subject"] == c["issuer"] and "Root CA" in c["subject"]]
    if len(roots) != 1:
        raise ValueError(f"{path}: unexpected X.509 self-issued roots: {len(roots)}")
    root = roots[0]
    intermediates = [c for c in cert_info if c["issuer"] == root["subject"] and c is not root]
    if len(intermediates) != 1:
        raise ValueError(f"{path}: expected one intermediate, found {len(intermediates)}")
    intermediary = intermediates[0]
    leaves = [c for c in cert_info if c["issuer"] == intermediary["subject"]]
    if len(leaves) != 1:
        raise ValueError(f"{path}: expected one leaf, found {len(leaves)}")
    return {
        "root": root, "intermediate": intermediary, "leaf": leaves[0],
        "cert_count": len(cert_info),
    }


def assess(accepted: Path, candidate: Path):
    a = describe_chain(accepted)
    b = describe_chain(candidate)
    root_match = a["root"]["fingerprint"] == b["root"]["fingerprint"]
    return {
        "decision": "SAME_EMBEDDED_ROOT" if root_match else "DIFFERENT_EMBEDDED_ROOT",
        "production_root_vs_test_root": (
            "Test Root CA" not in a["root"]["subject"]
            and "Test Root CA" in b["root"]["subject"]
        ),
        "root_fingerprint_equal": root_match,
        "intermediate_fingerprint_equal": (
            a["intermediate"]["fingerprint"] == b["intermediate"]["fingerprint"]
        ),
        "leaf_fingerprint_equal": a["leaf"]["fingerprint"] == b["leaf"]["fingerprint"],
        "accepted": a,
        "candidate": b,
        "not_proven": (
            "MBNv7 signed hash verification, secureboot fuse/root policy, "
            "Qualcomm PAS authentication, runtime QMI/WMI compatibility"
        ),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accepted", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    result = assess(args.accepted, args.candidate)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["decision"])
    print("INTERMEDIATE_SAME", result["intermediate_fingerprint_equal"])
    print("CANDIDATE_TEST_ROOT", result["production_root_vs_test_root"])
    if result["decision"] == "DIFFERENT_EMBEDDED_ROOT":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
