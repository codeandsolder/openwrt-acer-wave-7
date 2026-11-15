#!/bin/ash
# shellcheck shell=dash
# Temporary on-router self-observer for an already-accepted OpenWrt boot.
# On proven receive-path failure after a real copper link drop, preserve
# kernel evidence, attempt ONE documented QCA8081 copper PHY BMCR reset
# after confirmed zero-RX, and only then panic if traffic remains blocked.
# A new boot then uses the existing
# firstboot watchdog/stock fallback. No reboot for an inconclusive test.
set -eu
# Read-only on-device runtime preflight: no marker, timer, or link change.
if [ "${1:-}" = "--check" ]; then
  test -r /sys/class/net/lan/statistics/rx_packets
  test -r /sys/class/net/lan/carrier
  command -v phytool >/dev/null
  command -v ethtool >/dev/null
  phytool read lan/0x19:1/0x001e
  phytool read lan/0x19:1/0x007d
  ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null
  echo "POSTBOOT_MONITOR_CHECK_PASS rx=$(cat /sys/class/net/lan/statistics/rx_packets)"
  exit 0
fi
path=/tmp/wave7-postboot-link-monitor
logfile=$path.log
ready=$path.ready
donefile=$path.done
expected=$(cat /proc/sys/kernel/random/boot_id)
log() {
  printf '%s\n' "$*" >> "$logfile"
  printf '<6>wave7-postboot-link: %s\n' "$*" > /dev/kmsg
}
start=$(cut -d. -f1 /proc/uptime)
rx0=$(cat /sys/class/net/lan/statistics/rx_packets)
rx_at_up=$rx0
down=0
up=0
up_at=0
failure_proven=0
failure_class=none
log "armed boot=$expected rx0=$rx0 start=$start"
touch "$ready"
while :; do
  now=$(cut -d. -f1 /proc/uptime)
  # Allow the human 15 minutes to make the physical cut. Once the
  # edge occurs, bound the diagnostic window to 110 seconds.
  if [ "$down" = 0 ]; then
    [ $((now - start)) -lt 900 ] || break
  else
    [ $((now - down_at)) -lt 110 ] || break
  fi
  carrier=$(cat /sys/class/net/lan/carrier 2>/dev/null || echo unknown)
  if [ "$carrier" = 0 ] && [ "$down" = 0 ]; then
    down=1
    down_at=$now
    printf '%s\n' "$expected" > /tmp/wave7-postboot-link-monitor.down
    log "physical-copper-DOWN t=$now"
  fi
  if [ "$carrier" = 1 ] && [ "$down" = 1 ] && [ "$up" = 0 ]; then
    up=1
    up_at=$now
    rx_at_up=$(cat /sys/class/net/lan/statistics/rx_packets)
    log "physical-copper-UP t=$now rx_at_up=$rx_at_up"
  fi
  if [ "$up" = 1 ] && [ $((now - up_at)) -ge 7 ]; then
    rx1=$(cat /sys/class/net/lan/statistics/rx_packets)
    peer_ok=0
    if ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null 2>&1; then
      peer_ok=1
    fi
    if [ "$peer_ok" = 1 ] && [ "$rx1" -gt "$rx_at_up" ]; then
      log "SUCCESS after-flap peer2-of-2 rx_at_up=$rx_at_up rx_after=$rx1 elapsed=$((now - start))s"
      # Healthy post-flap SerDes register comparison against the failed path.
      if command -v phytool >/dev/null 2>&1; then
        for reg in 0x0009 0x001e 0x001f 0x006e 0x007d 0x9072; do
          value=$(phytool read "lan/0x19:1/$reg" 2>&1 || echo READ_ERROR)
          log "serdes[recovered].$reg=$value"
        done
      fi
      ethtool -S lan | grep -E 'rx_frames:|tx_frames:|rx_crc_err:' |
        head -12 | while IFS= read -r line; do log "mib[recovered] $line"; done
      printf 'SUCCESS boot=%s rx_at_up=%s rx1=%s\n' "$expected" "$rx_at_up" "$rx1" > "$donefile"
      exit 0
    fi
    if [ $((now - up_at)) -ge 30 ]; then
      if [ "$rx1" -gt "$rx_at_up" ]; then
        # Physical RX advanced, but the management peer is still
        # unreachable: distinct L2/L3/asymmetric-path failure. Recover
        # the router anyway, after preserving that classification.
        failure_class=peer_unreachable_rx_advanced
        log "PEER_UNREACHABLE_GMAC_RX_ADVANCED from=$rx_at_up to=$rx1 elapsed=$((now - start))s"
      else
        failure_class=peer_unreachable_rx_stalled
        log "RX_STALLED_30S_AFTER_LINK_UP peer_ok=$peer_ok rx_at_up=$rx_at_up rx_after=$rx1 elapsed=$((now - start))s"
      fi
      failure_proven=1
      break
    fi
  fi
  sleep 1
