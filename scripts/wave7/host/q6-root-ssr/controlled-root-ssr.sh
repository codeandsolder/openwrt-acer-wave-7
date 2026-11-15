#!/usr/bin/env bash
set -Eeuo pipefail
mode=$1
[[ $mode == --check || $mode == --run ]] || exit 2
root=/home/jan/firmware/wave7/trials/20261115-q6-root-ssr
mkdir -p "$root"
exec 9>"$root/.trial.lock"
flock -n 9
router() {
 ssh -n -i /home/jan/.ssh/wave7-root-rsa -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@192.168.76.1 "$@"
}
wyse() { ssh -n -o BatchMode=yes acer "ssh -n -o BatchMode=yes wyse-eth '$1'"; }
XDG_RUNTIME_DIR=/run/user/$(id -u); export XDG_RUNTIME_DIR
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
test -z "$(systemctl --user --no-pager --no-legend list-units --state=active 'wave7-openwrt-watch-*' 'wave7-fallback-watch-*')"
test "$(sha256sum /home/jan/scripts/wave7/q6-integration/q6-recovery-guard.sh | cut -d' ' -f1)" = 9a13baf9729818d0179bdfc2a99d7f2ed68be45c2e342efa0749c657e55ae58d
boot=$(router 'set -e
 grep -q 3b1851eda6 /etc/openwrt_release
 test "$(fw_printenv -n bootfail)" = 0
 test -f /tmp/wave7-keep-boot
 test "$(cat /sys/class/remoteproc/remoteproc0/name)" = d100000.remoteproc
 for p in /sys/class/remoteproc/remoteproc*; do test "$(cat "$p/state")" = running; done
 test "$(cat /sys/kernel/debug/remoteproc/remoteproc0/recovery)" = enabled
 test -w /sys/kernel/debug/remoteproc/remoteproc0/crash
 test ! -e /tmp/wave7-q6-ssr-trial.arm
 test "$(iw dev | grep -Ec "link ID[[:space:]]+[01]")" = 2
 test "$(iw dev ap-mld0 station dump | grep -c "^Station ")" -ge 1
 ping -I br-lan -c 2 -W 1 192.168.76.2 >/dev/null
 ping -I br-lan -c 2 -W 1 192.168.76.145 >/dev/null
 cat /proc/sys/kernel/random/boot_id')
[[ $boot =~ ^[0-9a-f-]{36}$ ]]
wyse 'test "$(nmcli -g connection.autoconnect connection show Wave7-MLO-Lab)" = no; ip -4 address show dev eno1 | grep -q 10.1.0.221; ping -I wlp2s0 -c 2 -W 1 192.168.76.1 >/dev/null' >/dev/null
echo "Q6_SSR_PREFLIGHT_PASS boot=$boot mode=$mode wired_wyse=10.1.0.221 sta=192.168.76.145"
[[ $mode == --run ]] || exit 0
tag=q6-root-ssr-$(date +%Y%m%d-%H%M%S)
out="$root/$tag"; mkdir -p "$out"
# Compare against the actual pre-injection crash count. This boot had
# already seen a genuine firmware fatal error before the synthetic test.
crash_before=$(router 'dmesg | grep -c "handling crash #" || :')
[[ $crash_before =~ ^[0-9]+$ ]]
printf 'boot=%s crash_count_before=%s\n' "$boot" "$crash_before" > "$out/preflight.txt"
watch=wave7-openwrt-watch-$tag.service
fallback=wave7-fallback-watch-$tag.service
armed=0
triggered=0
accepted=0
log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$out/orchestrator.log"; }
cleanup() {
 rc=$?
 trap - EXIT
 if (( armed )); then
   for suffix in openwrt-watch.log fallback-watch.log openwrt-capture.txt pstore.txt ramoops-raw.bin bootid-gate.log; do
     f=/tmp/wave7-$tag-$suffix
     [[ ! -s $f ]] || cp -p "$f" "$out/"
   done
   if (( accepted || ! triggered )); then
     router 'rm -f /tmp/wave7-q6-ssr-trial.arm; if test -s /tmp/wave7-q6-ssr-guard.pid; then kill "$(cat /tmp/wave7-q6-ssr-guard.pid)" 2>/dev/null || :; fi; rm -f /tmp/wave7-q6-ssr-guard.pid /tmp/wave7-q6-ssr-guard.sh' 2>/dev/null || :
     systemctl --user stop "$watch" "$fallback" 2>/dev/null || :
   else
     log 'Recovery unconfirmed: leave autonomous guard and external watchers active'
   fi
 fi
 exit "$rc"
}
trap cleanup EXIT
scp -q -O -i /home/jan/.ssh/wave7-root-rsa -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null /home/jan/scripts/wave7/q6-integration/q6-recovery-guard.sh root@192.168.76.1:/tmp/wave7-q6-ssr-guard.sh
router '/bin/ash /tmp/wave7-q6-ssr-guard.sh --check' > "$out/ondevice-guard-preflight.txt"
systemd-run --user --quiet --unit="wave7-openwrt-watch-$tag" -p RuntimeMaxSec=700 -- /home/jan/scripts/wave7/controlled-link/watch-new-boot-id.sh "$tag" "$boot" 3b1851eda6
armed=1
systemd-run --user --quiet --unit="wave7-fallback-watch-$tag" -p RuntimeMaxSec=700 -- /home/jan/scripts/wave7/wave7-fallback-watch.sh "$tag"
systemctl --user is-active --quiet "$watch"
systemctl --user is-active --quiet "$fallback"
router 'set -e
 t=$(cat /proc/sys/kernel/random/uuid)
 printf "%s\n" "$t" > /tmp/wave7-q6-ssr-trial.arm
 start-stop-daemon -S -b -m -p /tmp/wave7-q6-ssr-guard.pid -x /bin/ash -- /tmp/wave7-q6-ssr-guard.sh "$(cat /proc/sys/kernel/random/boot_id)" "$t" 240 192.168.76.145 < /dev/null > /dev/null 2>&1
 sleep 1
 test -s /tmp/wave7-q6-ssr-guard.pid
 kill -0 "$(cat /tmp/wave7-q6-ssr-guard.pid)"
 echo GUARD_ACTIVE' > "$out/armed.txt"
log 'Two Asus observers active; 240s independent router recovery guard armed; Wyse reachable over Ethernet'
router 'echo BOOT=$(cat /proc/sys/kernel/random/boot_id); dmesg | grep -E "handling crash #|root Q6 restarted" | tail -8; iw dev' > "$out/before.txt"
triggered=1
log 'Triggering synthetic root-Q6 watchdog crash using Linux remoteproc0 debugfs crash=1'
router 'printf "1\n" > /sys/kernel/debug/remoteproc/remoteproc0/crash' > "$out/trigger.txt" 2>&1 || :
for ((i=1;i<=60;i++)); do
 state=$(router 'echo BOOT=$(cat /proc/sys/kernel/random/boot_id); for d in /sys/class/remoteproc/remoteproc*; do echo "$(basename "$d")=$(cat "$d/state")"; done; echo LINKS=$(iw dev | grep -Ec "link ID[[:space:]]+[01]" || :); echo STA=$(iw dev ap-mld0 station dump | grep -c "^Station " || :); echo PEER=$(ping -I br-lan -c 1 -W 1 192.168.76.2 >/dev/null 2>&1 && echo yes || echo no); echo CLIENT=$(ping -I br-lan -c 1 -W 1 192.168.76.145 >/dev/null 2>&1 && echo yes || echo no); echo CRASH=$(dmesg | grep -c "handling crash #" || :)' 2>/dev/null || :)
 printf 'sample=%d time=%s\n%s\n' "$i" "$(date -Is)" "$state" >> "$out/observation.log"
 if (( i % 8 == 0 )); then
   log "sample=$i $(printf '%s' "$state" | tr '\n' ' ')"
   if [[ "$state" == *"CLIENT=no"* ]]; then
     log "manual Wyse Wi-Fi profile reassociation over independent Ethernet (autoconnect=no)"
     wyse 'sudo -n nmcli connection up Wave7-MLO-Lab ifname wlp2s0' >> "$out/wyse-reassociate.log" 2>&1 || :
   fi
 fi
 crash_now=$(printf '%s\n' "$state" | sed -n 's/^CRASH=//p')
 if [[ "$crash_now" =~ ^[0-9]+$ ]] && (( crash_now > crash_before )) &&
    [[ "$state" == *"BOOT=$boot"* && "$state" == *"remoteproc0=running"* && "$state" == *"remoteproc1=running"* && "$state" == *"remoteproc2=running"* && "$state" == *"LINKS=2"* && "$state" == *"STA=1"* && "$state" == *"PEER=yes"* && "$state" == *"CLIENT=yes"* ]]; then
   if wyse 'ping -I wlp2s0 -c 2 -W 1 192.168.76.1 >/dev/null' >/dev/null 2>&1; then
     accepted=1
     log "SAME_BOOT_Q6_RECOVERY_ACCEPTED sample=$i"
     break
   fi
 fi
 sleep 2
done
if (( accepted )); then
 router 'dmesg; echo RPROCS; for d in /sys/class/remoteproc/remoteproc*; do echo "$(basename "$d")=$(cat "$d/state")"; done; iw dev; iw dev ap-mld0 station dump' > "$out/after.txt"
 (cd "$out"; find . -maxdepth 1 -type f ! -name evidence.sha256 -print0 | sort -z | xargs -0 sha256sum > evidence.sha256)
 exit 0
fi
log 'SAME_BOOT_SSR_NOT_PROVED; recovery guard and independent fallback still armed'
exit 4
