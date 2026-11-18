#!/usr/bin/env bash
# Reproducible dual-port Asus <-> Wave7 throughput test, without installed router packages.
set -Eeuo pipefail
umask 077
trial=/home/jan/firmware/wave7/trials/20261118-asus-dualport
runtime=/home/jan/firmware/wave7/trials/20261115-deferred-regression/iperf-runtime
router_runtime=/tmp/wave7-port0-iperf
out="$trial/throughput"
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
die() { printf 'BENCH_ABORT: %s\n' "$*" >&2; exit 4; }
[[ $(id -un) == jan ]] || die 'run as Asus jan'
[[ -r $key && -r $known && -x $runtime/iperf3 ]] || die 'iperf3 runtime or SSH identity missing'
[[ $(cat /sys/class/net/enp4s0f4u2u4/speed) == 2500 ]] || die '2.5G peer link down'
[[ $(cat /sys/class/net/enp4s0f4u2u2u4/speed) == 1000 ]] || die '1G peer link down'
ip -4 addr show enp4s0f4u2u4 | grep -q '192.168.76.181/24' || die '2.5G peer IP changed'
ip -4 addr show enp4s0f4u2u2u4 | grep -q '192.168.76.190/24' || die '1G peer IP changed'
ready() {
  remote 'test "$(cat /etc/openwrt_version)" = r0+38249-port0-16a784ae;
    test "$(fw_printenv -n bootfail)" = 0;
    test -e /tmp/wave7-keep-boot;
    test "$(cat /sys/class/net/lan1/carrier)" = 1;
    test "$(cat /sys/class/net/lan/carrier)" = 1;
    test "$(cat /sys/class/net/lan1/speed)" = 1000;
    readlink /sys/class/net/lan1/master | grep -q br-lan;
    test "$(dmesg | grep -c "NOC ERROR DETECTED")" = 0'
}
ready || die 'Wave7 candidate not ready'
mkdir -p "$out"
exec 9>"$out/.bench.lock"
flock -n 9 || die 'another benchmark running'
remote "mkdir -p '$router_runtime'"
for f in iperf3 libiperf.so.0 libatomic.so.1; do
  upload "$runtime/$f" "$router_runtime/"
  source_sha=$(sha256sum "$runtime/$f" | cut -d' ' -f1)
  remote_sha=$(remote "sha256sum '$router_runtime/$f'" | cut -d' ' -f1)
  [[ $source_sha == "$remote_sha" ]] || die "transferred $f corrupted"
done
remote "LD_LIBRARY_PATH=$router_runtime $router_runtime/iperf3 --version" > "$out/router-iperf-version.txt"
iperf3 --version > "$out/asus-iperf-version.txt"
{ date -Is; ip -4 addr; ip route; ip -s link show enp4s0f4u2u4; ip -s link show enp4s0f4u2u2u4; } > "$out/asus-before.txt"
remote 'cat /proc/stat; cat /proc/softirqs; ethtool -S lan1; ethtool -S lan; cat /proc/uptime' > "$out/router-before.txt"
printf 'case\tpeer_mbps\tsender_mbps\treceiver_mbps\ttcp_retransmits\trouter_cpu_pct\tasus_cpu_pct\n' > "$out/results.tsv"
serverpid="$out/asus-iperf.pid"
cleanup() {
  if [[ -s $serverpid ]]; then
    kill "$(cat "$serverpid")" 2>/dev/null || :
  fi
  remote "rm -f $router_runtime/iperf3 $router_runtime/libiperf.so.0 $router_runtime/libatomic.so.1" >/dev/null 2>&1 || :
}
trap cleanup EXIT
if [[ ! -s $serverpid ]] || ! kill -0 "$(cat "$serverpid")" 2>/dev/null; then
  iperf3 -s -D -I "$serverpid" -p 52225
fi
ready_server=0
for ((attempt=0;attempt<40;attempt++)); do
  if [[ -s $serverpid ]] && kill -0 "$(cat "$serverpid")" 2>/dev/null &&
     ss -ltn 'sport = :52225' | grep -q LISTEN; then
    ready_server=1; break
  fi
  sleep 0.1
done
[[ $ready_server == 1 ]] || die 'iperf server did not start'
run_one() {
  local name=$1 addr=$2 rate=$3
  shift 3
  echo "$(date -Is) START $name" >> "$out/progress.log"
  ready || die "router unhealthy before $name"
  remote "LD_LIBRARY_PATH=$router_runtime $router_runtime/iperf3 -4 -c $addr -B 192.168.76.1 -p 52225 -J -t 12 -O 2 $*" > "$out/$name.json"
  jq -e '(.error == null) and (.end != null)' "$out/$name.json" >/dev/null || die "bad iperf3 result for $name"
  jq -r --arg name "$name" --arg rate "$rate" '[
    $name, $rate, ((.end.sum_sent.bits_per_second // 0)/1000000),
    ((.end.sum_received.bits_per_second // 0)/1000000),
    (.end.sum_sent.retransmits // 0),
    (.end.cpu_utilization_percent.host_total // 0),
    (.end.cpu_utilization_percent.remote_total // 0)] | @tsv' "$out/$name.json" | tee -a "$out/results.tsv"
  echo "$(date -Is) DONE $name" >> "$out/progress.log"
}
run_one lan1-tcp-forward-1 192.168.76.190 1000 -P 1
run_one lan1-tcp-reverse-1 192.168.76.190 1000 -P 1 -R
run_one lan1-tcp-forward-4 192.168.76.190 1000 -P 4
run_one lan1-tcp-reverse-4 192.168.76.190 1000 -P 4 -R
run_one lan-tcp-forward-1 192.168.76.181 2500 -P 1
run_one lan-tcp-reverse-1 192.168.76.181 2500 -P 1 -R
run_one lan-tcp-forward-4 192.168.76.181 2500 -P 4
run_one lan-tcp-reverse-4 192.168.76.181 2500 -P 4 -R
{ date -Is; ip -s link show enp4s0f4u2u4; ip -s link show enp4s0f4u2u2u4; } > "$out/asus-after.txt"
remote 'cat /proc/stat; cat /proc/softirqs; ethtool -S lan1; ethtool -S lan; cat /proc/uptime' > "$out/router-after.txt"
ready || die 'router unhealthy after benchmarks'
(cd "$out" && sha256sum *.json *.txt *.tsv > evidence.sha256 && sha256sum -c evidence.sha256 > evidence-verified.txt)
echo "THROUGHPUT_COMPLETE $(date -Is)" >> "$out/progress.log"
