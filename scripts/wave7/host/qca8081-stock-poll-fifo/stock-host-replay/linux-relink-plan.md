# Conditional PCS preservation — prospective experiment

Status: design only, not a kernel patch or an observed fix. The existing
0491 build must first undergo the matched 1G reconnect test. If 0491
works, do not add a new intervention merely to approximate stock.

## Decision boundary

Original stock replay establishes that the full speed/duplex/TX pause/RX
pause tuple, not speed alone or carrier, selects the explicit host clock
and adapter-reset block. Interface mode is checked separately. The
unaltered stock mode-apply boundary may still reconfigure on a mismatch.
In particular, never infer that an interface enum alone guarantees a
usable PCS.

The prepared Linux 6.18.60 sources (prod-integrated) have these relevant
differences:

- 0479 defers initial MPPE index0 outband SGMII configuration until
  actual link-up; preserve this behavior.
- 0480 executes full `ipq_pcs_config_mode` on every such up event.
  `ipq_pcs_link_up_config_sgmii` also pulses the adapter independently.
  Suppressing only the former does not reproduce preservation.
- `ipq_pcs_config_mode` gates clocks, sets mode, resets and calibrates
  the PCS, sets reference/clock-out configuration and clock rates.
  `qpcs->interface` is published before all those operations finish and
  participates in clock-provider rate selection. It is NOT a validity
  flag; don't just move its assignment to the end.
- Phylink calls `pcs_link_up` before `mac_link_up`. Its PCS callback
  receives the resolved speed and duplex but not resolved pause flags.
  The MAC callback receives the complete tuple. Both callbacks are void.
- `ppe_port_mac_config` resets the MAC clocks and sets its mux. It runs
  on major configuration. `ppe_port_mac_link_up` programs the clocks,
  GMAC, BM flow control and bridge. Link-down disables bridge and MAC.
- `phylink_stop` disables PCS after ordinary link-down. A later start
  must not be treated as an ordinary warm cable reconnect.

## Proposed ownership and scope

Keep the experiment local to the exact Acer Wave7 direct QCA8081
(004dd101) port2 / UNIPHY1 / MPPE index0, resolved out-of-band SGMII,
selected during initialization from board and topology. Do not change
the RTL8367D path, 2.5G BASE-X/XGMAC path, phylink-wide callback ABI,
PHY 0491 behavior, or Wi-Fi. No private phylink structure access.

Use a coordinated PPE-owned link-up path for the opt-in case: PCS
link-up callback defers that case to an explicit internal PCS helper;
the PPE callback calls the helper immediately before the existing MAC
sequence with the full resolved tuple. A tuple cache spans the
successful link-up and ordinary link-down, not major reconfiguration.
Keep the standard callback paths for every non-opt-in case. This
proposal needs a careful implementation review of callback context,
module dependencies and initialization/teardown before a build.

A valid cache requires both PCS preparation and the existing complete
MAC/bridge programming to have succeeded. Clear validity before a new
transaction. A warm preservation decision uses the previous valid
record, an identical interface, negotiation mode, speed, duplex and
both pauses, and no invalidation since that record. A successful
transaction commits the new complete tuple only after the bridge is
enabled. Failed PCS configuration must prevent MAC/bridge enable;
failed MAC programming must leave the cache invalid and log the
failure. Since phylink's callbacks are void, carrier alone is not a
successful-configuration indication. Existing phylink error semantics
are a separate issue, not a reason to silently ignore errors.

Invalidation: major configuration, MAC reset or failed config,
PCS config/enable/disable, mode or negotiation change, stop, suspend,
remove, unsuccessful link-down, and any failed prepare or commit.
Ensure invalidation from either layer cannot be hidden by a stale
cache in the other. Use explicit lifecycle/generation state under the
existing phylink callback serialization; never use elapsed time or
the interface enum as a substitute. Verify all reset paths and
suspend/resume before claiming cache validity. The initial
link-down/up sequence after boot must still perform full preparation.

First intervention: on a valid same-tuple warm reconnect, skip BOTH
full PCS mode reinitialization and adapter pulse; retain ordinary
MAC up/down and existing MAC-side clock/flow-control programming.
Do not assume clk_set_rate with an unchanged requested rate causes
no hardware accesses; distinguish any such accesses in telemetry.
Stock's different bridge delay and TX gating, and extra status worker,
remain separate follow-ups, not part of this intervention. For all
cold, changed-tuple, invalidated or failed previous transactions,
retain the current full preparation path. This is deliberately a
test of one host-side difference, not an attempt at wholesale parity.

## Evidence gates

- Exercise cold, ordinary down/up unchanged, changed speed/duplex/TX
  or RX pause individually, interface change and return, forced major
  configuration, stop/start, suspend/resume. Inject failures in PCS
  prepare and MAC/bridge steps. No skip after invalidation or failed
  prepare/commit. Test the real implementation, not a duplicated
  model alone.
- Confirm unchanged nonopt-in paths; inspect the exact build and ABI
  of any added PCS/PPE symbol, including module dependencies. Build
  with managed sccache, preserve current integration and rollback
  artifact, verify pinned images and metadata.
- Log the decision (cold/changed/invalidated/preserved) with speed,
  duplex and pauses and success/failure. Validate first link-up,
  1G warm reconnect and 2.5G unchanged behavior independently.
- On the router the matched 1G experiment must use an independent
  switch management path, peer traffic throughout the measurement
  window, unchanged boot UUID, and both ends confirmed 1G. Record
  PHY copper ingress and external MAC ingress, GMAC RX/TX and
  bounded timestamps together; do not destructively read MMD7
  counters to obtain a second sample. Observe >30s after link-up.
  A carrier-only success or nonmatching transition is inconclusive.
- If preservation fails, compare timings with the stock replay before
  proposing another intervention. Do not repeat already-negative
  blanket resets or tune several variables at once.
