#!/usr/bin/env bash
# Run bounded sustained tests on the two physically bound lab paths.
# No persistent router changes; use known ARM64 iperf runtime in /tmp.
set -Eeuo pipefail
umask 077
base=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8
runtime=/home/jan/firmware/wave7/trials/20261115-deferred-regression/iperf-runtime
[[ $(id -un) == jan && ( $# == 2 || ( $# == 3 && ( $3 == --diagnose || $3 == --localize-udp ) ) ) ]] || { echo 'usage: bench-serial.sh RUN_DIR DIRECT_RATE [--diagnose|--localize-udp]'; exit 2; }
diagnose=0
[[ ${3:-} != --diagnose ]] || diagnose=1
localize_udp=0
[[ ${3:-} != --localize-udp ]] || localize_udp=1
rate=$2
if (( localize_udp )); then [[ $rate == 2500 ]]; fi
case "$rate" in 10|100|1000|2500) ;; *) exit 2 ;; esac
run=$(realpath -e "$1")
case "$run" in
  "$base"/serial-speed-dhcp-guard8/runs/*) revision=r0+38346-f9aa3e1fa3-ap-dhcp-guard8 ;;
  *) exit 2 ;;
esac
[[ $(cat "$run/status") == SOAK_PASS ]]
lock="$base/.lab-control.lock"
[[ -f $lock && ! -L $lock && -O $lock ]]
exec 8<>"$lock"
flock -n 8
XDG_RUNTIME_DIR=/run/user/$(id -u)
export XDG_RUNTIME_DIR
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
test -z "$(systemctl --user --no-pager --no-legend list-units --state=active,activating 'wave7-*watch-*' 'wave7-*supervisor-*' 'wave7-autonomous-observer-*')"
systemctl is-active --quiet wave7-lab-upstream-guard8.service
[[ -f $run/latest-state.txt ]] || exit 2
out=$run/throughput-$rate-$(date +%Y%m%d-%H%M%S)
[[ ! -e $out ]] || { echo 'refusing to overwrite prior benchmark'; exit 2; }
state=$run/latest-state.txt
boot=$(sed -n 's/^boot=//p' "$state")
[[ $boot =~ ^[a-f0-9-]{36}$ ]]
remote_dir=/tmp/wave7-serial-bench-$boot-$rate
direct=enp4s0f4u2u4
switch=enp4s0f4u2u2u4
opts=(-i /home/jan/.ssh/wave7-root-rsa -o BindInterface="$switch" -o BindAddress=192.168.76.250 -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$base/known_hosts" -o ConnectTimeout=4)
remote() { ssh -nT "${opts[@]}" root@192.168.76.1 "$@"; }
ready() {
  remote "test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$boot' &&
    test \"\$(cat /etc/openwrt_version)\" = '$revision' &&
    test \"\$(fw_printenv -n bootfail)\" = 0 &&
    test -e /tmp/wave7-keep-boot &&
    test \"\$(cat /sys/class/net/lan/carrier)\" = 1 &&
    test \"\$(cat /sys/class/net/lan1/carrier)\" = 1 &&
    test \"\$(cat /sys/class/net/lan/speed)\" = '$rate' &&
    test \"\$(sha256sum /lib/modules/6.18.60/pcs-qcom-ipq9574.ko | cut -d' ' -f1)\" = 6e1293e83985caf4eb352e163036d050de5eb2d3f4272ca8a2a71667833658bf &&
    ! dmesg | grep -q 'NOC ERROR DETECTED'"
}
for dev in "$direct" "$switch"; do
  [[ $(cat /sys/class/net/"$dev"/carrier) == 1 ]]
done
[[ $(cat /sys/class/net/"$direct"/speed) == "$rate" && $(cat /sys/class/net/"$switch"/speed) == 1000 ]]
ip route get 192.168.76.1 from 192.168.76.2 | rg -Fq "dev $direct "
ip route get 192.168.76.1 from 192.168.76.250 | rg -Fq "dev $switch "
sha256sum -c "$runtime/sha256sums"
ready
mkdir -m 700 "$out"
made=0
pid=''
captures=()
stack_pids=()
cleanup() {
  local rc=$?
  trap - EXIT
  for cp in "${captures[@]}" "${stack_pids[@]}"; do wait "$cp" || :; done
  if [[ -n $pid ]]; then
    kill "$pid" 2>/dev/null || :
    wait "$pid" 2>/dev/null || :
  fi
  # Server is one-shot and bounded by timeout. Never remove a different
  # boot's files, or a runtime directory not created by this process.
  if (( made )); then
    remote "test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$boot' &&
      rm -f '$remote_dir/iperf3' '$remote_dir/libiperf.so.0' '$remote_dir/libatomic.so.1' &&
      rmdir '$remote_dir'" || rc=1
  fi
  exit "$rc"
}
trap cleanup EXIT
remote "test ! -e '$remote_dir' && mkdir -m 700 '$remote_dir'"
made=1
for f in iperf3 libiperf.so.0 libatomic.so.1; do
  scp -q -O "${opts[@]}" "$runtime/$f" "root@192.168.76.1:$remote_dir/"
  [[ $(sha256sum "$runtime/$f" | cut -d' ' -f1) == "$(remote "sha256sum '$remote_dir/$f'" | cut -d' ' -f1)" ]]
done
remote "LD_LIBRARY_PATH='$remote_dir' '$remote_dir/iperf3' --version" > "$out/version.txt"
snapshot() {
  remote 'cat /proc/sys/kernel/random/boot_id /proc/uptime; ethtool -S switch; ethtool -S lan; ethtool -S lan1; cat /proc/stat'
}
snapshot > "$out/before.txt"
host_snapshot() {
  local dev n
  for dev in "$direct" "$switch"; do
    printf '%s ' "$dev"
    for n in rx_bytes tx_bytes rx_packets tx_packets rx_errors tx_errors rx_dropped tx_dropped; do
      printf '%s=%s ' "$n" "$(cat "/sys/class/net/$dev/statistics/$n")"
    done
    printf '\n'
  done
}
# Read-only UDP stack and exact test-port queue/drop telemetry.
stack_snapshot='echo uptime
cat /proc/uptime
grep "^Udp:" /proc/net/snmp
echo softnet
cat /proc/net/softnet_stat
echo socket_buffers
for n in rmem_default rmem_max wmem_default wmem_max; do
 echo "$n=$(cat /proc/sys/net/core/$n)"
done
echo sockets
awk '"'"'NR>1 && ($2 ~ /:CC03$/ || $3 ~ /:CC03$/) {print}'"'"' /proc/net/udp
'
echo "RUN_DIR=$out"
printf 'case\tsender_mbps\treceiver_mbps\tretransmits\tloss_pct\tasus_cpu_pct\trouter_cpu_pct\n' > "$out/results.tsv"
run_case() {
  local name=$1 addr=$2 dev=$3 duration=$4
  shift 4
  ready
  ip -4 route get 192.168.76.1 from "$addr" | rg -Fq "dev $dev "
  host_snapshot > "$out/$name-host-before.txt"
  snapshot > "$out/$name-router-before.txt"
  remote '! netstat -lnt | grep -q ":52227 "'
  remote "timeout $((duration+25)) env LD_LIBRARY_PATH='$remote_dir' '$remote_dir/iperf3' -s -1 -B 192.168.76.1 -p 52227 -J" > "$out/$name-server.json" 2>"$out/$name-server.err" &
  pid=$!
  for _ in {1..20}; do
    if remote 'netstat -lnt | grep -q ":52227 "'; then break; fi
    sleep .2
  done
  remote 'netstat -lnt | grep -q ":52227 "'
  local rc=0
  local -a trace=()
  if (( localize_udp )); then
    bash -c "$stack_snapshot" > "$out/$name-host-stack-before.txt"
    remote "$stack_snapshot" > "$out/$name-router-stack-before.txt"
    # Read-only snapshots during the test, including per-socket drops.
    # The remote process has a finite loop and uses independent management.
    (for ((sample=0;sample<2*(duration+3);sample++)); do
       echo SAMPLE "$sample"
       bash -c "$stack_snapshot"
       sleep 0.5
     done) > "$out/$name-host-stack-during.txt" &
    stack_pids+=("$!")
    remote "for i in $(seq 1 $((duration+3)) | xargs); do echo SAMPLE \$i; $stack_snapshot sleep 1; done" > "$out/$name-router-stack-during.txt" &
    stack_pids+=("$!")
  fi
  if (( diagnose )); then
    for nic in "$direct" "$switch"; do
      dumpcap -q -i "$nic" -f 'host 192.168.76.1 and tcp port 52227 and (tcp[tcpflags] & (tcp-syn|tcp-fin|tcp-rst) != 0)' -s 80 -a duration:12 -c 100 -w "$out/$name-$nic.pcapng" > "$out/$name-$nic-capture.txt" 2>&1 &
      captures+=("$!")
    done
    sleep 1
    trace=(strace -qq -f -e "trace=bind,connect,setsockopt,getsockopt" -o "$out/$name-sockets.txt")
  fi
  timeout "$((duration+15))" "${trace[@]}" iperf3 -4 -c 192.168.76.1 -B "$addr" --bind-dev "$dev" -p 52227 --connect-timeout 4000 -t "$duration" -O 1 -J "$@" > "$out/$name.json" || rc=$?
  for cp in "${captures[@]}"; do wait "$cp" || :; done
  captures=()
  if (( localize_udp )); then
    bash -c "$stack_snapshot" > "$out/$name-host-stack-after.txt"
    remote "$stack_snapshot" > "$out/$name-router-stack-after.txt"
    for cp in "${stack_pids[@]}"; do wait "$cp"; done
    stack_pids=()
  fi
  if (( rc )); then
    # Server has its own short deadline in diagnosis mode.
    host_snapshot > "$out/$name-host-after.txt"
    snapshot > "$out/$name-router-after.txt" || :
    wait "$pid" || :
    pid=''
    echo "CASE_FAILED name=$name rc=$rc" >&2
    return "$rc"
  fi
  wait "$pid"
  pid=''
  host_snapshot > "$out/$name-host-after.txt"
  snapshot > "$out/$name-router-after.txt"
  ready
  jq -e '.error == null and .end.sum_received.bits_per_second > 0' "$out/$name.json" >/dev/null
  jq -r --arg name "$name" '[$name,.end.sum_sent.bits_per_second/1e6,.end.sum_received.bits_per_second/1e6,(.end.sum_sent.retransmits // 0),(.end.sum_received.lost_percent // 0),.end.cpu_utilization_percent.host_total,.end.cpu_utilization_percent.remote_total]|@tsv' "$out/$name.json" | tee -a "$out/results.tsv"
}
# A moderate UDP load tests loss separately from TCP retransmission.
# Both directions use physical socket binding; no forwarding benchmark
# is implied when the router itself is the endpoint.
udp_rate=$((rate/2))
(( udp_rate <= 150 )) || udp_rate=150
if (( diagnose )); then
  run_case direct-tcp-control 192.168.76.2 "$direct" 3 || :
  run_case switch-tcp-control 192.168.76.250 "$switch" 3 || :
  (cd "$out"; sha256sum ./*.json ./*.txt ./*.err ./*.tsv ./*.pcapng > SHA256SUMS; sha256sum -c SHA256SUMS)
  echo SERIAL_BENCH_DIAGNOSIS_COMPLETE
  exit 0
fi
if (( localize_udp )); then
  run_case direct-udp-tx-default 192.168.76.2 "$direct" 15 -u -b 150M -R
  run_case switch-udp-rx-default 192.168.76.250 "$switch" 15 -u -b 150M
  run_case switch-udp-tx-default 192.168.76.250 "$switch" 15 -u -b 150M -R
  # Socket-local tuning only: no sysctl or persistent system changes.
  if (( $(cat /proc/sys/net/core/rmem_max) >= 1048576 &&
        $(cat /proc/sys/net/core/wmem_max) >= 1048576 )); then
    buffers=$(remote 'cat /proc/sys/net/core/rmem_max /proc/sys/net/core/wmem_max')
    if awk '$1<1048576{bad=1} END{exit bad || NR!=2}' <<< "$buffers"; then
      run_case direct-udp-tx-largebuf 192.168.76.2 "$direct" 15 -u -b 150M -R -w 1M
      run_case switch-udp-rx-largebuf 192.168.76.250 "$switch" 15 -u -b 150M -w 1M
      run_case switch-udp-tx-largebuf 192.168.76.250 "$switch" 15 -u -b 150M -R -w 1M
    else
      printf '%s\n' "$buffers" > "$out/large-buffer-not-supported.txt"
    fi
  fi
  (cd "$out"; sha256sum ./*.json ./*.txt ./*.err ./*.tsv > SHA256SUMS; sha256sum -c SHA256SUMS)
  echo UDP_LOCALIZATION_CAPTURE_COMPLETE
  exit 0
fi
run_case direct-tcp-rx 192.168.76.2 "$direct" 30 -P 4
run_case direct-tcp-tx 192.168.76.2 "$direct" 30 -P 4 -R
run_case direct-udp-rx 192.168.76.2 "$direct" 15 -u -b "${udp_rate}M"
run_case direct-udp-tx 192.168.76.2 "$direct" 15 -u -b "${udp_rate}M" -R
if [[ $rate == 2500 ]]; then
  run_case switch-tcp-rx 192.168.76.250 "$switch" 30 -P 4
  run_case switch-tcp-tx 192.168.76.250 "$switch" 30 -P 4 -R
  run_case switch-udp-rx 192.168.76.250 "$switch" 15 -u -b 150M
  run_case switch-udp-tx 192.168.76.250 "$switch" 15 -u -b 150M -R
fi
snapshot > "$out/after.txt"
ready
# Unchanged raw error counters and increasing CPU ingress are essential:
# throughput on the wrong host NIC must not pass a switch test.
counter() { awk -v key="$2:" '$1==key {print $2}' "$1"; }
for field in dot3StatsFCSErrors etherStatsFragments etherStatsDropEvents; do
  before=$(counter "$out/before.txt" "s00_p06_$field")
  after=$(counter "$out/after.txt" "s00_p06_$field")
  [[ $before =~ ^[0-9]+$ && $after == "$before" ]]
done
before=$(counter "$out/before.txt" s00_p06_ifInOctets)
after=$(counter "$out/after.txt" s00_p06_ifInOctets)
[[ $before =~ ^[0-9]+$ && $after =~ ^[0-9]+$ && $after -gt $before ]]
(cd "$out"; sha256sum *.json *.txt *.err *.tsv > SHA256SUMS; sha256sum -c SHA256SUMS)
echo SERIAL_BENCH_CAPTURE_COMPLETE
