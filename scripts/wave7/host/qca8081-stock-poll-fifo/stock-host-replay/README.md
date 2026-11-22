# Stock ARM replay: port-2 QCA8081 and host link-sync worker

Run on the development host, without accessing the router:

```sh
r=/home/jan/projects/acer-wave7-firmware
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --offline --python /usr/bin/python3 python replay.py \
  "$r/Acer_Predator_T7c/rootfs-067/lib/modules/5.4.213/qca-ssdk.ko" \
  /home/jan/build/wave7/qca8081-stock-host-replay/verified-new \
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
  ops+0x200 host link-sync callback 0xadec, unlocks, queues with CPU argument 4
  and delay 100 jiffies (1 second after completion). The pinned stock
  configuration has NR_CPUS=4; Linux v5.4.213 [workqueue.h](https://github.com/gregkh/linux/blob/v5.4.213/include/linux/workqueue.h) defines
  WORK_CPU_UNBOUND=NR_CPUS, so this is the ordinary unbound CPU selector,
  not pinning to a nonexistent CPU4. The queue is system_wq. Original
  normal-silicon start 0x91e3c schedules the same work after 100 jiffies;
  stop 0x91dec synchronously cancels it. The replay covers both paths for
  supported context chip bytes 0x20/0xee/0x15, rejects unsupported chip
  bytes (-19) and missing contexts (-21), and excludes emulation.
  Registration
  is at 0xbd70. Linux PHY read_status at 0x69cc4 also calls the same
  get_status at 0x67640. Replay executes both call paths, including
  unchanged-up, down and unreadable status in phylib. The fixture starts
  with notification initialization complete (.bss+0x7abc=1), and mocks
  partner-ability and pause-resolution helpers. Do not infer an exact
  combined poll frequency.
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
* Corrected MAC selector scope: original ARM block 0x88c4–0x8990
  selects type 1 (GMAC) for wrapper 15/SGMII. Wrapper 12/SGMII+
  selects type 2 (XGMAC) with feature mask 4 clear, type 1 with
  that feature set. All three selectors are now executed in the
  fixture. At DT parser 0x982c4–0x98320, literal references
  resolve to `port_mac_sel`, `QGMAC_PORT`, `XGMAC_PORT`; QGMAC
  sets mask 4, XGMAC sets mask 8. Captured port2 PHY24 node
  has neither property nor forced-speed/duplex. Thus default
  2.5G selection is expected XGMAC, not GMAC (runtime feature
  state was not captured). The existing worker matrix intentionally
  mocks mode apply and holds MAC type at GMAC even at 2500; its
  GMAC enable traces for 2500 are synthetic and must not be claimed
  as stock hardware parity. The 1G GMAC traces remain applicable.
  GMAC and bridge register-address calculations execute original
  instructions.

* Separate direct original ARM parameter cases confirm GMAC speed
  register 0x1204 bits1:0 map 10/100/1000/2500 to 0/1/2/2.
  The 2500 encoding is a GMAC helper case, not evidence of GMAC use
  on stock Wave7 at 2.5G. GMAC_ENABLE 0x1200 bits6,5,4 are respectively
  TX pause, RX pause and duplex. Each helper reads and writes the
  entire word preserving other bits, including when unchanged.
  BM port9 flow-control register 0x600124 is a stock whole-word
  write of 0 or 1 (not read-modify-write). The worker's TX pause
  wrapper at 0x6ddc invokes the BM callback at ops+0x6a8 after MAC
  TX pause; init 0x241a8 assigns this callback 0x23f50. Linux also
  addresses BM port9, but programs it after TX/RX enable. These
  individual differences are distinct from the 0493 gate-order test.
  The parameter cases execute 0x6210, 0x6298, 0x6320, 0x70b4,
  0x23f50 and their original register-address routines. The worker
  matrix uses mocked parameter operations as before.

## Scope and results

All excluded code is filled with UDF, unknown call relocations
terminate, and hardware accesses go only to explicit fixture mocks.
The fixture includes original locks, status helpers, host transition,
adapter control, rate selection and MAC/bridge enable helpers; no
device register accesses. Cache tuples, PHY registers, clock outcomes,
device type, topology, and time are simulation inputs. Mode-apply,
MAC speed/duplex/pause wrappers in the worker, kernel scheduling and actual clock
hardware are boundaries; neither electrical behavior nor recovery is
proved by this experiment.

37 named cases (25 previous cases plus 12 isolated original ARM parameter cases), plus 2,304
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

See [Linux relink design](linux-relink-plan.md) for a scoped prospective experiment.

## Actual mode-apply boundary (14 additional cases)

Execute original ARM mode application at 0x9c3c, its instance1
wrapper derivation at 0x6b8c and status initialization at 0x92fe0.
The fixture models port1 as forced 2.5G SGMII+ (wrapper12), port2
as PHY24, and third wrapper absent. Port-property answers are
explicit simulation inputs; physical UNIPHY, MAC mux, SYS reset,
port5 clock and mode-apply TX/RX operations remain mock boundaries.
The cache-init literal at 0x930a0 is relocated to a writable
fixture structure with the actual device-context pointer at +0x18.

* Raw PHY mode mismatch invokes mode application on either edge.
  Mode4 => wrapper15 (SGMII); mode6 => wrapper12 (SGMII+).
  With port1 unchanged, mode apply updates wrapper records and
  requests SYS enable for both, then port5 clock-source setup.
  Only changed instance1 executes port2 TX/RX disable, mode set,
  MAC mux set, and status-cache initialization.
* Successful mode change clears cached link, sets speed and duplex
  to 0xffff, leaves non-forced pause cache values intact. Crucially,
  the worker at 0xb074 computes the tuple-changed boolean BEFORE
  mode check at 0xb094. An unchanged tuple + mode mismatch on up
  performs mode apply but skips the explicit clock/rate/adapter
  block, and ends with cached link1 but speed/duplex invalid.
  A subsequent steady-up poll does not repair that cache. The next
  down/up cycle does. A mismatch on down invalidates the cache
  before the following up's tuple comparison, forcing reprogramming.
* A genuine speed change through mode apply executes the clock
  gate/rate/duplex/adapter operations. This is a synthetic control
  path for 2.5G; MAC-specific 2.5G hardware operations remain mocked.
* Injected mode-set or mux failure demonstrates the original worker
  still enables TX/RX/bridge and notifies link up, and the original
  mode record was already updated. Do not reproduce that behavior.

61 named cases and the unchanged 2304-case transition matrix pass.
New cases 47–60 include same-mode controls, up/down mismatch,
both speed transitions, two failures and sequential polls using the
same actual context. This does NOT establish the real PHY mode during
a warm 1G flap. Observe raw C22.31 during down/up before choosing
a new behavioral patch; steady-state 52-field comparisons cannot
exclude transient mode changes. Do not copy shared SYS reset or
port5 operations into the direct-path driver.

## Actual wrapper-15 UNIPHY sequence and force-mode persistence

Ten more original ARM cases execute the wrapper dispatcher at
0x29780, SGMII helper 0x293f0, real register accessors and force
mode RMW 0x7eda0, MPPE calibration restart 0x28b14 and status
poll 0x29140. The device is simulated as MPPE type3, instance1,
port2, non-SFP, QCA8081 ID; force feature and calibration reads
are explicit mock inputs, not measurements of live stock.
The captured stock DTS specifies forced-speed/duplex for port1,
but neither for port2. Chip-enum alternate control produces
identical instance1 result.

The real wrapper-15 instruction sequence writes 0x218=0x30,
requests reset id3 with argument1, gates clocks22/23, programs
0x46c, then RMWs **0x480 bit3** according to feature mask64.
For non-forced port2 it clears bit3; forced control sets it.
It RMWs 0xb4 bit14 high, sleeps10ms, low, sleeps10ms, then
polls 0x1e0 bit7 and restores clocks22/23. Successful result
sets both raw direction clocks to 125MHz. The read-error case
exits with gates still off; timeout case performs 100 status
reads/101 delays, restores gates, returns -23, skips rates.
These failure behaviors are not proposed for Linux.

Cases 66–69 preserve actual emulated register/cache state across
a 2500→1000 down/up and a same-speed down/up. The original stock
worker's later adapter pulse clears/sets bit11 without touching
bit3; ordinary same-tuple reconnect writes neither. The GMAC
speed/duplex helper boundaries remain mocked here, but the
separate original GMAC parameter cases and dispatcher disassembly
confirm their accesses target PPE 0x1204/0x1200, not UNIPHY.
71 named + 2304 matrix cases pass with 710 relocations.

This establishes a concrete stock-vs-Linux policy difference:
the current Linux out-of-band PCS path sets 0x480 bit3, while
stock non-forced SGMII uses it clear. Whether live stock has any
other dependent negotiation setup is still unverified. Do not
blindly clear it in 0497, which isolates timing. After testing
0497, investigate the correct phylink SGMII negotiation model
and PHY-side in-band behavior before a separate intervention.
