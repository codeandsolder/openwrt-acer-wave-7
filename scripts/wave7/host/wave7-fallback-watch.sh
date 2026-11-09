#!/usr/bin/env bash
set -u
TAG=${1:?usage: wave7 watcher <trial-tag>}
LOG=/tmp/wave7-${TAG}-fallback-watch.log
OUT=/tmp/wave7-${TAG}-pstore.txt
RAW=/tmp/wave7-${TAG}-ramoops-raw.bin
SSH=(ssh -F /home/jan/.ssh/config -o BatchMode=yes \
    -o ConnectTimeout=3 -o ConnectionAttempts=1 \
    -o ServerAliveInterval=4 -o ServerAliveCountMax=2 wave7)
: > "$LOG"
rm -f "$OUT"
armed=0
down=0
for i in $(seq 1 3600); do
  k=$("${SSH[@]}" 'uname -r' 2>/dev/null || true)
  if [ "$k" = 5.4.213 ]; then
    if [ "$armed" -eq 1 ]; then
      echo "$(date -Is) vendor-reappeared" >> "$LOG"
      # Save the raw 1 MiB ramoops region. This is needed because the
      # vendor armv7 pstore decoder may not understand AArch64 records.
      if timeout 25 "${SSH[@]}" 'dd if=/dev/mem bs=4096 skip=322048 count=256 2>/dev/null' > "$RAW.part" &&
         [[ $(stat -c %s "$RAW.part") == 1048576 ]]; then
        mv -f -- "$RAW.part" "$RAW"
        echo "$(date -Is) raw-ramoops-saved bytes=1048576 sha256=$(sha256sum "$RAW" | cut -d" " -f1)" >> "$LOG"
      else
        rm -f -- "$RAW.part"
        echo "$(date -Is) raw-ramoops-unavailable" >> "$LOG"
      fi
      "${SSH[@]}" 'mount -t pstore pstore /sys/fs/pstore 2>/dev/null || true' >/dev/null 2>&1 || true
      for j in $(seq 1 90); do
        if "${SSH[@]}" 'set -- /sys/fs/pstore/*-ramoops-*; [ -f "$1" ]' >/dev/null 2>&1; then
          break
        fi
        sleep 1
      done
      {
        echo "captured_at=$(date -Is)"
        "${SSH[@]}" '
          echo ===UNAME===; uname -a
          echo ===BOOTFAIL===; fw_printenv -n bootfail 2>/dev/null || true
          echo ===CMDLINE===; cat /proc/cmdline
          echo ===PSTORE_LS===; ls -la /sys/fs/pstore 2>&1 || true
          for f in /sys/fs/pstore/*; do
            [ -f "$f" ] || continue
            echo "===PSTORE:$f==="
            cat "$f"
          done
        '
      } > "$OUT" 2>&1
      echo "$(date -Is) capture=$OUT" >> "$LOG"
      systemctl --user stop "wave7-openwrt-watch-$TAG.service" >/dev/null 2>&1 || true
      exit 0
    fi
    down=0
  else
    down=$((down + 1))
    if [ "$down" -ge 3 ] && [ "$armed" -eq 0 ]; then
      armed=1
      echo "$(date -Is) transition-armed-after-${down}-failures" >> "$LOG"
    fi
  fi
  sleep 1
done
echo "$(date -Is) timeout" >> "$LOG"
exit 1
