#!/usr/bin/env bash
set -u
TAG=${1:?usage: wave7 watcher TRIAL_TAG EXPECT_KERNEL EXPECT_REV}
EXPECT_KERNEL=${2:?expected Linux kernel version required}
EXPECT_REV=${3:?expected 10-character git SHA required}
[[ $TAG =~ ^[A-Za-z0-9._-]+$ && $EXPECT_KERNEL =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $EXPECT_REV =~ ^[0-9a-f]{10}$ ]] || exit 2
LOG=/tmp/wave7-${TAG}-openwrt-watch.log
OUT=/tmp/wave7-${TAG}-openwrt-capture.txt
SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
[[ -x "$SCRIPT_DIR/verify-factory-mtd.sh" && -s "$SCRIPT_DIR/factory-mtd.tsv" ]] || {
  echo "Missing Wave 7 factory MTD validator or fixture" >&2
  exit 2
}
SSH=(ssh -n -i /home/jan/.ssh/wave7-root-rsa -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=2 -o ConnectionAttempts=1 -o ServerAliveInterval=4 -o ServerAliveCountMax=2 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@192.168.76.1)
: > "$LOG"
rm -f "$OUT"
detected=0
for i in $(seq 1 3600); do
  ver=$("${SSH[@]}" 'uname -r' 2>/dev/null || true)
  if [ "$ver" = "$EXPECT_KERNEL" ]; then
    rev=$("${SSH[@]}" "sed -n 's/^DISTRIB_REVISION=//p' /etc/openwrt_release" 2>/dev/null || true)
    if [[ $rev != *"$EXPECT_REV"* ]]; then
      echo "$(date -Is) revision-mismatch expected=$EXPECT_REV got=$rev" >> "$LOG"
      sleep 2
      continue
    fi
    if [ "$detected" -eq 0 ]; then
      echo "$(date -Is) openwrt-detected" >> "$LOG"
      detected=1
    fi

    if "${SSH[@]}" 'ping -I br-lan -c 1 -W 1 192.168.76.2' >/dev/null 2>&1; then
      {
        echo "captured_at=$(date -Is)"
        timeout 30 "${SSH[@]}" '
          echo ===UNAME===; uname -a
          echo ===UPTIME===; cat /proc/uptime
          echo ===BOARD===; ubus call system board 2>&1 || true
          echo ===IP_LINK===; ip -d link show 2>&1 || true
          echo ===IP_ADDR===; ip addr show 2>&1 || true
          echo ===IP_ROUTE===; ip route show 2>&1 || true
          echo ===MDIO===; ls -l /sys/bus/mdio_bus/devices 2>&1 || true
          echo ===NAND_MTD===; cat /proc/mtd 2>&1 || true
          echo ===NAND_SPI_DEVICES===; ls -l /sys/bus/spi/devices 2>&1 || true
          echo ===NAND_UBI===; ubinfo -a 2>&1 || true
          echo ===ETHTOOL_LAN===; ethtool lan 2>&1 || true
          echo ===WIFI_FIRMWARE===; ls -l /lib/firmware/ath12k/IPQ5332/hw1.0 2>&1 || true
          echo ===MODULES===; lsmod 2>&1 || true
          echo ===REMOTEPROC===
          for r in /sys/class/remoteproc/remoteproc*; do
            [ -e "$r" ] || continue
            echo "--- $r"
            for f in name state firmware recovery; do
              [ -r "$r/$f" ] && { printf "%s=" "$f"; cat "$r/$f"; }
            done
          done
          echo ===QRTR===; ls -la /sys/bus/qrtr/devices 2>&1 || true
          echo ===IW_PHY===; iw phy 2>&1 || true
          echo ===IW_DEV===; iw dev 2>&1 || true
          echo ===WIRELESS_UBUS===; ubus call network.wireless status 2>&1 || true
          echo ===MLO_VALIDATION===
          rproc_running=0
          for r in /sys/class/remoteproc/remoteproc*; do
            [ -r "$r/state" ] || continue
            [ "$(cat "$r/state")" = running ] && rproc_running=$((rproc_running + 1))
          done
          iw_summary=$(iw dev 2>/dev/null || true)
          if [ "$rproc_running" -ge 3 ] &&
             printf "%s\n" "$iw_summary" | grep -Fq "MLD with links:" &&
             printf "%s\n" "$iw_summary" | grep -Eq "link ID[[:space:]]+0" &&
             printf "%s\n" "$iw_summary" | grep -Eq "link ID[[:space:]]+1"; then
            echo RADIO_MLO_READY=1
          else
            echo RADIO_MLO_READY=0
          fi
          echo ===PEER===
          if ping -I br-lan -c 3 -W 1 192.168.76.2; then
            echo PEER_REACHABLE=1
            # The on-router firstboot watchdog owns the safety decision.
            # A successful network ping alone must never disarm it.
            if [ -e /tmp/wave7-keep-boot ]; then
              echo KEEP_BOOT_ARMED=1
            else
              echo KEEP_BOOT_ARMED=0
            fi
          else
            echo PEER_REACHABLE=0
            echo KEEP_BOOT_ARMED=0
          fi
          echo ===DMESG_RELEVANT===; dmesg | grep -Ei "ath12k|remoteproc|q6|wcss|qmi|qrtr|firmware|scm|qca808|sgmii|mppe|pcs|ppe|clock|phylink|mdio|qpic|snand|nand|mtd|ubi|bam|spi|wave7|panic" || true
          echo ===DMESG_FULL===; dmesg
          echo ===LOGREAD===; logread 2>&1 || true
        '
      } > "$OUT" 2>&1
      echo '===NAND_LAYOUT_VALIDATION===' >> "$OUT"
      if validation=$("$SCRIPT_DIR/verify-factory-mtd.sh" --capture "$OUT" 2>&1); then
        printf '%s\nNAND_SMEMPART_READY=1\n' "$validation" >> "$OUT"
      else
        printf '%s\nNAND_SMEMPART_READY=0\n' "$validation" >> "$OUT"
      fi
      echo "$(date -Is) capture=$OUT" >> "$LOG"
      if rg -q '^KEEP_BOOT_ARMED=1$' "$OUT" &&
         rg -q '^RADIO_MLO_READY=1$' "$OUT"; then
        # Capture stays active until both Wi-Fi links and Q6 are up.
        echo "$(date -Is) radio-ready; fallback collector retained" >> "$LOG"
        exit 0
      fi
      # Do not poll full remote snapshots every second.
      sleep 14
    fi
  fi
  sleep 1
done
echo "$(date -Is) timeout" >> "$LOG"
exit 1
