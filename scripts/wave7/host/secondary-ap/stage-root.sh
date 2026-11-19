#!/bin/sh
# Construct a dedicated Wave7 secondary-AP role within an extracted native
# SquashFS, without interacting with the running router.
set -eu
[ "$#" -ge 2 ] && [ "$#" -le 3 ] || {
  echo "Usage: stage-root.sh EXTRACTED_ROOT dhcp|static [IPv4/CIDR]" >&2
  exit 2
}
root=$(realpath -e "$1")
mode=$2
cidr=""
if [ "$#" -eq 3 ]; then cidr=$3; fi
case "$mode" in
  dhcp)
    [ -z "$cidr" ] || { echo 'DHCP mode forbids fixed address' >&2; exit 2; }
    ;;
  static)
    printf '%s\n' "$cidr" | awk -F '[./]' '
      NF!=5 {exit 1}
      {
        for(i=1;i<=4;i++) {
          if($i !~ /^[0-9]+$/ || ($i ~ /^0[0-9]/) || $i+0>255) exit 1
        }
        if($1==0 || $1==127 || $1>=224) exit 1
        if($5 !~ /^[0-9]+$/ || ($5 ~ /^0[0-9]/) || $5+0<1 || $5+0>32) exit 1
        if($5+0<=30) {
          network=($1*16777216)+($2*65536)+($3*256)+($4+0)
          block=2^(32-$5)
          host=network%block
          if(host==0 || host==block-1) exit 1
        }
      }' || { echo 'invalid IPv4/CIDR' >&2; exit 2; }
    ;;
  *) echo "unknown management mode $mode" >&2; exit 2 ;;
esac
[ -d "$root/etc/config" ] && [ -f "$root/etc/openwrt_version" ] || {
  echo 'not an extracted OpenWrt root' >&2; exit 2
}
for f in "$root/etc/config/network" "$root/etc/config/dhcp" \
         "$root/etc/config/dropbear" "$root/etc/shadow" \
         "$root/etc/dropbear/authorized_keys" "$root/etc/openwrt_release" \
         "$root/etc/banner" "$root/usr/lib/os-release" \
         "$root/etc/config/wireless"; do
  [ -f "$f" ] && [ ! -L "$f" ] || {
    echo "missing or symlinked expected file: $f" >&2; exit 2
  }
done
[ ! -e "$root/etc/wave7-role-profile" ] || {
  echo 'already profiled image refused' >&2; exit 2
}
[ -s "$root/etc/dropbear/authorized_keys" ] || {
  echo 'cannot disable passwords without an authorized SSH key' >&2; exit 2
}
rg -q '^ssh-(rsa|ed25519) ' "$root/etc/dropbear/authorized_keys" || {
  echo 'no recognized public key in authorized_keys' >&2; exit 2
}
rg -q '^root::' "$root/etc/shadow" || {
  echo 'unexpected baseline root password state' >&2; exit 2
}
rg -q "option device 'br-lan'" "$root/etc/config/network" || {
  echo 'unexpected network base configuration' >&2; exit 2
}
rg -q "option mlo '1'" "$root/etc/config/wireless" || {
  echo 'missing original two-link MLO configuration' >&2; exit 2
}
rg -q "option enable '1'" "$root/etc/config/dropbear" || {
  echo 'unexpected Dropbear baseline' >&2; exit 2
}
oldrev=$(cat "$root/etc/openwrt_version")
case "$oldrev" in
  r0+*-ap-*) echo 'refuse to derive from another AP profile' >&2; exit 2 ;;
  r0+*) ;;
  *) echo 'unexpected OpenWrt source revision' >&2; exit 2 ;;
esac
newrev="$oldrev-ap-$mode"
net="$root/etc/config/network"
cat > "$net.new" <<'NET'
config interface 'loopback'
  option device 'lo'
  option proto 'static'
  list ipaddr '127.0.0.1/8'

