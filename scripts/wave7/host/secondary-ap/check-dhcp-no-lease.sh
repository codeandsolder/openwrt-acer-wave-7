#!/usr/bin/env bash
# Independently verify the DHCP-managed AP boot with upstream DHCP absent.
# Run on Asus after the scoped service and management have returned.
# This checker never writes attestation/approval/boot counters or reboots.
set -euo pipefail
LC_ALL=C
export LC_ALL=C
[[ $# == 1 ]] || { echo 'usage: check-dhcp-no-lease.sh RUN_DIRECTORY' >&2; exit 2; }
base=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8
run=$(realpath -e "$1")
[[ $run == "$base"/guard8-dhcp-managed/runs/no-lease-* ]] || exit 2
fail() { printf 'NO_LEASE_CHECK_FAIL %s\n' "$*" >&2; exit 1; }
value() { sed -n "s/^$2=//p" <<< "$1" | head -1; }
rev=r0+38346-0fbc2cc77b-ap-dhcp-guard8
old=$(head -1 "$run/reboot.log")
[[ $old =~ ^[a-f0-9]{8}-([a-f0-9]{4}-){3}[a-f0-9]{12}$ ]] || fail 'invalid predecessor UUID'
start=$(date -d "$(cat "$run/reboot-request-at.txt")" +%s)
restored=$(date -d "$(systemctl show -p ActiveEnterTimestamp --value wave7-lab-upstream-guard8.service)" +%s)
(( restored-start >= 180 )) || fail 'upstream absence too short'
systemctl is-active --quiet wave7-lab-upstream-guard8.service || fail 'upstream not restored'
# New boot DHCP client should emit requests, and no server may answer it
# before the scheduled restart. Check the complete recorded outage, not
# just the first discover. The preceding boot may send DHCPRELEASE.
frames=$(tcpdump -tt -enn -r "$run/direct.pcap" 'udp and (port 67 or port 68)' 2>/dev/null)
read -r discovers early_replies late_replies < <(awk -v start="$start" -v end="$restored" '
  $1 >= start && $1 < end && /70:5a:6f:5a:bb:14 > / && /0[.]0[.]0[.]0[.]68 > .*67:/ {d++}
  $1 >= start && $1 < end && /[.]67 > .*68:/ {e++}
  $1 >= end && /00:e0:4c:68:00:6d > / && /192[.]168[.]76[.]2[.]67 > (192[.]168[.]76[.]1|255[.]255[.]255[.]255)[.]68:/ {l++}
  END {print d+0,e+0,l+0}' <<< "$frames")
(( discovers > 0 && early_replies == 0 && late_replies > 0 )) || fail "DHCP evidence discovers=$discovers early_replies=$early_replies restored_replies=$late_replies"
# Wireless client must have demonstrated entirely static-address forwarding
# beyond the watchdog deadline while no upstream server was present.
client_start=$(date -d "$(grep -m1 -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}T' "$run/client.log")" +%s)
client_end=$(awk '/^\[[0-9]+[.][0-9]+\] .*icmp_seq=/ {gsub(/^\[/,"",$1); t=int($1)} END{print t+0}' "$run/client.log")
(( client_start >= start+150 && client_end < restored && client_end >= client_start )) || fail 'client probe did not finish within post-watchdog outage'
grep -Fxq 'WAVE7_CLIENT_PASS mode=static' "$run/client.log" || fail 'static MLO forwarding not proven'
# Direct independent management path avoids conflating a 1G switch-trunk
# failure with this role contract. Never supply a fresh boot token.
state=$(ssh -n -T -i /home/jan/.ssh/wave7-root-rsa -o BindInterface=enp4s0f4u2u4 -o BindAddress=192.168.76.2 -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=4 -o "UserKnownHostsFile=$base/known_hosts" root@192.168.76.1 '
  echo "boot=$(cat /proc/sys/kernel/random/boot_id)"
  echo "rev=$(cat /etc/openwrt_version)"
  echo "bootfail=$(fw_printenv -n bootfail)"
  echo "keep=$(test -e /tmp/wave7-keep-boot && echo 1 || echo 0)"
  echo "token=$(test -e /tmp/wave7-ap-management-verified && echo 1 || echo 0)"
  . /rom/lib/wave7/role-firstboot.sh
  echo "approval=$(wave7_secondary_ap_approval_matches /rom/etc/wave7-role-profile "$(cat /rom/etc/openwrt_version)" /overlay/wave7-ap-approved && echo 1 || echo 0)"
  echo "local_ready=$(wave7_secondary_ap_local_ready && echo 1 || echo 0)"
  echo "link_ready=$(wave7_secondary_ap_link_ready && echo 1 || echo 0)"
  echo "bridge_ip=$(ip -4 -o addr show dev br-lan | awk '\''$3=="inet" {print $4}'\'' | head -1)"
  echo "uptime=$(cut -d. -f1 /proc/uptime)"
  dmesg | grep -E "NAND root, radio and LAN accepted|wave7-firstboot:.*accepted" | tail -3 || :')
now=$(date +%s)
printf '%s\n' "$state" | tee "$run/restored-state.txt"
boot=$(value "$state" boot)
uptime=$(value "$state" uptime)
[[ $boot =~ ^[a-f0-9]{8}-([a-f0-9]{4}-){3}[a-f0-9]{12}$ && $boot != "$old" && $uptime =~ ^[0-9]+$ ]] || fail 'new boot identity unavailable'
boot_epoch=$((now-uptime))
# Exclude a hidden watchdog timeout/reboot before management came back.
# A normal boot enters Linux within 80s of the requested reboot; the
# earliest watchdog-triggered reboot would be beyond this bound.
(( uptime >= 150 && boot_epoch >= start-3 && boot_epoch <= start+80 )) || fail "unexpected boot epoch=$boot_epoch start=$start uptime=$uptime"
(( client_start-boot_epoch >= 120 )) || fail 'static client check preceded boot watchdog deadline'
accepted_uptime=$(sed -n 's/^\[[[:space:]]*\([0-9]*\)[.][0-9]*\].*NAND root, radio and LAN accepted.*/\1/p' <<< "$state" | tail -1)
[[ $accepted_uptime =~ ^[0-9]+$ ]] && (( boot_epoch+accepted_uptime < restored )) || fail 'no pre-restoration watchdog acceptance event'
for expected in "rev=$rev" bootfail=0 keep=1 token=0 approval=1 local_ready=1 link_ready=1 bridge_ip=192.168.76.1/24; do
  grep -Fxq "$expected" <<< "$state" || fail "missing state $expected"
done
awk -v now="$now" '$1 > now && tolower($2)=="70:5a:6f:5a:bb:14" && $3=="192.168.76.1"{n++} END{exit n!=1}' "$base/upstream/dnsmasq.leases" || fail 'restored lease not independently verified'
printf 'NO_LEASE_PASS boot=%s boot_epoch=%s uptime=%s accepted_uptime=%s absence_seconds=%s discovers=%s early_replies=%s restored_replies=%s\n' "$boot" "$boot_epoch" "$uptime" "$accepted_uptime" "$((restored-start))" "$discovers" "$early_replies" "$late_replies"
