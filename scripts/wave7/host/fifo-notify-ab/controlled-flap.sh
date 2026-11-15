#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
action=${1:---check}
case "$action" in --help|-h) echo "usage: $0 [--check|--run]"; exit 0;; --check|--run) ;; *) exit 2;; esac

root=/home/jan/scripts/wave7/fifo-notify-ab
base=/home/jan/firmware/wave7/trials/20261115-fifo-notify-ab/postboot
mkdir -p "$base"
ssh_wave() {
  ssh -n -i /home/jan/.ssh/wave7-root-rsa -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 \
   -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@192.168.76.1 "$@"
}
ssh_redmi() {
  ssh -n -J acer -o BatchMode=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=accept-new root@10.1.0.2 "$@"
}
[[ "$(id -un)" == jan ]] || exit 2
exec 9>"$base/.controlled-flap.lock"
flock -n 9 || { echo 'Another controlled link-flap run is in progress' >&2; exit 2; }
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}
test -z "$(systemctl --user --no-pager --no-legend list-units --state=active 'wave7-openwrt-watch-*' 'wave7-fallback-watch-*')"
# Asus Tailscale policy routes 10.1.0.2 via table 52; the Acer jump
# is independent of Wave7 and Redmi restores its own physical port.
ssh_redmi 'test -f /etc/openwrt_release; test "$(cat /sys/class/net/lan2/operstate)" = up' >/dev/null
expected=$(sha256sum "$root/wave7-postboot-link-monitor.sh" | cut -d' ' -f1)
[[ "$expected" == 154d39ed88663cdafc457f080bc34904a9ebb5c7f45bf881a975c6147f2466c6 ]]
old=$(ssh_wave '
 set -eu
 test "$(uname -r)" = 6.18.60
 grep -q 0078d29fd0 /etc/openwrt_release
 test "$(fw_printenv -n bootfail)" = 0
 test -f /tmp/wave7-keep-boot
 test -f /tmp/wave7-autoprobe-success
 test "$(cat /sys/class/net/lan/carrier)" = 1
 test "$(iw dev | grep -Ec "link ID[[:space:]]+[01]")" = 2
 test ! -e /tmp/wave7-postboot-link-monitor.ready
 test ! -e /tmp/wave7-postboot-link-monitor.done
 ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null
 echo "$(cat /proc/sys/kernel/random/boot_id)"
')
[[ $old =~ ^[a-f0-9-]{36}$ ]]
ssh_redmi '
  set -eu
  test "$(cat /sys/class/net/lan2/carrier)" = 1
  test "$(cat /sys/class/net/lan2/operstate)" = up
  ip addr show lan2 | grep -q "192.168.76.2/24"
  ip addr show br-lan | grep -q "10.1.0.2/16"
  test ! -e /tmp/wave7-postboot-port-restore.pid
  command -v start-stop-daemon >/dev/null
'
printf 'PREFLIGHT_PASS Wave7=%s Redmi=10.1.0.2 dedicated_port=lan2; read-only=%s\n' "$old" "$([[ $action == --check ]] && echo yes || echo no)"
if [[ $action == --check ]]; then exit 0; fi

tag="fifo-preserved-carrier-flap-$(date +%Y%m%d-%H%M%S)"
out="$base/$tag"
mkdir -p "$out"
printf 'Wave7 boot_id=%s\nMonitor SHA256=%s\n' "$old" "$expected" > "$out/preflight.txt"
log() { echo "$(date -Is) $*" | tee -a "$out/orchestrator.log"; }
waveunit="wave7-openwrt-watch-$tag.service"
fallbackunit="wave7-fallback-watch-$tag.service"
armed=0
complete=0
cut=0
peer_probe_pid=0
cleanup() {
  code=$?
  trap - EXIT
  if (( peer_probe_pid )); then
    kill "$peer_probe_pid" 2>/dev/null || :
    wait "$peer_probe_pid" 2>/dev/null || :
  fi
  if (( armed )); then
    for suffix in openwrt-watch.log fallback-watch.log openwrt-capture.txt pstore.txt ramoops-raw.bin; do
      f=/tmp/wave7-$tag-$suffix
      [[ ! -s $f ]] || cp -p "$f" "$out/" || :
    done
    if (( complete || ! cut )); then
      # Before a link cut, cancel the guard even if setup failed; leaving
      # the 145s timer active after an aborted trial risks a false reboot.
      ssh_wave 'rm -f /tmp/wave7-postboot-trial.arm /tmp/wave7-postboot-link-monitor.ready /tmp/wave7-postboot-link-monitor.done; for pf in /tmp/wave7-postboot-hard-guard.pid /tmp/wave7-postboot-monitor.pid; do if test -s "$pf"; then kill "$(cat "$pf")" 2>/dev/null || :; fi; done; rm -f /tmp/wave7-postboot-hard-guard.pid /tmp/wave7-postboot-monitor.pid' >/dev/null 2>&1 || :
      systemctl --user stop "$waveunit" "$fallbackunit" >/dev/null 2>&1 || :
    else
      log 'Interrupted trial after link cut: recovery guards remain armed.'
    fi
  elif (( ! cut )); then
    # Failure during file staging, before either external observer exists.
    ssh_wave 'rm -f /tmp/wave7-postboot-link-monitor.sh /tmp/wave7-postboot-hard-guard.sh' >/dev/null 2>&1 || :
  fi
  exit "$code"
}
trap cleanup EXIT

scp -q -O -i /home/jan/.ssh/wave7-root-rsa -o BatchMode=yes -o IdentitiesOnly=yes \
 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
 "$root/wave7-postboot-link-monitor.sh" root@192.168.76.1:/tmp/wave7-postboot-link-monitor.sh
actual=$(ssh_wave 'sha256sum /tmp/wave7-postboot-link-monitor.sh' | cut -d' ' -f1)
[[ "$actual" == "$expected" ]]
scp -q -O -i /home/jan/.ssh/wave7-root-rsa -o BatchMode=yes -o IdentitiesOnly=yes  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null  "$root/wave7-postboot-hard-guard.sh" root@192.168.76.1:/tmp/wave7-postboot-hard-guard.sh
guard_hash=$(sha256sum "$root/wave7-postboot-hard-guard.sh" | cut -d' ' -f1)
[[ "$guard_hash" == fc132414ebd84e1d8a8505d906fc018a34566ede78e53a7c47cedaeec9f9db14 ]]
remote_guard_hash=$(ssh_wave 'sha256sum /tmp/wave7-postboot-hard-guard.sh' | cut -d' ' -f1)
[[ "$remote_guard_hash" == "$guard_hash" ]]
ssh_wave 'chmod 700 /tmp/wave7-postboot-link-monitor.sh /tmp/wave7-postboot-hard-guard.sh; test -c /dev/kmsg; test -w /proc/sysrq-trigger; test "$(cat /proc/sys/kernel/panic)" -ge 1; /bin/ash /tmp/wave7-postboot-link-monitor.sh --check; /bin/ash /tmp/wave7-postboot-hard-guard.sh --check' > "$out/ondevice-preflight.txt"
log "On-router recovery observer staged; original healthy boot=$old"
systemd-run --user --quiet --unit="wave7-openwrt-watch-$tag" \
 --property=RuntimeMaxSec=900 -- \
 /home/jan/scripts/wave7/controlled-link/watch-new-boot-id.sh "$tag" "$old" 0078d29fd0
armed=1
systemd-run --user --quiet --unit="wave7-fallback-watch-$tag" \
 --property=RuntimeMaxSec=900 -- /home/jan/scripts/wave7/wave7-fallback-watch.sh "$tag"
armed=1
systemctl --user is-active --quiet "$waveunit"
systemctl --user is-active --quiet "$fallbackunit"
ssh_wave 'set -eu
 test ! -e /tmp/wave7-postboot-trial.arm
 trial=$(cat /proc/sys/kernel/random/uuid)
 test -n "$trial"
 printf "%s\n" "$trial" > /tmp/wave7-postboot-trial.arm
 test ! -e /tmp/wave7-postboot-hard-guard.pid
 start-stop-daemon -S -b -m -p /tmp/wave7-postboot-hard-guard.pid   -x /bin/ash -- /tmp/wave7-postboot-hard-guard.sh "$(cat /proc/sys/kernel/random/boot_id)" "$trial"   </dev/null >/dev/null 2>&1 || :
 sleep 1
 test -s /tmp/wave7-postboot-hard-guard.pid
 kill -0 "$(cat /tmp/wave7-postboot-hard-guard.pid)"
 echo HARD_GUARD_ARMED
' > "$out/router-hard-guard.txt"
ssh_wave 'set -eu
 start-stop-daemon -S -b -m -p /tmp/wave7-postboot-monitor.pid   -x /bin/ash -- /tmp/wave7-postboot-link-monitor.sh   </dev/null >/dev/null 2>&1 || :
'
for i in 1 2 3 4 5; do
  ssh_wave 'test -f /tmp/wave7-postboot-link-monitor.ready' && break || sleep 1
done
ssh_wave 'test -f /tmp/wave7-postboot-link-monitor.ready; test ! -f /tmp/wave7-postboot-link-monitor.done'
log 'Local monitor and independent timed hard recovery guard both armed.'
# Independent traffic witness runs through Acer/Redmi Wi-Fi management.
# Data packets are bound to Redmi lan2; 90 single-packet probes only.
# Thus a PHY RX=0 result is not mistaken for peer silence.
ssh_redmi 'ping -I lan2 -c 2 -W 1 192.168.76.1 >/dev/null'
ssh_redmi 'for n in rx_packets tx_packets rx_bytes tx_bytes; do printf "%s=" "$n"; cat "/sys/class/net/lan2/statistics/$n"; done' > "$out/redmi-lan2-before.txt"
(
 ssh_redmi 'i=0; while [ "$i" -lt 90 ]; do
  printf "probe=%s time=%s " "$i" "$(date -Is)"
  ping -I lan2 -c 1 -W 1 192.168.76.1 2>&1 | tail -n 4
  i=$((i+1))
  sleep 1
 done'
) > "$out/redmi-peer-probes.log" 2>&1 &
peer_probe_pid=$!
ssh_wave 'echo ====PCS1_HEALTHY====; cat /sys/kernel/debug/ipq-pcs-7a10000.ethernet-pcs/link_state; echo ====SERDES1_HEALTHY====; for r in 0x0009 0x001e 0x001f 0x006e 0x007d 0x9072; do printf "%s " "$r"; phytool read lan/0x19:1/$r; done' > "$out/pcs-healthy-before-flap.txt"
for field in pll_reset clkout_50m_ctrl link_detect; do rg -q "^$field=" "$out/pcs-healthy-before-flap.txt"; done
log 'Redmi active peer traffic witness running; 90 probes toward Wave7 copper.'
log 'Monitor ready, both recovery observers active. Triggering ONE 9-second copper link drop on Redmi lan2.'
ssh_redmi 'set -eu
 test ! -e /tmp/wave7-postboot-port-restore.pid
 start-stop-daemon -S -b -m -p /tmp/wave7-postboot-port-restore.pid   -x /bin/sh -- -c "exec >/dev/null 2>&1; sleep 9; ip link set lan2 up; logger -t wave7-postboot restored-lan2; rm -f /tmp/wave7-postboot-port-restore.pid" || :
 sleep 1
 test -s /tmp/wave7-postboot-port-restore.pid
 kill -0 "$(cat /tmp/wave7-postboot-port-restore.pid)"
 echo REDMI_RESTORE_TIMER_ARMED
' > "$out/redmi-control.txt" 2>&1
# The link cut can interrupt SSH. Restore is already independently armed.
cut=1
ssh_redmi 'ip link set lan2 down' >> "$out/redmi-control.txt" 2>&1 || :
log 'Redmi lan2 cut with independent nine-second restore armed.'
sleep 13
ssh_redmi 'echo DATE=$(date -Is); echo OPERSTATE=$(cat /sys/class/net/lan2/operstate); echo CARRIER=$(cat /sys/class/net/lan2/carrier); logread | grep -F wave7-postboot | tail -4' \
 > "$out/redmi-restored.txt" 2>&1 || :
if ! ssh_redmi 'test "$(cat /sys/class/net/lan2/operstate)" = up; test "$(cat /sys/class/net/lan2/carrier)" = 1'; then
  log 'Redmi auto-restoration not yet verified; forcing dedicated port UP.'
  ssh_redmi 'ip link set lan2 up' || :
fi
log 'Redmi physical interface restored; checking Wave7 on-router result.'
ssh_redmi 'for n in rx_packets tx_packets rx_bytes tx_bytes; do printf "%s=" "$n"; cat "/sys/class/net/lan2/statistics/$n"; done' > "$out/redmi-lan2-after.txt" || :
postpanic_recovered=0
postpanic_pstore_copied=0
for ((i=1; i<=100; i++)); do
  result=$(ssh_wave 'cat /tmp/wave7-postboot-link-monitor.done 2>/dev/null' 2>/dev/null || :)
  if [[ $result == SUCCESS* ]]; then
    log "WAVE7_MONITOR_$result"
    ssh_wave 'cat /tmp/wave7-postboot-link-monitor.log' > "$out/wave7-monitor.log"
    ssh_wave 'dmesg; echo ===GMAC===; ethtool -S lan; echo ===PPE===; cat /sys/kernel/debug/ppe/port_rx' \
     > "$out/wave7-posttest-dmesg-and-mib.txt"
    test "$(ssh_wave 'fw_printenv -n bootfail')" = 0
    test "$(ssh_wave 'cat /proc/sys/kernel/random/boot_id')" = "$old"
    a=$(ssh_wave 'cat /sys/class/net/lan/statistics/rx_packets')
    ssh_wave 'ping -I br-lan -c 3 -W 1 192.168.76.2' > "$out/peer-check.txt"
    b=$(ssh_wave 'cat /sys/class/net/lan/statistics/rx_packets')
    [[ "$b" =~ ^[0-9]+$ && "$a" =~ ^[0-9]+$ && b -gt a ]]
    log "ACCEPTED: Same boot; copper link recovered; received packets $a->$b."
    complete=1
    break
  fi
  if [[ $result == INCONCLUSIVE* ]]; then
    log "INCONCLUSIVE: $result"
    complete=1
    break
  fi
  # A failed monitored trial causes a planned SysRq panic. The monitor's
  # /tmp result disappears, so assess the *new* boot independently, while
  # preserving pstore from the failed boot before observer cleanup.
  changed_boot=$(ssh_wave 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null || :)
  if [[ $changed_boot =~ ^[a-f0-9-]{36}$ && $changed_boot != "$old" ]]; then
    if (( ! postpanic_pstore_copied )); then
      ssh_wave 'tar -C /sys/fs/pstore -cf - .' > "$out/failed-boot-pstore.tar" 2> "$out/pstore-stderr.txt" || :
      ssh_wave 'dmesg; cat /sys/kernel/debug/ipq-pcs-7a10000.ethernet-pcs/link_state' > "$out/recovered-boot-dmesg.txt" 2>&1 || :
      postpanic_pstore_copied=1
      log "POSTPANIC_EVIDENCE_SAVED boot=$changed_boot"
    fi
    accepted_state=$(ssh_wave 'set -e
      grep -q 0078d29fd0 /etc/openwrt_release
      test "$(fw_printenv -n bootfail)" = 0
      test -e /tmp/wave7-keep-boot
      test "$(iw dev | grep -Ec "link ID[[:space:]]+[01]")" = 2
      for d in /sys/class/remoteproc/remoteproc0 /sys/class/remoteproc/remoteproc1 /sys/class/remoteproc/remoteproc2; do
        test "$(cat "$d/state")" = running
      done
      ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null
      echo POSTPANIC_ACCEPTED' 2>/dev/null || :)
    if [[ $accepted_state == POSTPANIC_ACCEPTED ]]; then
      log "FIFO_A_B_NEGATIVE_POSTPANIC_RECOVERED boot=$changed_boot"
      complete=1
      postpanic_recovered=1
      break
    fi
  fi
  # Until recovery is accepted, retain independent fallback observers.
  sleep 2
done
if (( ! complete )); then
  log 'No accepted post-test result within deadline; recovery observers stay active.'
  exit 4
fi
ssh_wave 'rm -f /tmp/wave7-postboot-trial.arm; if test -s /tmp/wave7-postboot-hard-guard.pid; then kill "$(cat /tmp/wave7-postboot-hard-guard.pid)" 2>/dev/null || :; fi; rm -f /tmp/wave7-postboot-link-monitor.sh /tmp/wave7-postboot-link-monitor.log /tmp/wave7-postboot-link-monitor.ready /tmp/wave7-postboot-link-monitor.done /tmp/wave7-postboot-monitor.pid /tmp/wave7-postboot-hard-guard.sh /tmp/wave7-postboot-hard-guard.pid' >/dev/null 2>&1 || :
(cd "$out"; find . -maxdepth 1 -type f ! -name evidence.sha256 -print0 | sort -z | xargs -0 sha256sum > evidence.sha256; sha256sum -c evidence.sha256 | tail -8)
echo "EVIDENCE=$out"
if (( postpanic_recovered )); then
  echo "FIFO_A_B_NEGATIVE_POSTPANIC_RECOVERED"
  exit 4
fi
