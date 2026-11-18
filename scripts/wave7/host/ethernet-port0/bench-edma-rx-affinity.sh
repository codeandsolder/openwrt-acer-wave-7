#!/usr/bin/env bash
# Bounded A/B of Wave 7 EDMA RX IRQ affinity against the 2.5Gbps receive path.
# Source is Asus. All target IRQ affinity changes are transient and restored.
set -Eeuo pipefail
umask 077
trial=/home/jan/firmware/wave7/trials/20261118-asus-dualport
out="$trial/edma-rx-affinity/runs/$(date +%Y%m%d-%H%M%S)"
runtime=/home/jan/firmware/wave7/trials/20261115-deferred-regression/iperf-runtime
router_runtime=/tmp/wave7-port0-iperf
key=/home/jan/.ssh/wave7-root-rsa
known="$trial/known_hosts"
host=root@192.168.76.1
remote() {
  ssh -n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 \
    -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" "$host" "$@"
}
upload() {
  scp -q -O -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=5 \
    -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" "$1" "$host:$2"
}
die() { echo "ABORT: $*" >&2; exit 3; }
[[ $(id -un) == jan && -r $key && -r $known ]] || die "missing Asus user or Wave7 identity"
[[ $(cat /sys/class/net/enp4s0f4u2u4/speed) == 2500 ]] || die "2.5G physical link down"
ip -4 addr show enp4s0f4u2u4 | grep -q '192.168.76.181/24' || die "Asus DHCP address changed"
health() {
  remote 'test "$(cat /etc/openwrt_version)" = r0+38249-port0-16a784ae &&
    test "$(fw_printenv -n bootfail)" = 0 &&
    test -e /tmp/wave7-keep-boot &&
    test "$(cat /sys/class/net/lan/carrier)" = 1 &&
    test "$(cat /sys/class/net/lan1/carrier)" = 1 &&
    test "$(dmesg | grep -c "NOC ERROR DETECTED")" = 0'
}
health || die "router health gate failed"
mkdir -p "$out"
exec 9>"$out/.affinity.lock"
flock -n 9 || die "affinity trial already running"
[[ ! -e $out/results.tsv ]] || die "trial results already exist; preserve old evidence"
remote 'cat /proc/interrupts' > "$out/irqs-initial.txt"
printf 'irq\tname\tallowed_before\teffective_before\n' > "$out/affinities-before.tsv"
for name in rxdesc_12 rxdesc_13 rxdesc_14 rxdesc_15; do
  irq=$(awk -v name="$name" '$NF==name {sub(/:/,"",$1);print $1}' "$out/irqs-initial.txt")
  [[ $irq =~ ^[0-9]+$ ]] || die "missing EDMA IRQ $name"
  mask=$(remote "cat /proc/irq/$irq/smp_affinity_list")
  effective=$(remote "cat /proc/irq/$irq/effective_affinity_list")
  [[ $mask == 0-3 && $effective == 0 ]] || die "unexpected affinity for $name IRQ $irq: $mask / $effective"
  printf '%s\t%s\t%s\t%s\n' "$irq" "$name" "$mask" "$effective" >> "$out/affinities-before.tsv"
done
server_pid="$out/asus-server.pid"
modified=0
cleanup() {
  local rc=$? irq name allowed effective
  trap - EXIT
  if (( modified )); then
    while IFS=$'\t' read -r irq name allowed effective; do
      [[ $irq =~ ^[0-9]+$ ]] || continue
      # Restore original target first, then its original allowed mask.
      remote "printf '%s\n' '$effective' > /proc/irq/$irq/smp_affinity_list" || :
      remote "printf '%s\n' '$allowed' > /proc/irq/$irq/smp_affinity_list" || :
    done < "$out/affinities-before.tsv"
    remote 'cat /proc/interrupts; cat /proc/softirqs' > "$out/irq-restore.txt" || :
    while IFS=$'\t' read -r irq name allowed effective; do
      [[ $irq =~ ^[0-9]+$ ]] || continue
      new_allowed=$(remote "cat /proc/irq/$irq/smp_affinity_list" || :)
      new_effective=$(remote "cat /proc/irq/$irq/effective_affinity_list" || :)
      echo "$irq $name original=$allowed/$effective restored=$new_allowed/$new_effective" >> "$out/restore-check.txt"
      if [[ $new_allowed != "$allowed" || $new_effective != "$effective" ]]; then
        echo "RESTORE_MISMATCH IRQ=$irq" >> "$out/restore-check.txt"
      fi
    done < "$out/affinities-before.tsv"
  fi
  if [[ -s $server_pid ]]; then
    kill "$(cat "$server_pid")" 2>/dev/null || :
  fi
  remote "rm -f $router_runtime/iperf3 $router_runtime/libiperf.so.0 $router_runtime/libatomic.so.1" >/dev/null 2>&1 || :
  exit "$rc"
}
trap cleanup EXIT
remote "mkdir -p '$router_runtime'"
for f in iperf3 libiperf.so.0 libatomic.so.1; do
  upload "$runtime/$f" "$router_runtime/"
  localsha=$(sha256sum "$runtime/$f" | cut -d' ' -f1)
  remotesha=$(remote "sha256sum '$router_runtime/$f'" | cut -d' ' -f1)
  [[ $localsha == "$remotesha" ]] || die "transfer failed $f"
