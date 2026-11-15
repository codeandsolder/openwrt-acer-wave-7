#!/bin/ash
# shellcheck shell=dash
# Read-only IPQ5332 port2/PCS1/SERDES state snapshot.
# Never read MMD7.0x802A-0x802F: those packet counters self-clear on read.
set -eu
mode=--snapshot
if [ "$#" -gt 0 ]; then mode=$1; fi
case "$mode" in
  --snapshot|--check) ;;
  *) echo "usage: $0 [--snapshot|--check]" >&2; exit 2 ;;
esac
clk=/sys/kernel/debug/clk/clk_summary
pcs=/sys/kernel/debug/ipq-pcs-7a10000.ethernet-pcs/link_state
test -r "$clk"
test -r "$pcs"
command -v phytool >/dev/null
command -v ethtool >/dev/null
printf 'wave7-path boot=%s uptime=%s check=%s\n' \
 "$(cat /proc/sys/kernel/random/boot_id)" \
 "$(cut -d. -f1 /proc/uptime)" "$mode"
# CCF is driver enable state, not actual physical clock/SerDes synchronization.
awk -v check="$mode" '
 BEGIN {
   want["7a10000.ethernet-pcs::phy_ref_clk"]=50000000
   want["7a10000.ethernet-pcs::rx_clk"]=125000000
   want["7a10000.ethernet-pcs::tx_clk"]=125000000
   want["nss_cc_port2_rx_clk_src"]=125000000
   want["nss_cc_port2_rx_div_clk_src"]=125000000
   want["nss_cc_uniphy_port2_rx_clk"]=125000000
   want["nss_cc_port2_rx_clk"]=125000000
   want["nss_cc_port2_tx_clk_src"]=125000000
   want["nss_cc_port2_tx_div_clk_src"]=125000000
   want["nss_cc_uniphy_port2_tx_clk"]=125000000
   want["nss_cc_port2_tx_clk"]=125000000
   want["nss_cc_port2_mac_clk"]=200000000
 }
 ($1 in want) {
   name=$1
   seen[name]++
   printf "clk %s enable=%s prepare=%s rate=%s hardware=%s expected=%s\n", \
     name,$2,$3,$5,$9,want[name]
   if (check == "--check" && (($2+0)<1 || ($3+0)<1 ||
     ($5+0)!=want[name] || $9!="Y" || seen[name]!=1)) bad++
 }
 END {
   for (name in want) {
     if (!seen[name]) {
       print "clk MISSING name=" name
       if (check=="--check") bad++
     }
   }
   if (check=="--check" && bad) exit 3
 }
' "$clk"
echo 'pcs_start'
cat "$pcs"
echo 'pcs_end'
# 0x006e BITSYNC is PRBS checker state, not normal Ethernet CDR lock.
for reg in 0x0009 0x001e 0x001f 0x006e 0x006f 0x0070 0x007d 0x9072; do
  val=$(phytool read "lan/0x19:1/$reg" 2>&1 || echo READ_ERROR)
  echo "serdes.mmd1.$reg=$val"
  if [ "$mode" = --check ]; then
    [ "$val" != READ_ERROR ] || exit 4
  fi
done
val=$(phytool read lan/0x18:3/0x805a 2>&1 || echo READ_ERROR)
echo "copper.mmd3.0x805a=$val"
if [ "$mode" = --check ]; then
  [ "$val" != READ_ERROR ] || exit 4
fi
echo "copper.mmd7.control.0x8029=$(phytool read lan/0x18:7/0x8029 2>&1 || echo READ_ERROR)"
echo 'mac_start'
ethtool -S lan | grep -E 'rx_frames:|tx_frames:|rx_crc_err:|rx_errors:' || :
echo 'mac_end'
if [ "$mode" = --check ]; then
  echo 'WAVE7_SGMII_PASSIVE_PATH_CHECK_PASS'
fi
