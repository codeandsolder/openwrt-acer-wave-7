#!/bin/ash
# Temporary on-router self-observer for an already-accepted OpenWrt boot.
# On proven receive-path failure after a real copper link drop, preserve
# kernel evidence by sysrq panic. A new boot then uses the existing
# firstboot watchdog/stock fallback. No reboot for an inconclusive test.
set -eu
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
  [ $((now - start)) -lt 110 ] || break
  carrier=$(cat /sys/class/net/lan/carrier 2>/dev/null || echo unknown)
  if [ "$carrier" = 0 ] && [ "$down" = 0 ]; then
    down=1
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
  sync
  echo c > /proc/sysrq-trigger
  exit 5
fi
log "INCONCLUSIVE did_not_observe_both_edges down=$down up=$up"
printf 'INCONCLUSIVE down=%s up=%s\n' "$down" "$up" > "$donefile"
exit 6
