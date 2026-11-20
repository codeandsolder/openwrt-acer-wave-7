#!/usr/bin/env bash
# One-shot on-boot management attestation, launched by the *independent* Asus
# trial supervisor. It does not commit bootfail or request a flash/reboot.
set -euo pipefail
mode=$1
if [[ $mode != --selftest && ( $mode != --run || $# != 5 ) ]]; then
  echo "usage: $0 --selftest | --run ROUTER EXPECTED_REV BIND_INTERFACE KNOWN_HOSTS" >&2
  exit 2
fi
value() { sed -n "s/^$2=//p" <<< "$1" | head -1; }
valid() {
  local s=$1 expected=$2 rev boot bootfail keep netmode wanted
  rev=$(value "$s" rev)
  boot=$(value "$s" boot)
  bootfail=$(value "$s" bootfail)
  keep=$(value "$s" keep)
  [[ $rev == "$expected" ]] || return 1
  [[ $boot =~ ^[a-f0-9]{8}-([a-f0-9]{4}-){3}[a-f0-9]{12}$ ]] || return 1
  [[ $bootfail =~ ^[1-5]$ && $keep == 0 ]] || return 1
  wanted=dhcp
  [[ $expected == *-ap-static-auth ]] && wanted=static
  netmode=$(value "$s" netproto)
  [[ $(value "$s" role) == secondary-ap ]] || return 1
  [[ $(value "$s" profile_mode) == "$wanted" ]] || return 1
  [[ $netmode == "$wanted" ]] || return 1
  for field in 'kernel=6.18.60' 'root_hash=!' 'rootkey=1' \
    'pass=off' 'rootpass=off' 'rootlogin=on' 'dnsmasq=1' \
    'dhcpv4=disabled' 'dhcpv6=disabled' 'ra=disabled' \
    'lan=1' 'lan1=1' 'q6=3' 'mlo=2' 'ping=1' 'noc=0'; do
    grep -Fxq "$field" <<< "$s" || return 1
  done
  [[ $(value "$s" bridge_ip) =~ ^[0-9]+(\.[0-9]+){3}/[0-9]+$ ]] || return 1
  if [[ $wanted == static ]]; then
    local profile_ip
    profile_ip=$(value "$s" management_ipv4)
    [[ $profile_ip =~ ^[0-9]+(\.[0-9]+){3}/[0-9]+$ ]] || return 1
    [[ $(value "$s" bridge_ip) == "$profile_ip" ]] || return 1
  else
    [[ -z $(value "$s" management_ipv4) ]] || return 1
  fi
}
if [[ $mode == --selftest ]]; then
  rev=r0+38346-0fbc2cc77b-ap-static-auth
  boot=11111111-2222-3333-4444-555555555555
  good=$'rev=r0+38346-0fbc2cc77b-ap-static-auth\nboot=11111111-2222-3333-4444-555555555555\nbootfail=5\nkeep=0\nkernel=6.18.60\nroot_hash=!\nrootkey=1\npass=off\nrootpass=off\nrootlogin=on\ndnsmasq=1\ndhcpv4=disabled\ndhcpv6=disabled\nra=disabled\nrole=secondary-ap\nprofile_mode=static\nmanagement_ipv4=192.168.76.1/24\nnetproto=static\nbridge_ip=192.168.76.1/24\nlan=1\nlan1=1\nq6=3\nmlo=2\nping=1\nnoc=0'
  valid "$good" "$rev"
  for change in 'bootfail=0' 'keep=1' 'root_hash=' 'rootkey=0' \
    'pass=on' 'rootpass=on' 'rootlogin=off' 'dnsmasq=0' \
    'dhcpv4=server' 'dhcpv6=server' 'ra=server' 'lan=0' \
    'lan1=0' 'q6=2' 'mlo=1' 'ping=0' 'noc=1' \
    'bridge_ip=192.168.76.2/24' 'netproto=dhcp'; do
    field=$(cut -d= -f1 <<< "$change")
    if valid "$(sed "s@^$field=.*@$change@" <<< "$good")" "$rev"; then
      echo "ATTESATION_REJECT_TEST_FAIL $change" >&2
      exit 1
    fi
  done
  dynamic_rev=r0+38346-0fbc2cc77b-ap-dhcp-auth
  dynamic=$(sed -e "s@$rev@$dynamic_rev@" \
    -e 's@netproto=static@netproto=dhcp@' \
    -e 's@profile_mode=static@profile_mode=dhcp@' \
    -e 's@management_ipv4=192.168.76.1/24@management_ipv4=@' \
    -e 's@bridge_ip=192.168.76.1/24@bridge_ip=10.22.33.44/24@' <<< "$good")
  valid "$dynamic" "$dynamic_rev"
  for change in 'role=lab' 'profile_mode=dhcp' 'management_ipv4=192.168.76.99/24'; do
    field=$(cut -d= -f1 <<< "$change")
    if valid "$(sed "s@^$field=.*@$change@" <<< "$good")" "$rev"; then
      echo "ATTESTATION_PROFILE_MISMATCH_ACCEPTED $change" >&2
      exit 1
    fi
  done
  for change in 'role=lab' 'profile_mode=static' 'management_ipv4=192.168.76.1/24'; do
    field=$(cut -d= -f1 <<< "$change")
    if valid "$(sed "s@^$field=.*@$change@" <<< "$dynamic")" "$dynamic_rev"; then
      echo "DHCP_ATTESTATION_PROFILE_MISMATCH_ACCEPTED $change" >&2
      exit 1
    fi
  done
  echo SECONDARY_AP_ATTESTATION_SELFTEST_PASS
  exit 0
fi
router=$2
expected=$3
iface=$4
known=$5
[[ $expected =~ ^r0\+[0-9]+-[a-f0-9]{10}-ap-(static|dhcp)-auth$ ]] || {
  echo 'unexpected AP revision' >&2; exit 2
}
[[ $router =~ ^[a-zA-Z0-9.:_-]+$ && $iface =~ ^[a-zA-Z0-9_.:-]+$ ]] || {
  echo 'unsafe router/iface' >&2; exit 2
}
[[ -r "$known" && -r /home/jan/.ssh/wave7-root-rsa ]] || {
  echo 'known host or SSH identity missing' >&2; exit 2
}
remote() {
  ssh -n -T -i /home/jan/.ssh/wave7-root-rsa -o "BindInterface=$iface" \
    -o BatchMode=yes -o IdentitiesOnly=yes -o PreferredAuthentications=publickey \
    -o PasswordAuthentication=no -o ConnectTimeout=4 \
    -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$known" \
    "root@$router" "$@"
}
state=$(remote '
  echo "rev=$(cat /etc/openwrt_version)"
  echo "boot=$(cat /proc/sys/kernel/random/boot_id)"
  echo "bootfail=$(fw_printenv -n bootfail)"
  echo "keep=$(test -e /tmp/wave7-keep-boot && echo 1 || echo 0)"
  echo "kernel=$(uname -r)"
  echo "root_hash=$(awk -F: '\''$1=="root" {print $2}'\'' /etc/shadow)"
  echo "rootkey=$(test -s /etc/dropbear/authorized_keys && echo 1 || echo 0)"
  echo "pass=$(uci -q get dropbear.main.PasswordAuth)"
  echo "rootpass=$(uci -q get dropbear.main.RootPasswordAuth)"
  echo "rootlogin=$(uci -q get dropbear.main.RootLogin)"
  echo "dnsmasq=$(uci -q get dhcp.main.disabled)"
  echo "dhcpv4=$(uci -q get dhcp.lan.dhcpv4)"
  echo "dhcpv6=$(uci -q get dhcp.lan.dhcpv6)"
  echo "ra=$(uci -q get dhcp.lan.ra)"
  echo "role=$(sed -n '\''s/^role=//p'\'' /etc/wave7-role-profile | head -1)"
  echo "profile_mode=$(sed -n '\''s/^mode=//p'\'' /etc/wave7-role-profile | head -1)"
  echo "management_ipv4=$(sed -n '\''s/^management_ipv4=//p'\'' /etc/wave7-role-profile | head -1)"
  echo "netproto=$(uci -q get network.lan.proto)"
  echo "bridge_ip=$(ip -4 -o addr show dev br-lan | sed -n '\''s/.*inet \([^ ]*\).*/\1/p'\'' | head -1)"
  echo "lan=$(cat /sys/class/net/lan/carrier)"
  echo "lan1=$(cat /sys/class/net/lan1/carrier)"
  echo "q6=$(ok=0; for p in /sys/class/remoteproc/remoteproc0 /sys/class/remoteproc/remoteproc1 /sys/class/remoteproc/remoteproc2; do [ "$(cat "$p/state")" = running ] && ok=$((ok+1)); done; echo "$ok")"
  echo "mlo=$(iw dev ap-mld0 info 2>/dev/null | grep -Ec "link ID[[:space:]]+[01]" || :)"
  echo "noc=$(dmesg | grep -Ec NOC.*ERROR || :)"
  echo "ping=$(set -- $SSH_CONNECTION; ping -I br-lan -c 1 -W 1 "$1" >/dev/null 2>&1 && echo 1 || echo 0)"
')
if ! valid "$state" "$expected"; then
  echo 'SECONDARY_AP_MANAGEMENT_ATTESTATION_REFUSED'
  printf '%s\n' "$state" | rg -v '^root_hash='
  exit 3
fi
boot=$(value "$state" boot)
# Writing this token is the only authorized router modification. Neither
# the bootloader counter nor the keep marker is controlled by this script.
ack=$(remote "set -eu; test \"\$(cat /etc/openwrt_version)\" = '$expected'; test \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$boot'; umask 077; printf '%s %s\\n' '$boot' '$expected' > /tmp/wave7-ap-management-verified; test \"\$(cat /tmp/wave7-ap-management-verified)\" = '$boot $expected'; echo MANAGEMENT_ATTESTATION_STORED")
[[ $ack == MANAGEMENT_ATTESTATION_STORED ]] || exit 4
printf 'MANAGEMENT_ATTESTATION_PASS boot=%s revision=%s peer=%s\n' "$boot" "$expected" "$router"
