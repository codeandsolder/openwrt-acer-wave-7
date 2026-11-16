#!/usr/bin/env bash
# Run on Asus, after one passing pilot; 99 additional guarded reboot cycles.
# Restore Wyse's original autoconnect preference only on complete success.
set -Eeuo pipefail
umask 077
base=/home/jan/firmware/wave7/trials/20261116-cycle-stress
source_acer=/home/jan/firmware/wave7/trials/20261116-cycle-stress/wyse-autoconnect-original.txt
status=$base/99-reboot-controller.status
ssh_acer() { ssh -n -T -o BatchMode=yes -o ConnectTimeout=5 acer "$@"; }
original=$(ssh_acer "cat '$source_acer'")
[[ $original == no ]] || { echo "UNKNOWN_WYSE_ORIGINAL_PREF=$original"; exit 3; }
test -s "$base/active-reboot-run-path"
# A new result directory is created by the real reboot controller.
rc=0
/home/jan/scripts/wave7/stability-cycle/router-reboots.sh --run 99 || rc=$?
if ((rc)); then
  printf 'REBOOT_LOOP_FAILED exit=%d; Wyse autoconnect remains enabled for recovery\n' "$rc" | tee "$status"
  exit "$rc"
fi
path=$(cat "$base/active-reboot-run-path")
[[ $path == "$base"/reboots-* && -s $path/reboots.tsv ]]
[[ $(cat "$path/status") == 'PASS 99/99' ]]
[[ $(awk -F '\t' 'NR>1 {n++} END {print n+0}' "$path/reboots.tsv") == 99 ]]
# The original configuration had auto=false; do not disconnect the current
# Wi-Fi association while restoring the saved preference.
setting=$(ssh_acer 'ssh -n -T -o BatchMode=yes -o ConnectTimeout=5 wyse-eth "sudo -n nmcli connection modify Wave7-MLO-Lab connection.autoconnect no && nmcli -g connection.autoconnect connection show Wave7-MLO-Lab"')
[[ $setting == no ]] || { printf 'WYSE_PREF_RESTORE_FAILED value=%s\n' "$setting" | tee "$status"; exit 4; }
printf 'PASS 99/99; WYSE_AUTOCONNECT_RESTORED=no; PILOT=1; TOTAL_GOOD_REBOOTS=100\n' | tee "$status"
