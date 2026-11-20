# Stock ARM replay: port-2 QCA8081 and host link-sync worker

Run on the development host, without accessing the router:

```sh
r=/home/jan/projects/acer-wave7-firmware
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --offline --python /usr/bin/python3 python replay.py \
  "$r/Acer_Predator_T7c/rootfs-067/lib/modules/5.4.213/qca-ssdk.ko" \
  /home/jan/build/wave7/qca8081-stock-host-replay/verified-v2 \
  --stock-fit "$r/Acer_Predator_T7c/work/openwrt-roundtrip-stock/kernel.itb" \
  --stock-dts "$r/device-backup-2026-10-28/live.dts"
```

Requires the existing managed sccache, clang, ld.lld and qemu-arm.
Choose a new evidence output directory. The build products are temporary.
Only evidence JSON remains; the stock module itself is not distributed.
Replay pins exact input hashes, validates the FIT kernel checksums,
extracts the embedded Linux 5.4.213 configuration (HZ=100), and checks
the captured stock DT's IPQ53xx compatibility and initial wrapper 1 mode.

## Findings

Original executable paths, not a translated pseudocode model:

* SSDK work callback 0x918e8 takes its mutex, calls the registered
  ops+0x200 host link-sync callback 0xadec, unlocks, queues on CPU 4
  with delay 100 jiffies (1 second after completion). Registration
  is at 0xbd70. Linux PHY read_status at 0x69cc4 also calls the same
  get_status at 0x67640. Do not infer an exact combined poll frequency.
* The SSDK worker dispatches via 0x6d73c, ops+0xf0, registered
  at 0x68f34 (literal at 0x69568), to original QCA808x get_status.
  QCA8081 copper ID is 004dd101. Raw C22.17 bit10 is link;
  bits9:7 encode speed, bit13 duplex, bits3/2 TX/RX flow.
  C22.31 bits14:13 report SGMII/SGMII+ mode independently of speed.
  The down branch rewrites the slave seed under the original
  capability predicates and handles the master/slave fault.
* Original locked FIFO helper: neighbor PHY 25 MMD1.9072 bit11
  set on up, clear on down, even if already correct. The stock
  wrapper ignores some read/write errors. In particular, an all-ones
  status read may become a false down, and an all-ones FIFO read
  prevents the write but not link-up. Do not copy these error paths.
* Host compares cached speed, duplex, TX/RX pause (0xad8c).
  On down, bridge TX off, ten 1ms delay calls, MAC RX off,
  link cache update, interface mode status check, link notify,
  FDB deletion. The original bridge helper at 0x74f4 changes only
  bit16 of PPE port2 bridge control 0x60308. The original GMAC
  enable helpers at 0x6104 and 0x63ec update different bits of
  port2 GMAC_ENABLE at 0x1200 (TX bit1, RX bit0).
  No explicit GMAC TX disable on the ordinary down path.
* On up: TX off, mode-status check, then, only if the cached
  negotiated tuple changed, gate UNIPHY clocks, program necessary
  rates/speed/duplex/pause, re-enable clocks, pulse adapter reset.
  The IPQ53xx branch of stock qca_gcc_uniphy_port_clock_set chooses
  clock IDs22/23, not the IPQ95xx IDs20/21. Speed-rate IDs2/3:
  2.5/25/125/312.5MHz for 10/100/1000/2500Mbps respectively.
  Actual speed changes have two 10ms waits. Adapter pulse uses
  UNIPHY1 offset 0x480 bit11 clear/set, preserving other bits.
  Unchanged tuple skips that explicit reconfiguration block.
  Final TX/RX/bridge on and notification happen on either up path.
  The independent mode-status check may still invoke mode apply,
  even for an unchanged tuple; the mode-apply internals are mocked.
* For SGMII and SGMII+ port2 the stock wrapper selectors 15/12
  both select GMAC type 1; the fixture uses that type. GMAC and
  bridge register-address calculations execute actual instructions.

## Scope and results

All excluded code is filled with UDF, unknown call relocations
terminate, and hardware accesses go only to explicit fixture mocks.
The fixture includes original locks, status helpers, host transition,
adapter control, rate selection and MAC/bridge enable helpers; no
device register accesses. Cache tuples, PHY registers, clock outcomes,
device type, topology, and time are simulation inputs. Mode-apply,
MAC speed/duplex/pause internals, kernel scheduling and actual clock
hardware are boundaries; neither electrical behavior nor recovery is
proved by this experiment.

19 named cases (9 full worker/PHY cases, 10 host cases), plus 2,304
synthetic status combinations (24 negotiated tuples squared times
four old/new carrier combinations) pass. Half duplex included only
for 10/100; pause inputs independently varied to exercise decisions.
576 steady down, 576 steady up, 576 down edges, 24 unchanged-tuple up
edges, 552 changed-tuple up edges. The last group executes 552
adapter pulses, including 416 speed-rate changes. All 24 unchanged
up edges skip the explicit pulse. 320 mode-apply calls across both
edge directions (mocked internals). A separate named mismatch case
demonstrates mode apply without explicit adapter pulse.

The full replay does not prove 0491 fixes any hardware fault. The
stock extra worker and host reset policy are not yet reproduced by
0491. In particular, preserve a first-time setup path and do not
suppress resets on interface changes. The next gated hardware test
remains the existing approved 0491 matched 1G reconnect; isolate any
host-side follow-up so it does not confound that result.
