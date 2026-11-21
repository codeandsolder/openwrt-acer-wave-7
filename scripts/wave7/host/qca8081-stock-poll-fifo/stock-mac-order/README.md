# 0493 stock-derived GMAC gate ordering experiment

0491 and 0492 failed the real 1G reconnect test. 0492 also failed two
later 2.5G→1G transitions (both recovered at 2.5G). Source/fixture for
the original stock transitions is ../stock-host-replay/.

This patch layers only the GMAC gate sequence over 0492, on the same
exact Wave7 QCA8081 port2 SGMII opt-in. Close bridge TX gate, wait 10 ms,
disable RX only, and retain TX on ordinary media-down. Before PCS
preparation on up, disable TX; program speed/duplex/pause without
enabling the gates; enable TX, RX, then existing flow control/bridge.

The retained-GMAC flag tracks ownership even after a partial write or
error. Quiesce clears bridge and both gates, attempts both operations
even on failure, stops MIB work, and retries on subsequent lifecycle
events if either operation failed. Major configuration quiesces before
reset/mux. After synchronous phylink_stop the EDMA close path quiesces
even when carrier was already down; destruction repeats cleanup after
callbacks are gone. PPE MAC/bridge registers are on the PPE/MAC bus, not
the PCS RX/TX clocks disabled by phylink_stop. No system sleep support
in the exact target config, as in 0492.

This is not complete stock timing parity: PCS preservation, clock rate
programming, MAC tuple parameter writes, MIB handling and BM flow control
are deliberately unchanged. XGMAC and other boards/ports keep their
existing paths. No live writes or changes outside the kernel patch.

Test with `uv run --no-project --offline python test-policy.py PREPARED_KERNEL`.
Actual C functions extracted from the patched tree, explicit mocks at
PCS preparation, clocks, registers and EDMA boundaries. Exercises 20
negotiated tuples, 20 link-up write/failure combinations, both stop paths,
destruction, major config, down/error cleanup and quiesce retry. Untouched
register bits checked. Test success is not hardware proof.