done
iperf3 -s -D -I "$server_pid" -B 192.168.76.181 --bind-dev enp4s0f4u2u4 -p 52226
server_ready=0
for ((i=0;i<40;i++)); do
  if [[ -s $server_pid ]] && kill -0 "$(cat "$server_pid")" 2>/dev/null &&
     ss -ltn 'sport = :52226' | grep -q LISTEN; then server_ready=1; break; fi
  sleep 0.1
done
[[ $server_ready == 1 ]] || die "bound iperf3 server did not start"
printf 'case\tmbps\ttcp_retransmits\trouter_cpu_percent\n' > "$out/results.tsv"
snapshot() {
  local stage=$1
  remote 'cat /proc/stat; cat /proc/softirqs; cat /proc/interrupts; ethtool -S lan; cat /proc/uptime' > "$out/router-$stage.txt"
}
run_case() {
  local name=$1 streams=$2
  health || die "router health lost before $name"
  echo "START $name $(date -Is)" >> "$out/progress.log"
  remote "LD_LIBRARY_PATH=$router_runtime $router_runtime/iperf3 -4 -c 192.168.76.181 -B 192.168.76.1 -p 52226 --connect-timeout 5000 -J -t 12 -O 2 -P $streams -R" > "$out/$name.json"
  jq -e '(.error == null) and (.end != null)' "$out/$name.json" >/dev/null || die "invalid result $name"
  jq -r --arg case "$name" '[$case, ((.end.sum_received.bits_per_second // 0)/1000000),(.end.sum_sent.retransmits // 0),(.end.cpu_utilization_percent.host_total // 0)] | @tsv' "$out/$name.json" | tee -a "$out/results.tsv"
  echo "DONE $name $(date -Is)" >> "$out/progress.log"
}
snapshot baseline-before
run_case baseline-one 1
run_case baseline-four 4
snapshot baseline-after
# Leave CPU0's already-correct routing untouched. A freshly saturated
# router may delay SSH, so give CPU0 time to drain before an IRQ migration.
sleep 2
modified=1
while IFS=$'\t' read -r irq name allowed effective; do
  [[ $irq =~ ^[0-9]+$ ]] || continue
  case $name in
    rxdesc_12) cpu=0 ;;
    rxdesc_13) cpu=1 ;;
    rxdesc_14) cpu=2 ;;
    rxdesc_15) cpu=3 ;;
    *) die "unexpected IRQ $name" ;;
  esac
  if [[ $cpu != 0 ]]; then
    applied=0
    for retry in 1 2 3; do
      if failure=$(remote "printf '%s\n' '$cpu' > /proc/irq/$irq/smp_affinity_list" 2>&1); then
        applied=1
        break
      fi
      echo "AFFINITY_RETRY irq=$irq attempt=$retry error=$failure" >> "$out/progress.log"
      sleep 2
    done
    [[ $applied == 1 ]] || die "IRQ $irq affinity change failed: $failure"
  fi
  now=$(remote "cat /proc/irq/$irq/effective_affinity_list")
  [[ $now == "$cpu" ]] || die "IRQ $irq didn't move to CPU$cpu, effective=$now"
  echo "$irq $name new_effective=$now" >> "$out/affinities-spread.txt"
done < "$out/affinities-before.tsv"
snapshot spread-before
run_case spread-one 1
run_case spread-four 4
snapshot spread-after
health || die "post-run router health failed"
echo "EDMA_RX_A_B_COMPLETED $(date -Is)" >> "$out/progress.log"
# cleanup trap restores all affinities and removes benchmark binaries
