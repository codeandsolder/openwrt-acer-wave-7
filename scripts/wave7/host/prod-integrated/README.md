# Wave 7 integrated firmware — guarded native trial

Source branch: wave7-prod-guarded-trial (based on PR #5 source
0fbc2cc77b2cab0838261cc23a5b310a795913ba).

The existing native NAND sysupgrade and same-slot Asus rollback are physically
validated. On Nov 16 a WBE1.4 firmware trial developed a real Q6 NoC fatal at
uptime 406 seconds and the autonomous Asus supervisor restored the previously
accepted image, recovering firstboot, MLO and bootfail=0. The Nov 18 RTL8367D
port0 trial installed and accepted the present live firmware.

**Exact accepted rollback:** r0+38249-port0-16a784ae,
SHA256 6098ac96a49f9d9384983e0d8f5534fefe6ad5cf743c217484f7a4b124cc9f3b.
Asus file: /home/jan/firmware/wave7/trials/20261118-asus-dualport/
wave7-port0-16a784ae-sysupgrade.bin. It passed the actual live router's
read-only sysupgrade -T -n on Nov 19 without reboot or NAND writes.

## Operation

Install trial.sh to /home/jan/scripts/wave7/prod-integrated/trial.sh on Asus.
After the final source-aligned image is independently verified and copied
to Asus, place it and its cross-host SHA256SUMS in:
  /home/jan/firmware/wave7/trials/20261119-prod-integrated-0fbc2cc77b/

  trial.sh --selftest        # no external effects
  trial.sh --check-baseline  # accepted state, peers, observers, no writes
  trial.sh --check           # require candidate file and exact SHA
  trial.sh --run             # guarded native NAND upgrade

The guard binds all router SSH and image transfers to the Asus independent
1GbE switch management interface enp4s0f4u2u2u4; verifies QCA8081 2.5GbE
data link, 1GbE RTL8367D lan1, br-lan peer, MLO2, all three Q6 remoteprocs,
NoC=0, accepted firstboot marker, bootfail0, and active independent Asus
capture services. Both images must pass live sysupgrade -T -n before flashing.

The trial and vendor fallback watchers must both acknowledge readiness.
A candidate requires 300 seconds of continuous health. A candidate accepted
by firstboot but subsequently unhealthy is automatically restored from the
exact accepted image; early boot failures use the established bootloader
bootfail/firstboot watchdog recovery. No manual Wyse reassociation is invoked.

The trial image still contains lab DHCPv4/DHCPv6/RA and blank-password root
SSH. Do not connect as a production AP until hardened. Avoid QCA8081 direct
1Gbps SGMII uplink because physical carrier loss can strand GMAC RX.
This is isolated hardware acceptance, not production deployment.

**No UART required** for this proven native sysupgrade/rollback workflow.
