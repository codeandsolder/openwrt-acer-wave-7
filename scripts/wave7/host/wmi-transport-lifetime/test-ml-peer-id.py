#!/usr/bin/env python3
"""Exercise the actual host ML peer allocator across exhaustion and wrap."""
import argparse
from pathlib import Path
import subprocess

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    source = (a.source / "peer.c").read_text()
    start = source.index("u16 ath12k_peer_ml_alloc(")
    end = source.index("\nint ath12k_peer_mlo_link_peers_delete(", start)
    fixture = Path(__file__).with_name("ml-peer-id-fixture.c").read_text()
    expanded = a.output / "ml-peer-id-expanded.c"
    obj = a.output / "ml-peer-id.o"
    exe = a.output / "ml-peer-id"
    expanded.write_text(fixture.replace("/* EXTRACTED BODIES */", source[start:end]))
    subprocess.run(["/usr/local/bin/sccache", "cc", "-std=gnu11", "-O2",
                    "-Wall", "-Wextra", "-Werror", "-c", str(expanded),
                    "-o", str(obj)], check=True)
    subprocess.run(["cc", str(obj), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

if __name__ == "__main__":
    main()
