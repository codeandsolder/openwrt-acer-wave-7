#!/usr/bin/env bash
# Guarded minimal-kernel-FIT native UMACNOC QDSS A/B, executed from Asus.
set -Eeuo pipefail
umask 077
action=${1:---check}
[[ $action == --check || $action == --run ]] || { echo 'usage: flash-qdss.sh --check|--run' >&2; exit 2; }
dir=/home/jan/firmware/wave7/trials/20261117-umacnoc-qdss
image="$dir/image-build/wave7-umacnoc-qdss-3a8d36d639-sysupgrade.bin"
rollback=/home/jan/firmware/wave7/trials/20261116-napi-irq-ab/image-build/wave7-napi-5e3df9b898-sysupgrade.bin
image_sha=df3cc778923af11eaf2e98f5520ef3eeac764c258ce50746ae143705b94d3e4e
rollback_sha=18e285b7dbfac4075a4f675b23c9b97cbf51c50aced6c16a82d1aab439dc0622
baseline_rev=r0+38249-qdss-64ef394b1e
host=root@192.168.76.1
key=/home/jan/.ssh/wave7-root-rsa
ssh_opts=(-n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 -o ConnectionAttempts=1 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
scp_opts=(-q -O -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=5 -o ConnectionAttempts=1 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
remote() { ssh "${ssh_opts[@]}" "$host" "$@"; }
abort() { echo "PREFLIGHT_BLOCKED: $*" >&2; exit 3; }
[[ $(id -un) == jan ]] || abort 'must run as jan'
[[ $(sha256sum "$image" | cut -d' ' -f1) == "$image_sha" ]] || abort 'candidate digest mismatch'
[[ $(sha256sum "$rollback" | cut -d' ' -f1) == "$rollback_sha" ]] || abort 'accepted rollback digest mismatch'
[[ $(tar xOf "$image" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || abort 'bad candidate board'
[[ $(tar xOf "$rollback" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || abort 'bad accepted board'
command -v systemd-run >/dev/null
command -v timeout >/dev/null
[[ -x /home/jan/scripts/wave7/qdss-trial/qdss-watch.sh ]] || abort 'observer not installed'
/home/jan/scripts/wave7/qdss-trial/qdss-watch.sh --selftest
baseline=$(/home/jan/scripts/wave7/qdss-trial/qdss-watch.sh --check)
old_boot=$(printf '%s\n' "$baseline" | sed -n 's/^boot=//p')
[[ $old_boot =~ ^[a-f0-9-]{36}$ ]] || abort 'invalid predecessor boot ID'
[[ $(printf '%s\n' "$baseline" | sed -n 's/^rev=//p') == "$baseline_rev" ]] || abort 'predecessor revision mismatch'
[[ $(printf '%s\n' "$baseline" | sed -n 's/^kernel=//p') == 6.18.60 ]] || abort 'kernel mismatch'
[[ $(printf '%s\n' "$baseline" | sed -n 's/^ping=//p') == 1 ]] || abort 'Redmi peer not responding'
[[ $(printf '%s\n' "$baseline" | sed -n 's/^q6=//p') == 3 ]] || abort 'Q6 not healthy'
[[ $(printf '%s\n' "$baseline" | sed -n 's/^ap=//p') == 2 ]] || abort 'MLO not healthy'
[[ $(printf '%s\n' "$baseline" | sed -n 's/^keep=//p') == 1 ]] || abort 'firstboot not accepted'
[[ $(printf '%s\n' "$baseline" | sed -n 's/^bootfail=//p') == 0 ]] || abort 'bootloader not stable'
[[ -n $(ssh -n -T -o BatchMode=yes -o ConnectTimeout=5 acer 'ssh -n -T -o BatchMode=yes -o ConnectTimeout=4 wyse-eth "cat /proc/sys/kernel/hostname"' 2>/dev/null) ]] || abort 'Wyse out-of-band management inaccessible'
XDG_RUNTIME_DIR=/run/user/$(id -u)
export XDG_RUNTIME_DIR
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
[[ $(systemctl --user is-active wave7-q6-devcoredump-capture.service) == active ]] || abort 'independent core capture service not running'
[[ $(systemctl --user is-active wave7-q6-noc-kmsg.service) == active ]] || abort 'read-only kmsg capture service not running'
[[ $(systemctl --user is-active wave7-q6-noc-events.service) == active ]] || abort 'NoC IRQ/dmesg history capture service not running'
test -z "$(systemctl --user --no-pager --no-legend list-units --state=active 'wave7-openwrt-watch-*' 'wave7-fallback-watch-*' 'wave7-napi-supervisor-*' 'wave7-qdss-supervisor-*')" || abort 'another trial guard is active'
# The independent raw collector owns one global flock. An older,
# completed trial may retain that lock until its capture deadline.
test -z "$(systemctl --user --no-pager --no-legend list-units --state=active 'wave7-qdss-capture-*')" || abort 'another QDSS raw collector is active'
echo "PREFLIGHT_PASS predecessor_boot=$old_boot source_image_sha=$image_sha accepted_restore_sha=$rollback_sha"
[[ $action == --run ]] || exit 0

tag=qdss-3a8d36d639-$(date +%Y%m%d-%H%M%S)
run_dir="$dir/runs/$tag"
mkdir -p "$run_dir"
printf '%s\n' "$baseline" > "$run_dir/preflight.txt"
printf 'candidate_sha=%s\nrollback_sha=%s\n' "$image_sha" "$rollback_sha" >> "$run_dir/preflight.txt"
trial_remote=/tmp/wave7-qdss-3a8d36d639-trial.bin
rollback_remote=/tmp/wave7-qdss-accepted-preflight.bin
for pair in "$image|$trial_remote|$image_sha" "$rollback|$rollback_remote|$rollback_sha"; do
  IFS='|' read -r source dest sha <<< "$pair"
  scp "${scp_opts[@]}" "$source" "$host:$dest"
  check=$(remote "sha256sum '$dest' && /sbin/sysupgrade -T -n '$dest'")
  [[ $check == "$sha  $dest"* ]] || abort "on-router hash or sysupgrade -T failed: $dest"
  printf 'on_router_%s_sha=%s\n' "$(basename "$dest")" "$sha" >> "$run_dir/preflight.txt"
done
echo "STAGED_QDSS_TRIAL_AND_ROLLBACK_IMAGES_PASS tag=$tag"
# The native platform.sh sets bootfail=4 and the existing WCSS hard
# deadline handles preinit radio failure. The external supervisor is
# independent of the flashing SSH process, and can restore if the
# trial boots with an accepted root but fails radio/NoC checks.
unit=wave7-qdss-supervisor-$tag
fallback=wave7-fallback-watch-$tag
collector=wave7-qdss-capture-$tag
flash_started=0
cleanup_preflash_abort() {
  local rc=$?
  if (( rc != 0 && !flash_started )); then
    # A failed collector (e.g. lock contention) must not strand two
    # independently armed fallback guards for a flash never started.
    systemctl --user stop "$unit.service" "$fallback.service" "$collector.service" >/dev/null 2>&1 || :
    printf 'ABORTED_PRE_FLASH_NO_NAND_WRITES\n' > "$run_dir/status"
  fi
}
trap cleanup_preflash_abort EXIT
[[ -x /home/jan/scripts/wave7/qdss-trial/watch-qdss-devcore.sh ]] || abort 'raw collector not installed'
/home/jan/scripts/wave7/qdss-trial/watch-qdss-devcore.sh --check
systemd-run --user --quiet --unit="$collector" --property=RuntimeMaxSec=2100 -- \
  /home/jan/scripts/wave7/qdss-trial/watch-qdss-devcore.sh --run
systemd-run --user --quiet --unit="$unit" --property=RuntimeMaxSec=1800 -- \
  /home/jan/scripts/wave7/qdss-trial/qdss-watch.sh --run "$old_boot" "$run_dir"
systemd-run --user --quiet --unit="$fallback" --property=RuntimeMaxSec=1800 -- \
  /home/jan/scripts/wave7/wave7-fallback-watch.sh "$tag"
sleep 2
systemctl --user is-active --quiet "$unit.service" || abort 'supervisor service not active'
systemctl --user is-active --quiet "$fallback.service" || abort 'vendor fallback observer not active'
systemctl --user is-active --quiet "$collector.service" || abort 'QDSS raw collector not active'
[[ -f $run_dir/status && $(cat "$run_dir/status") == ARMED ]] || abort 'supervisor not armed'
echo "SUPERVISORS_ARMED tag=$tag"
# No fallback to force-flash. If the original boot is not verified and
# systemd supervisors cannot be armed, exit before any NAND writes.
# After this boundary, any SSH disconnect can be the expected reboot:
# leave the independent guards running even if the controller exits.
flash_started=1
set +e
timeout 125 ssh "${ssh_opts[@]}" "$host" "/sbin/sysupgrade -n '$trial_remote'" > "$run_dir/sysupgrade.log" 2>&1
flash_rc=$?
set -e
echo "FLASH_SSH_RC=$flash_rc" | tee -a "$run_dir/sysupgrade.log"
echo "WATCHER_UNIT=$unit.service"
echo "VENDOR_UNIT=$fallback.service"
echo "QDSS_COLLECTOR_UNIT=$collector.service"
echo "TRIAL_DIR=$run_dir"
# Controller can exit while Asus systemd user services keep observing.
# Do not stop the independent guards after SSH disconnect.
