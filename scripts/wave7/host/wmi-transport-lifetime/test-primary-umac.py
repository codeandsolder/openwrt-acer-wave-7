#!/usr/bin/env python3
"""Compile the actual primary selector and setup routine against a host shim."""
import argparse
from pathlib import Path
import re
import subprocess


def function(text, name):
    match = re.search(r"(?m)^(?:static )?(?:u8|int|void) " + name + r"\(", text)
    if not match:
        raise ValueError(name)
    pos = text.index("{", match.start())
    depth = 1
    end = pos + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[match.start():end] + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    text = (args.source / "mac.c").read_text()
    fixture = Path(__file__).with_name("primary-umac-fixture.c").read_text()
    bodies = "\n".join(function(text, name) for name in (
        "ath12k_mac_mlo_select_primary", "ath12k_mac_mlo_setup_primary"))
    generated = args.output / "primary-umac-expanded.c"
    generated.write_text(fixture.replace("/* EXTRACTED BODIES */", bodies))
    obj = args.output / "primary-umac.o"
    exe = args.output / "primary-umac"
    subprocess.run(["/usr/local/bin/sccache", "cc", "-std=gnu11", "-O2",
                    "-Wall", "-Wextra", "-Werror", "-c", str(generated),
                    "-o", str(obj)], check=True)
    subprocess.run(["cc", str(obj), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
    text = (args.source / "dp.c").read_text()
    fixture = Path(__file__).with_name("primary-umac-dp-fixture.c").read_text()
    bodies = "\n".join(function(text, name) for name in (
        "ath12k_dp_peer_set_default_routing", "ath12k_dp_peer_setup",
        "ath12k_dp_peer_cleanup"))
    generated = args.output / "primary-umac-dp-expanded.c"
    generated.write_text(fixture.replace("/* EXTRACTED BODIES */", bodies))
    obj = args.output / "primary-umac-dp.o"
    exe = args.output / "primary-umac-dp"
    subprocess.run(["/usr/local/bin/sccache", "cc", "-std=gnu11", "-O2",
                    "-Wall", "-Wextra", "-Werror", "-c", str(generated),
                    "-o", str(obj)], check=True)
    subprocess.run(["cc", str(obj), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()