config device
  option name 'br-lan'
  option type 'bridge'
  list ports 'lan'
  list ports 'lan1'
  list ports 'lan2'
  list ports 'game'

config interface 'lan'
  option device 'br-lan'
NET
if [ "$mode" = dhcp ]; then
  cat >> "$net.new" <<'NET'
  option proto 'dhcp'
  option peerdns '1'
NET
else
  printf "  option proto 'static'\n  list ipaddr '%s'\n" "$cidr" >> "$net.new"
fi
# No AP-sourced DHCPv4/DHCPv6/RA/ND proxy/DNS.
cat > "$root/etc/config/dhcp.new" <<'DHCP'
config dnsmasq 'main'
  option disabled '1'

config dhcp 'lan'
  option interface 'lan'
  option ignore '1'
  option dhcpv4 'disabled'
  option dhcpv6 'disabled'
  option ra 'disabled'
  option ndp 'disabled'

config odhcpd 'odhcpd'
  option maindhcp '0'
DHCP
cat > "$root/etc/config/dropbear.new" <<'SSH'
config dropbear 'main'
  option enable '1'
  option PasswordAuth 'off'
  option RootPasswordAuth 'off'
  option RootLogin 'on'
  option Interface 'lan'
  option Port '22'
  option LocalPortForward 'off'
  option RemotePortForward 'off'
SSH
awk -F: 'BEGIN {OFS=":"}
  NF != 9 {exit 5}
  $1 == "root" {$2="!"; roots++}
  {print}
  END {if(roots!=1) exit 6}' \
  "$root/etc/shadow" > "$root/etc/shadow.new"
chmod 0600 "$root/etc/shadow.new"
mv -f "$net.new" "$net"
mv -f "$root/etc/config/dhcp.new" "$root/etc/config/dhcp"
mv -f "$root/etc/config/dropbear.new" "$root/etc/config/dropbear"
mv -f "$root/etc/shadow.new" "$root/etc/shadow"
chmod 0600 "$net" "$root/etc/config/dhcp" "$root/etc/config/dropbear" \
  "$root/etc/shadow" "$root/etc/dropbear/authorized_keys"
# Explicitly distinct revision so trial monitors cannot mistake this
# role for the accepted lab image.
for f in "$root/etc/openwrt_version" "$root/etc/openwrt_release" \
         "$root/usr/lib/os-release" "$root/etc/banner"; do
  rg -Fq "$oldrev" "$f" || { echo "identity missing $oldrev from $f" >&2; exit 2; }
  awk -v old="$oldrev" -v new="$newrev" '{
    rest=$0
    updated=""
    while((i=index(rest,old))>0) {
      updated=updated substr(rest,1,i-1) new
      rest=substr(rest,i+length(old))
    }
    print updated rest
  }' "$f" > "$f.new"
  chmod --reference="$f" "$f.new"
  mv -f "$f.new" "$f"
done
{
  printf 'role=secondary-ap\nmode=%s\nsource_revision=%s\nrevision=%s\n' \
    "$mode" "$oldrev" "$newrev"
  if [ "$mode" = static ]; then printf 'management_ipv4=%s\n' "$cidr"; fi
  printf 'dhcpv4_server=off\ndhcpv6_server=off\nrouter_advertisements=off\n'
  printf 'dns_service=off\nroot_password_authentication=off\nroot_public_key_authentication=on\n'
} > "$root/etc/wave7-role-profile"
chmod 0644 "$root/etc/wave7-role-profile"
rg -qx 'role=secondary-ap' "$root/etc/wave7-role-profile"
rg -qx 'root:!:.*' "$root/etc/shadow"
rg -q "option ra 'disabled'" "$root/etc/config/dhcp"
rg -q "option PasswordAuth 'off'" "$root/etc/config/dropbear"
[ "$(cat "$root/etc/openwrt_version")" = "$newrev" ]
printf 'ROLE_STAGED mode=%s revision=%s\n' "$mode" "$newrev"
