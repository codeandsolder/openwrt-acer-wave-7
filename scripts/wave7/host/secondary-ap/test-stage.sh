#!/bin/bash
set -euo pipefail
stage=$(cd -- "$(dirname -- "$0")" && pwd)/stage-root.sh
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
make_fixture() {
  local d=$1
  mkdir -p "$d/etc/config" "$d/etc/dropbear" "$d/usr/lib"
  cat > "$d/etc/config/network" <<'CFG'
config interface 'lan'
 option device 'br-lan'
 option proto 'static'
 list ipaddr '192.168.76.1/24'
CFG
  cat > "$d/etc/config/wireless" <<'CFG'
config wifi-iface 'mld'
 option mlo '1'
 option key 'dummy-test-secret'
CFG
  cat > "$d/etc/config/dropbear" <<'CFG'
config dropbear 'main'
 option enable '1'
 option PasswordAuth 'on'
CFG
  echo "config dhcp 'lan'" > "$d/etc/config/dhcp"
  printf '%s\n' 'root::0:0:99999:7:::' 'daemon:*:0:0:99999:7:::' > "$d/etc/shadow"
  echo 'ssh-ed25519 placeholder-synthetic-test-key' > "$d/etc/dropbear/authorized_keys"
  echo 'r0+1234-c0ffee1234' > "$d/etc/openwrt_version"
  echo "DISTRIB_REVISION='r0+1234-c0ffee1234'" > "$d/etc/openwrt_release"
  echo 'BUILD_ID="r0+1234-c0ffee1234"' > "$d/usr/lib/os-release"
  echo 'OpenWrt r0+1234-c0ffee1234' > "$d/etc/banner"
}
make_fixture "$work/dhcp"
make_fixture "$work/static"
"$stage" "$work/dhcp" dhcp > "$work/dhcp.result"
"$stage" "$work/static" static 192.168.76.1/24 > "$work/static.result"
rg -q 'ROLE_STAGED mode=dhcp' "$work/dhcp.result"
rg -q 'ROLE_STAGED mode=static' "$work/static.result"
rg -q "option proto 'dhcp'" "$work/dhcp/etc/config/network"
rg -q "list ipaddr '192.168.76.1/24'" "$work/static/etc/config/network"
for d in "$work/dhcp" "$work/static"; do
  rg -q "option disabled '1'" "$d/etc/config/dhcp"
  for role in "dhcpv4 'disabled'" "dhcpv6 'disabled'" "ra 'disabled'" "ndp 'disabled'"; do
    rg -Fq "$role" "$d/etc/config/dhcp"
  done
  rg -q "option PasswordAuth 'off'" "$d/etc/config/dropbear"
  rg -q "option RootPasswordAuth 'off'" "$d/etc/config/dropbear"
  rg -q "option RootLogin 'on'" "$d/etc/config/dropbear"
  rg -q '^root:!:0:0:99999:7:::$' "$d/etc/shadow"
  rg -q '^daemon:\*:0:0:99999:7:::$' "$d/etc/shadow"
  rg -q 'dummy-test-secret' "$d/etc/config/wireless"
  rg -q 'ssh-ed25519 placeholder' "$d/etc/dropbear/authorized_keys"
  [ "$(stat -c %a "$d/etc/config/dropbear")" = 600 ]
  [ "$(stat -c %a "$d/etc/dropbear/authorized_keys")" = 600 ]
  if "$stage" "$d" dhcp >/dev/null 2>&1; then
    echo 'DOUBLE_STAGING_MUST_FAIL' >&2
    exit 1
  fi
done
for invalid in 192.168.76.999/24 192.168.76.1/0 192.168.76.0/24 192.168.76.255/24 127.0.0.1/8 239.0.0.1/24 192.168.76.01/24 '192.168.76.1/24;touch' xyz ''; do
  make_fixture "$work/bad"
  if "$stage" "$work/bad" static "$invalid" >/dev/null 2>&1; then
    echo "INVALID_CIDR_ACCEPTED $invalid" >&2
    exit 1
  fi
done
make_fixture "$work/no-key"
: > "$work/no-key/etc/dropbear/authorized_keys"
if "$stage" "$work/no-key" dhcp >/dev/null 2>&1; then
  echo 'MISSING_SSH_KEY_ACCEPTED' >&2
  exit 1
fi
echo SECONDARY_AP_STAGE_TEST_PASS