done
if [ "$failure_proven" = 1 ]; then
  log "POSTBOOT_PEER_FAILURE class=$failure_class: save PHY PCS and GMAC diagnostics before watchdog panic"
  for name in carrier operstate speed; do
    val=$(cat "/sys/class/net/lan/$name" 2>/dev/null || echo unavailable)
    log "lan.$name=$val"
  done
  val=$(cat /sys/class/net/lan/statistics/rx_packets)
  log "lan.rx_packets=$val"
  # Read-only, bounded SerDes pseudo-PHY+1 diagnostics. Register 0x001e
  # has UNKNOWN field semantics; record only the raw value. 0x006e belongs
  # to PRBS test logic and must not be called a normal-traffic CDR lock bit.
  if command -v phytool >/dev/null 2>&1; then
    for reg in 0x0009 0x001e 0x001f 0x006e 0x006f 0x007d 0x9072; do
      value=$(phytool read "lan/0x19:1/$reg" 2>&1 || echo READ_ERROR)
      log "serdes_mmd1.$reg=$value"
    done
  fi
  # Bounded excerpts to retain ring space, not entire debugfs.
  if [ -r /sys/kernel/debug/ipq-pcs-7a10000.ethernet-pcs/link_state ]; then
    head -45 /sys/kernel/debug/ipq-pcs-7a10000.ethernet-pcs/link_state |
    while IFS= read -r line; do log "pcs $line"; done
  fi
  if [ -r /sys/kernel/debug/ppe/port_rx ]; then
    head -22 /sys/kernel/debug/ppe/port_rx |
    while IFS= read -r line; do log "ppe $line"; done
  fi
  ethtool -S lan | grep -E 'rx_frames:|tx_frames:|rx_errors:|rx_crc_errors:' |
    head -15 | while IFS= read -r line; do log "mib $line"; done
  # Distinct from PCS reinitialization or SerDes FIFO reset:
  # genphy_soft_reset() writes BMCR_RESET to the *copper* PHY, and the
  # MDIO ioctl (phy_mii_ioctl) re-runs phy_init_hw() after a BMCR reset.
  # We only attempt it when PHY copper link is UP but GMAC RX is stalled.
  # The separate on-device hard guard will still reboot at its deadline
  # if this monitor, the reset, or the test fails.
  if [ "$failure_class" = peer_unreachable_rx_stalled ] &&
     [ "$(cat /sys/class/net/lan/carrier 2>/dev/null)" = 1 ]; then
    log "qca8081-soft-reset-before bmcr=$(phytool read lan/0x18/0x00 2>&1 || echo READ_ERROR) irq_status=$(phytool read lan/0x18/0x13 2>&1 || echo READ_ERROR)"
    log "qca8081-soft-reset-begin bmcr_reset=0x8000"
    if phytool write lan/0x18/0x00 0x8000 >> "$logfile" 2>&1; then
      log "qca8081-soft-reset-write-returned-success"
      # Polling bounds: max 40 iterations, each <3s including two ICMP
      # probes. Recovery is accepted only with fresh hardware RX frames.
      attempt=0
      while [ "$attempt" -lt 40 ]; do
        attempt=$((attempt + 1))
        sleep 1
        test "$(cat /proc/sys/kernel/random/boot_id)" = "$expected" || exit 3
        carrier=$(cat /sys/class/net/lan/carrier 2>/dev/null || echo unknown)
        post_rx=$(cat /sys/class/net/lan/statistics/rx_packets)
        if [ "$carrier" = 1 ] &&
           [ "$post_rx" -gt "$rx1" ] &&
           ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null 2>&1; then
          log "RECOVERED_PHY_SOFT_RESET attempts=$attempt rx_before=$rx1 rx_after=$post_rx carrier=1"
          ethtool -S lan | grep -E 'rx_frames:|tx_frames:|rx_crc_err:' |
            head -8 | while IFS= read -r line; do log "mib[after-reset] $line"; done
          printf 'SUCCESS_PHY_SOFT_RESET boot=%s before=%s after=%s attempts=%s\n'             "$expected" "$rx1" "$post_rx" "$attempt" > "$donefile"
          exit 0
        fi
        if [ $((attempt % 8)) -eq 0 ]; then
          log "qca8081-soft-reset-progress attempt=$attempt carrier=$carrier rx=$post_rx rx_before=$rx1"
        fi
      done
      log "qca8081-soft-reset-FAILED no durable RX+peer within 40 cycles"
    else
      log "qca8081-soft-reset-WRITE_ERROR"
    fi
  fi
  log "qca8081-soft-reset-diagnostic-reboot class=$failure_class"
  sync
  echo c > /proc/sysrq-trigger
  exit 5
fi
log "INCONCLUSIVE did_not_observe_both_edges down=$down up=$up"
printf 'INCONCLUSIVE down=%s up=%s\n' "$down" "$up" > "$donefile"
exit 6
