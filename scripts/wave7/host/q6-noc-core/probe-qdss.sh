#!/usr/bin/env bash
# Two bounded QDSS ETR captures from one independently guarded boot.
set -Eeuo pipefail
umask 077
[[ $# -ge 1 ]] || { echo 'usage: probe-qdss.sh --check|--run [TRIAL_DIR] [idle|wlan-load]' >&2; exit 2; }
action=$1
[[ $action == --check || $action == --run ]] || exit 2
root=/home/jan/firmware/wave7/trials/20261117-umacnoc-qdss
revision=r0+38249-qdss-eeae36fccc
image=$root/image-build/wave7-umacnoc-qdss-eeae36fccc-sysupgrade.bin
image_sha=bc4806ad80e3e5d83fd21aeefae4a4549f0d1aee970c2d75d818671d1c80e5c5
key=/home/jan/.ssh/wave7-root-rsa
host=root@192.168.76.1
qdss=/sys/kernel/debug/ath12k/ahb-c000000.wifi/umacnoc_qdss
remote() {
  ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o ConnectionAttempts=1 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$host" "$@"
}
abort() { echo "QDSS_PROBE_BLOCKED: $*" >&2; exit 3; }
# Wyse management goes over independent wired SSH, while its wlp2s0
# traffic uses the MT7925 MLO station. No client auto-connect mutation.
wyse() {
  ssh -n -T -o BatchMode=yes -o ConnectTimeout=5 acer \
    "ssh -n -T -o BatchMode=yes -o ConnectTimeout=4 wyse-eth \"$1\""
}
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
[[ $status == *"configured=1 active=0"* && $status == *"start_requested=0"* ]] ||
  abort "QDSS already running or unexpected state: $status"
remote "test -e '$qdss/reload_config'" ||
  abort 'post-ready QDSS reload debugfs control unavailable'
for service in wave7-q6-devcoredump-capture.service wave7-q6-noc-events.service wave7-q6-noc-kmsg.service; do
  systemctl --user is-active --quiet "$service" || abort "missing passive $service"
done
wyse_link=$(wyse 'iw dev wlp2s0 link') || abort 'Wyse MLO station unreachable'
[[ $wyse_link == *"Connected to"* ]] || abort "Wyse WLAN station disconnected: $wyse_link"
if [[ $action == --check ]]; then
  printf 'QDSS_PROBE_PREFLIGHT_PASS\n%s\n%s\n' "$state" "$status"
  exit 0
fi
[[ $# == 3 ]] || abort 'provide exact guarded run directory'
run_dir=$2
[[ $run_dir == "$root"/runs/qdss-eeae36fccc-* && -d $run_dir ]] ||
  abort 'invalid run directory'
tag=$(basename "$run_dir")
systemctl --user is-active --quiet "wave7-qdss-supervisor-$tag.service" || abort 'native guard inactive'
systemctl --user is-active --quiet "wave7-fallback-watch-$tag.service" || abort 'fallback guard inactive'
systemctl --user is-active --quiet "wave7-qdss-capture-$tag.service" || abort 'raw capture guard inactive'
[[ $(cat "$run_dir/status") == ARMED ]] || abort 'trial already finished'
[[ $(value boot) == $(sed -n 's/^boot=//p' "$run_dir/last-trial-state.txt" | head -1) ]] ||
  abort 'wrong trial boot'
phase=$3
[[ $phase == idle || $phase == wlan-load ]] || abort 'invalid phase'
out=$run_dir/evidence/clear-etr/$phase
[[ ! -e $out ]] || abort 'phase already attempted'
mkdir -p "$out"
printf '%s\n' "$state" > "$out/preflight.txt"
printf '%s\n' "$status" > "$out/pre-start-status.txt"
remote 'dmesg' > "$out/pre-start-dmesg.txt"
# The first idle capture provisions the ETR and preserves an unmodified
# baseline. Only the second phase clears the stopped 1MiB reservation,
# confirms zero twice before TRACE_ON and tests for actual new writes.
if [[ $phase == wlan-load ]]; then
  idle=$run_dir/evidence/clear-etr/idle
  [[ -f $idle/end-time.txt && -f $idle/trace-etr.sha256 ]] ||
    abort 'idle baseline not captured on this boot'
  sha256sum -c "$idle/trace-etr.sha256" >/dev/null ||
    abort 'idle baseline digest mismatch'
  [[ $status == *"etr_ready=1"* && $status == *"etr_alloc_size=1048576"* ]] ||
    abort 'ETR must be provisioned before clearing'
  timeout 25 ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$host" "echo 1 > '$qdss/clear_etr'" > "$out/clear-etr-output.txt" 2>&1 ||
    abort 'stopped-only clear_etr rejected'
  for sample in immediately-after-clear after-one-second-stopped; do
    if [[ $sample == after-one-second-stopped ]]; then sleep 1; fi
    timeout 25 ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$host" "cat '$qdss/raw_etr'" > "$out/$sample.bin" 2> "$out/$sample.stderr" ||
      abort "raw_etr read failed during $sample"
    uv run --no-project python -B -c 'import sys; b=open(sys.argv[1],"rb").read(); assert len(b)==1048576 and not any(b), "ETR is not zero"' "$out/$sample.bin" ||
      abort "ETR unexpected data while stopped in $sample"
    sha256sum "$out/$sample.bin" > "$out/$sample.sha256"
  done
  echo QDSS_STOPPED_ETR_CLEAR_VERIFIED
fi
# Independently re-download the *same* pinned QDSS configuration
# after firmware readiness. Watch the missing 0x3f MEM_REQ counter:
# a successful 0x44 ACK alone is not proof the sink became active.
remote "cat '$qdss/status'" > "$out/pre-reload-status.txt"
date -Is > "$out/reload-time.txt"
timeout 25 ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$host" "echo 1 > '$qdss/reload_config'" > "$out/reload-config-output.txt" 2>&1 ||
  abort "$phase post-ready QDSS profile download failed"
sleep 3
remote "cat '$qdss/status'" > "$out/post-reload-status.txt" ||
  abort 'cannot read post-reload QDSS status'
remote 'dmesg' > "$out/post-reload-dmesg.txt" || :
if [[ $phase == wlan-load ]]; then
  # A newly-written buffer while tracing is OFF would be a separate
  # effect of reloading config, not proof that TRACE_ON works.
  timeout 25 ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$host" "cat '$qdss/raw_etr'" > "$out/post-reload-before-trace.bin" 2> "$out/post-reload-stderr.txt" ||
    abort 'post-reload stopped ETR read failed'
  [[ $(stat -c %s "$out/post-reload-before-trace.bin") == 1048576 ]] ||
    abort 'post-reload stopped ETR unexpected size'
  sha256sum "$out/post-reload-before-trace.bin" > "$out/post-reload-before-trace.sha256"
  uv run --no-project python -B -c 'import sys; b=open(sys.argv[1],"rb").read(); print("QDSS_POST_RELOAD_STOPPED_NONZERO",sum(x!=0 for x in b))' "$out/post-reload-before-trace.bin" > "$out/post-reload-count.txt"
fi
post_reload=$(cat "$out/post-reload-status.txt")
[[ $post_reload == *"configured=1 active=0"* &&
   $post_reload == *"start_requested=0"* ]] ||
  abort "unexpected QDSS activation during reload: $post_reload"
date -Is > "$out/start-time.txt"
trace_live=1
restore_idle_on_error() {
  local rc=$?
  if (( rc != 0 && trace_live )); then
    # If the controller exits during TRACE_ON, only disable trace mode;
    # the external Q6, NoC and rollback supervisors remain independent.
    remote "echo 1 > '$qdss/stop'" > "$out/recovery-stop.txt" 2>&1 || :
  fi
}
trap restore_idle_on_error EXIT
set +e
timeout 25 ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$host" "echo 1 > '$qdss/start'" > "$out/start-output.txt" 2>&1
start_rc=$?
set -e
echo "$start_rc" > "$out/start-rc.txt"
remote "cat '$qdss/status'" > "$out/post-start-status.txt" || :
remote 'dmesg' > "$out/post-start-dmesg.txt" || :
printf 'QDSS_START_RC=%d phase=%s\n' "$start_rc" "$phase"
cat "$out/post-start-status.txt"
if (( start_rc != 0 )) || ! rg -q 'active=1' "$out/post-start-status.txt"; then
  abort "$phase QDSS TRACE_ON refused"
fi
if (( start_rc == 0 )); then
  # Maintain the MLO association while comparing a short idle sample
  # with traffic overlapping the end of a separate sample.
  set +e
  if [[ $phase == idle ]]; then
    # Match approximate trace exposure without launching load.
    sleep 2
  else
    # Keep Wi-Fi packets in flight while MODE_OFF executes so a fast
    # circular ETR overwrite cannot lose the relevant traffic.
    wyse 'sudo -n ping -I wlp2s0 -c 120 -i 0.02 -s 1200 -W 2 192.168.76.1' > "$out/wlan-traffic.txt" 2>&1 &
    workload_pid=$!
    sleep 1.2
  fi
  remote 'ping -I br-lan -c 1 -W 1 192.168.76.2' > "$out/wired-control.txt" 2>&1 || :
  set +e
  timeout 25 ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$host" "echo 1 > '$qdss/stop'" > "$out/stop-output.txt" 2>&1
  stop_rc=$?
  set -e
  echo "$stop_rc" > "$out/stop-rc.txt"
  printf 'QDSS_STOP_RC=%d phase=%s\n' "$stop_rc" "$phase"
  if (( stop_rc == 0 )); then
    trace_live=0
  fi
  stopped_status=$(remote "cat '$qdss/status'") || abort 'poststop QDSS status unavailable'
  printf '%s\n' "$stopped_status" > "$out/post-stop-status.txt"
  if (( stop_rc != 0 )) || [[ $stopped_status != *"active=0"* ||
                                $stopped_status != *"start_requested=0"* ]]; then
    abort "$phase MODE_OFF did not clear active/start latch: $stopped_status"
  fi
  if [[ $phase == wlan-load ]]; then
    # Packet loss is evidence, not a reason to discard an otherwise
    # valid ETR snapshot; archive the workload result as observed.
    traffic_rc=0
    wait "$workload_pid" || traffic_rc=$?
    printf '%d\n' "$traffic_rc" > "$out/wlan-traffic-rc.txt"
  fi
  if (( stop_rc == 0 )); then
    # Take one immutable stopped-ETR snapshot. The native driver refuses
    # active tracing and bounds the read to its 1MiB no-map reservation.
    set +e
    timeout 25 ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$host" "cat '$qdss/raw_etr'" > "$out/trace-etr.bin" 2> "$out/raw-etr-stderr.txt"
    raw_rc=$?
    set -e
    printf '%d\n' "$raw_rc" > "$out/raw-etr-rc.txt"
    if (( raw_rc == 0 )) && [[ $(stat -c %s "$out/trace-etr.bin") == 1048576 ]]; then
      sha256sum "$out/trace-etr.bin" > "$out/trace-etr.sha256"
      sha256sum -c "$out/trace-etr.sha256" >/dev/null
      echo "QDSS_RAW_ETR_SNAPSHOT_COMPLETE phase=$phase"
    else
      abort "$phase raw ETR read failed or incomplete"
    fi
  fi
  sleep 5
fi
remote "cat '$qdss/status'" > "$out/final-status.txt" || :
remote 'dmesg' > "$out/final-dmesg.txt" || :
if [[ -s $out/trace-etr.bin ]]; then
  uv run --no-project python -B -c 'import sys,json,hashlib; b=open(sys.argv[1],"rb").read(); assert len(b)==1048576; n=sum(x!=0 for x in b); print(json.dumps({"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"nonzero_bytes":n,"all_zero":n==0}))' "$out/trace-etr.bin" > "$out/trace-etr-analysis.json"
  printf 'QDSS_ETR_FRESHNESS phase=%s result=%s\n' "$phase" "$(cat "$out/trace-etr-analysis.json")"
fi
find /home/jan/firmware/wave7/captures/qdss-umacnoc -maxdepth 1 -type f ! -name '.*' -printf '%f %s bytes\n' > "$out/raw-captures.txt"
date -Is > "$out/end-time.txt"
printf 'QDSS_PROBE_EVIDENCE=%s\n' "$out"
