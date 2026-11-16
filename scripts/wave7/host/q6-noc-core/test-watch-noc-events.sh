#!/usr/bin/env bash
# Small controlled mock SSH fixture, no live hardware changes.
set -Eeuo pipefail
script=$(cd -- "$(dirname -- "$0")" && pwd)/watch-noc-events.sh
tmp=$(mktemp -d "${TMPDIR:-/tmp}/wave7-noc-event-test.XXXXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/captures"
cat > "$tmp/bin/ssh" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
last=''
for a in "$@"; do last=$a; done
case "$last" in
  *'dmesg | grep -F "NOC ERROR DETECTED"'*)
    echo BOOT_ID=12345678-aaaa-bbbb-cccc-0123456789ab
    echo REV=r0+38249-wbe14-01734-test
    echo '[ 406.00000] NOC ERROR DETECTED'
    echo ====WAVE7_IRQS====
    echo ' 55: 5 3 0 0 GIC-0 455 Edge ce1'
    echo ' 70: 1100 200 0 0 GIC-0 516 Edge rxdma2host-monitor-destination-mac1'
    echo ' 85: 40 2 0 0 GICv2m-pMSI-soc@0:wifi 14 Edge pci2_wlan_dp_8'
    echo ' 12: 5000 5000 5000 5000 GIC-0 20 Level arch_timer'
    echo ====WAVE7_IRQS_END====
    echo ====WAVE7_CLOCKS====
    echo " gcc_pcie3x2_axi_m_clk 0 0 0 266666666 0 0 50000 Y deviceless no_connection_id"
    echo " gcc_snoc_pcie3_2lane_m_clk 0 0 0 266666666 0 0 50000 Y 1800000.clock-controller icc"
    echo " gcc_pcie3x2_phy_ahb_clk 0 0 0 99999999 0 0 50000 N deviceless no_connection_id"
    echo " gcc_pcie3x1_0_axi_m_clk 0 0 0 240000000 0 0 50000 Y deviceless no_connection_id"
    echo ====WAVE7_CLOCKS_END====
    echo "WAVE7_UPTIME=${WAVE7_TEST_UPTIME:-406.75}"
    echo WAVE7_STATION_COUNT=1
    ;;
  *'====ROUTER_CONTEXT===='*)
    echo ====ROUTER_CONTEXT====
    if [[ ${WAVE7_TEST_STALE_BOOT:-0} == 1 ]]; then
      echo BOOT_ID=12345678-ffff-bbbb-cccc-0123456789ab
    else
      echo BOOT_ID=12345678-aaaa-bbbb-cccc-0123456789ab
    fi
    echo REV=r0+38249-wbe14-01734-test
    echo ====KERNEL_DMESG====
    echo '[ 406.00000] NOC ERROR DETECTED'
    echo 'ERRLOG0=0x12105 ERRLOG1=0x841d'
    ;;
  *)
    exit 3
    ;;
esac
MOCK
chmod 750 "$tmp/bin/ssh"
export PATH="$tmp/bin:$PATH"
export WAVE7_Q6_SSH_KEY="$tmp/bin/ssh"
export WAVE7_NOC_EVENT_DIR="$tmp/captures"
export WAVE7_NOC_POLL_SECONDS=2
"$script" --check | rg 'NOC_MONITOR_CHECK_PASS'
export WAVE7_TEST_STALE_BOOT=1
timeout 3 "$script" --run > "$tmp/stale.log" 2>&1 || test "$?" -eq 124
rg 'NOC_CAPTURE_INCOMPLETE' "$tmp/stale.log"
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.kernel.txt' | wc -l) == 0 ]]
unset WAVE7_TEST_STALE_BOOT
timeout 4 "$script" --run > "$tmp/first.log" 2>&1 || test "$?" -eq 124
rg 'NOC_EVENT_ARCHIVED' "$tmp/first.log"
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.kernel.txt' | wc -l) == 1 ]]
irq="$tmp/captures/irq-12345678-aaaa-bbbb-cccc-0123456789ab.tsv"
test -s "$irq"
rg -Fq $'406.75\t1\t70\t1300\trxdma2host-monitor-destination-mac1' "$irq"
rg -Fq $'406.75\t1\t55\t8\tce1' "$irq"
rg -Fq $'406.75\t1\t85\t42\tpci2_wlan_dp_8' "$irq"
! rg -Fq 'arch_timer' "$irq"
clock_file="$tmp/captures/clocks-12345678-aaaa-bbbb-cccc-0123456789ab.tsv"
test -s "$clock_file"
rg -Fq $'406.75\tgcc_pcie3x2_axi_m_clk\t0\t0\t266666666\tY' "$clock_file"
rg -Fq $'406.75\tgcc_pcie3x2_phy_ahb_clk\t0\t0\t99999999\tN' "$clock_file"
rg -Fq $'406.75\tgcc_snoc_pcie3_2lane_m_clk\t0\t0\t266666666\tY' "$clock_file"
! rg -Fq 'gcc_pcie3x1_0_axi_m_clk' "$clock_file"
find "$tmp/captures" -maxdepth 1 -name '*.kernel.txt' -exec rg -Fq 'ERRLOG1=0x841d' {} \;
timeout 3 "$script" --run > "$tmp/restart.log" 2>&1 || test "$?" -eq 124
! rg -q 'NOC_EVENT_ARCHIVED' "$tmp/restart.log"
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.kernel.txt' | wc -l) == 1 ]]
[[ $(rg -c -F $'406.75\t1\t70\t1300\trxdma2host-monitor-destination-mac1' "$irq") -ge 2 ]]
[[ $(rg -c -F $'captured_utc\trouter_uptime_s' "$irq") == 1 ]]
test -z "$(find "$tmp/captures" -maxdepth 1 -name '.noc.partial.*' -print -quit)"
# Verify that early uptime uses the same read-only SSH probe:
# two or more samples within five seconds; one after the cutoff.
export WAVE7_NOC_POLL_SECONDS=8
export WAVE7_NOC_EARLY_POLL_SECONDS=2
export WAVE7_TEST_UPTIME=90.0
mkdir -p "$tmp/early"
WAVE7_NOC_EVENT_DIR="$tmp/early" timeout 5 "$script" --run > "$tmp/early.log" 2>&1 || test "$?" -eq 124
early_file="$tmp/early/irq-12345678-aaaa-bbbb-cccc-0123456789ab.tsv"
[[ $(rg -c -F $'90.0\t1\t70\t1300\trxdma2host-monitor-destination-mac1' "$early_file") -ge 2 ]]
export WAVE7_TEST_UPTIME=406.75
mkdir -p "$tmp/late"
WAVE7_NOC_EVENT_DIR="$tmp/late" timeout 5 "$script" --run > "$tmp/late.log" 2>&1 || test "$?" -eq 124
late_file="$tmp/late/irq-12345678-aaaa-bbbb-cccc-0123456789ab.tsv"
[[ $(rg -c -F $'406.75\t1\t70\t1300\trxdma2host-monitor-destination-mac1' "$late_file") == 1 ]]
echo NOC_EVENT_ADAPTIVE_POLL_TEST_PASS
echo NOC_EVENT_CAPTURE_RESTART_DEDUP_PASS
