#!/usr/bin/env bash
# Explicit one-shot QDSS ETR protocol probe from Asus after an independently guarded boot.
set -Eeuo pipefail
umask 077
[[ $# -ge 1 ]] || { echo 'usage: probe-qdss.sh --check|--run [TRIAL_DIR]' >&2; exit 2; }
action=$1
[[ $action == --check || $action == --run ]] || exit 2
root=/home/jan/firmware/wave7/trials/20261117-umacnoc-qdss
revision=r0+38249-qdss-48b2476bd6
image=$root/image-build/wave7-umacnoc-qdss-48b2476bd6-sysupgrade.bin
image_sha=42b2dde4c2253a6168b6a423deff370122287ea69db34b7d5a7d55e82683db78
key=/home/jan/.ssh/wave7-root-rsa
host=root@192.168.76.1
qdss=/sys/kernel/debug/ath12k/ahb-c000000.wifi/umacnoc_qdss
remote() {
  ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o ConnectionAttempts=1 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$host" "$@"
}
abort() { echo "QDSS_PROBE_BLOCKED: $*" >&2; exit 3; }
[[ $(id -un) == jan && -r $key ]] || abort 'wrong identity'
[[ $(sha256sum "$image" | cut -d' ' -f1) == "$image_sha" ]] || abort 'candidate image hash'
XDG_RUNTIME_DIR=/run/user/$(id -u)
export XDG_RUNTIME_DIR
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
state=$(remote 'echo "boot=$(cat /proc/sys/kernel/random/boot_id)";
  echo "rev=$(cat /etc/openwrt_version)";
  echo "kernel=$(uname -r)";
  echo "bootfail=$(fw_printenv -n bootfail 2>/dev/null || :)";
  echo "keep=$(test -e /tmp/wave7-keep-boot && echo 1 || echo 0)";
  echo "ap=$(iw dev ap-mld0 info 2>/dev/null | grep -Ec "link ID[[:space:]]+[01]" || :)";
  echo "q6=$(healthy=1; for p in /sys/class/remoteproc/remoteproc0 /sys/class/remoteproc/remoteproc1 /sys/class/remoteproc/remoteproc2; do test "$(cat "$p/state" 2>/dev/null)" = running || healthy=0; done; if [ "$healthy" = 1 ]; then echo 3; else echo 0; fi)";
  echo "ping=$(ping -I br-lan -c 1 -W 1 192.168.76.2 >/dev/null 2>&1 && echo 1 || echo 0)";
  echo "noc=$(dmesg | grep -c "NOC ERROR DETECTED" || :)";')
value() { printf '%s\n' "$state" | sed -n "s/^$1=//p" | head -1; }
[[ $(value rev) == "$revision" && $(value kernel) == 6.18.60 &&
   $(value bootfail) == 0 && $(value keep) == 1 && $(value ap) == 2 &&
   $(value q6) == 3 && $(value ping) == 1 && $(value noc) == 0 ]] ||
  abort "candidate not healthy: $state"
status=$(remote "cat '$qdss/status'") || abort 'debugfs unavailable'
[[ $status == *"configured=1 active=0"* && $status == *"start_requested=0"* && $status == *"etr_ready=0"* ]] ||
  abort "QDSS already running or unexpected state: $status"
for service in wave7-q6-devcoredump-capture.service wave7-q6-noc-events.service wave7-q6-noc-kmsg.service; do
  systemctl --user is-active --quiet "$service" || abort "missing passive $service"
done
if [[ $action == --check ]]; then
  printf 'QDSS_PROBE_PREFLIGHT_PASS\n%s\n%s\n' "$state" "$status"
  exit 0
fi
[[ $# == 2 ]] || abort 'provide exact guarded run directory'
run_dir=$2
[[ $run_dir == "$root"/runs/qdss-48b2476bd6-* && -d $run_dir ]] ||
  abort 'invalid run directory'
tag=$(basename "$run_dir")
systemctl --user is-active --quiet "wave7-qdss-supervisor-$tag.service" || abort 'native guard inactive'
systemctl --user is-active --quiet "wave7-fallback-watch-$tag.service" || abort 'fallback guard inactive'
systemctl --user is-active --quiet "wave7-qdss-capture-$tag.service" || abort 'raw capture guard inactive'
[[ $(cat "$run_dir/status") == ARMED ]] || abort 'trial already finished'
[[ $(value boot) == $(sed -n 's/^boot=//p' "$run_dir/last-trial-state.txt" | head -1) ]] ||
  abort 'wrong trial boot'
out=$run_dir/evidence/proactive-etr-probe
[[ ! -e $out ]] || abort 'probe already attempted'
mkdir -p "$out"
printf '%s\n' "$state" > "$out/preflight.txt"
printf '%s\n' "$status" > "$out/pre-start-status.txt"
remote 'dmesg' > "$out/pre-start-dmesg.txt"
date -Is > "$out/start-time.txt"
set +e
timeout 25 ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$host" "echo 1 > '$qdss/start'" > "$out/start-output.txt" 2>&1
start_rc=$?
set -e
echo "$start_rc" > "$out/start-rc.txt"
remote "cat '$qdss/status'" > "$out/post-start-status.txt" || :
remote 'dmesg' > "$out/post-start-dmesg.txt" || :
printf 'QDSS_START_RC=%d\n' "$start_rc"
cat "$out/post-start-status.txt"
if (( start_rc == 0 )) && rg -q 'active=1' "$out/post-start-status.txt"; then
  remote 'ping -I br-lan -c 6 -W 1 192.168.76.2' > "$out/traffic.txt" 2>&1 || :
  sleep 3
  set +e
  timeout 25 ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$host" "echo 1 > '$qdss/stop_and_capture'" > "$out/stop-output.txt" 2>&1
  stop_rc=$?
  set -e
  echo "$stop_rc" > "$out/stop-rc.txt"
  printf 'QDSS_STOP_RC=%d\n' "$stop_rc"
  sleep 5
fi
remote "cat '$qdss/status'" > "$out/final-status.txt" || :
remote 'dmesg' > "$out/final-dmesg.txt" || :
find /home/jan/firmware/wave7/captures/qdss-umacnoc -maxdepth 1 -type f ! -name '.*' -printf '%f %s bytes\n' > "$out/raw-captures.txt"
date -Is > "$out/end-time.txt"
printf 'QDSS_PROBE_EVIDENCE=%s\n' "$out"
