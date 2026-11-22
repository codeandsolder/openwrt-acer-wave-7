#!/usr/bin/env python3
"""Scoped Clause 22 BMCR power control for the dedicated Asus RTL8156B.

Keep the netdev administratively up and the USB device enumerated. A
successful ioctl/readback is not evidence of far-end carrier isolation.
"""
import argparse
import fcntl
import os
import platform
from pathlib import Path
import socket
import struct
import subprocess

IFACE = "enp4s0f4u2u4"
SYS = Path("/sys/class/net") / IFACE
SIOCGMIIPHY, SIOCGMIIREG, SIOCSMIIREG = 0x8947, 0x8948, 0x8949
BMCR, BMSR = 0, 1
PDOWN, RESET, RESTART_AN, ISOLATE = 0x0800, 0x8000, 0x0200, 0x0400
# The pinned Asus is x86_64 Linux; struct ifreq is 40 bytes, with
# struct mii_ioctl_data overlaying the 24-byte union at offset 16.
REQ = struct.Struct("=16sHHHH16x")


def check_scope():
    if (SYS / "address").read_text().strip() != "00:e0:4c:68:00:6d":
        raise RuntimeError("wrong direct NIC")
    if (SYS / "master").exists():
        raise RuntimeError("direct NIC enslaved")
    device = (SYS / "device").resolve()
    if device.name != "6-2.4:1.0" or (device / "driver").resolve().name != "r8152":
        raise RuntimeError("wrong USB device or driver")
    for family in ("-4", "-6"):
        routes = subprocess.check_output(["ip", family, "route", "show", "default"], text=True)
        if any(IFACE in row.split() for row in routes.splitlines()):
            raise RuntimeError("direct NIC is default routed")
    if not (int((SYS / "flags").read_text(), 16) & 1):
        raise RuntimeError("direct NIC unexpectedly admin down")


def ioctl(sock, op, phy=0, reg=0, value=0):
    req = REQ.pack(IFACE.encode(), phy, reg, value, 0)
    _, addr, _, _, out = REQ.unpack(fcntl.ioctl(sock, op, req))
    return addr, out


def control(action):
    check_scope()
    if platform.machine() != "x86_64" or os.geteuid() != 0:
        raise PermissionError("use the pinned x86_64 Linux host as root")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        phy, _ = ioctl(sock, SIOCGMIIPHY)
        def read(reg):
            return ioctl(sock, SIOCGMIIREG, phy, reg)[1]
        before = read(BMCR)
        if before == 0xffff or before & (RESET | ISOLATE):
            raise RuntimeError(f"unexpected BMCR 0x{before:04x}")
        if action in ("down", "up"):
            # Only modify the standard power bit; never replay the
            # self-clearing reset / restart autonegotiation commands.
            val = before & ~(PDOWN | RESTART_AN)
            if action == "down":
                val |= PDOWN
            ioctl(sock, SIOCSMIIREG, phy, BMCR, val)
        after = read(BMCR)
        if after == 0xffff or (action != "status" and
                bool(after & PDOWN) != (action == "down")):
            raise RuntimeError(f"PHY power readback mismatch: 0x{after:04x}")
        # BMSR link is latch-low. Read twice for current state.
        latched, current = read(BMSR), read(BMSR)
        if current == 0xffff or latched == 0xffff:
            raise RuntimeError("invalid PHY status")
        print(f"phy={phy} bmcr=0x{after:04x} pdown={int(bool(after & PDOWN))} "
              f"bmsr_latched=0x{latched:04x} bmsr=0x{current:04x} "
              f"link={int(bool(current & 4))}", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("status", "down", "up"))
    control(p.parse_args().action)
