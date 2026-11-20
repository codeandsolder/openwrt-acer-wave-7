#!/bin/bash
set -euo pipefail
stage=$(cd -- "$(dirname -- "$0")" && pwd)/stage-root.sh
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
make_fixture() {
  local d=$1
  mkdir -p "$d/etc/config" "$d/etc/dropbear" "$d/usr/lib" "$d/lib/preinit" "$d/etc/init.d"
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
  echo "config firewall 'main'" > "$d/etc/config/firewall"
  echo "config system 'main'" > "$d/etc/config/system"
  printf '%s\n' 'root::0:0:99999:7:::' 'daemon:*:0:0:99999:7:::' > "$d/etc/shadow"
  echo 'ssh-ed25519 placeholder-synthetic-test-key' > "$d/etc/dropbear/authorized_keys"
  echo 'r0+1234-c0ffee1234' > "$d/etc/openwrt_version"
  echo "DISTRIB_REVISION='r0+1234-c0ffee1234'" > "$d/etc/openwrt_release"
  echo 'BUILD_ID="r0+1234-c0ffee1234"' > "$d/usr/lib/os-release"
  echo 'OpenWrt r0+1234-c0ffee1234' > "$d/etc/banner"
  printf 'wave7_firstboot_link_ready() {\n  true\n}\n' > "$d/lib/preinit/05_wave7_firstboot_watchdog"
  cat > "$d/etc/init.d/wave7-firstboot-failsafe" <<'FAILSAFE'
#!/bin/sh /etc/rc.common
wave7_firstboot_link_ready() {
  [ "$(cat /sys/class/net/lan/carrier 2>/dev/null)" = 1 ] || return 1
  ip -4 -o addr show dev br-lan | grep -Fq '192.168.76.1/24' || return 1
  ping -I br-lan -c 1 -W 1 192.168.76.2
}
start() {
  if wave7_firstboot_link_ready; then
    touch /tmp/wave7-keep-boot
  fi
}
FAILSAFE
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
  rg -q 'wave7_secondary_ap_link_ready' "$d/lib/preinit/05_wave7_firstboot_watchdog"
  sh -n "$d/lib/preinit/05_wave7_firstboot_watchdog"
  test -s "$d/lib/wave7/role-firstboot.sh"
  test -s "$d/lib/wave7/overlay-reset.sh"
  test -s "$d/lib/preinit/76_wave7_ap_overlay_reset"
  rg -Fq 'boot_hook_add preinit_mount_root wave7_ap_reset_preinit' "$d/lib/preinit/76_wave7_ap_overlay_reset"
  sh -n "$d/lib/preinit/76_wave7_ap_overlay_reset" "$d/lib/wave7/overlay-reset.sh"
  sh -n "$d/etc/init.d/wave7-firstboot-failsafe"
  rg -q 'return 1' "$d/etc/init.d/wave7-firstboot-failsafe"
  if rg -q '192[.]168[.]76[.][12]' "$d/etc/init.d/wave7-firstboot-failsafe"; then
    echo 'LATE_INIT_AUTH_BYPASS_STILL_PRESENT' >&2
    exit 1
  fi
  # Source the late-init function only, not the test's simulated start().
  extracted=$(sed -n '/^wave7_firstboot_link_ready() {/,/^}/p' "$d/etc/init.d/wave7-firstboot-failsafe")
  if (eval "$extracted"; wave7_firstboot_link_ready); then
    echo 'LATE_INIT_FALLBACK_ACCEPTED_UNATTESTED_AP' >&2
    exit 1
  fi
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
# Integration-style overlay fixture: start from a genuinely staged AP root,
# place a malicious/old standalone-router override for every role-owned
# file in its separate UBIFS upperdir, and verify only trusted image data
# remains authoritative. This test never edits the running router.
p="$work/overlay-reset"
cp -a "$work/static" "$p"
mkdir -p "$p/rom" "$p/overlay/upper"
. "$(dirname -- "$stage")/overlay-reset.sh"
for file in $(wave7_ap_policy_paths); do
  mkdir -p "$p/rom/$(dirname -- "$file")" \
           "$p/overlay/upper/$(dirname -- "$file")"
  cp "$p/$file" "$p/rom/$file"
  printf 'LEGACY-OVERRIDE-%s\\n' "$file" > "$p/overlay/upper/$file"
done
# System UCI is generated on first boot; the real SquashFS has no such file.
test ! -e "$p/rom/etc/config/system"
printf 'generated-system-MUST-SURVIVE\n' > "$p/overlay/upper/etc/config/system"
printf 'env-config-MUST-SURVIVE\\n' > "$p/overlay/upper/etc/fw_env.config"
printf 'host-identity-MUST-SURVIVE\\n' > "$p/overlay/upper/etc/dropbear/dropbear_ed25519_host_key"
printf 'ubootenv-MUST-SURVIVE\\n' > "$p/overlay/upper/etc/config/ubootenv"
wave7_ap_reset_upper "$p/overlay" "$p/rom"
wave7_ap_policy_matches_lower "$p"
wave7_ap_reset_upper "$p/overlay" "$p/rom" # idempotent on repeat boot
for file in $(wave7_ap_policy_paths); do
  test ! -e "$p/overlay/upper/$file"
done
rg -q '^generated-system-MUST-SURVIVE' "$p/overlay/upper/etc/config/system"
rg -q '^env-config-MUST-SURVIVE' "$p/overlay/upper/etc/fw_env.config"
rg -q '^host-identity-MUST-SURVIVE' "$p/overlay/upper/etc/dropbear/dropbear_ed25519_host_key"
rg -q '^ubootenv-MUST-SURVIVE' "$p/overlay/upper/etc/config/ubootenv"
# A fresh volume (stock OTA reformats it) has no upper yet.
mkdir "$work/fresh-volume"
wave7_ap_reset_upper "$work/fresh-volume" "$p/rom"
wave7_ap_check_image "$p/rom"
mv "$p/rom/etc/config/dhcp" "$work/missing-dhcp"
if wave7_ap_reset_upper "$work/fresh-volume" "$p/rom"; then
  echo 'INCOMPLETE_IMAGE_POLICY_ACCEPTED' >&2
  exit 1
fi
mv "$work/missing-dhcp" "$p/rom/etc/config/dhcp"

# Verify a stale merged policy does not pass the lowerdir check.
printf 'incorrect-merged-network\\n' > "$p/etc/config/network"
if wave7_ap_policy_matches_lower "$p"; then
  echo 'STALE_MERGED_NETWORK_ACCEPTED' >&2
  exit 1
fi
# The reset refuses to traverse symlinked parent paths.
q="$work/overlay-bad"
cp -a "$work/static" "$q"
mkdir -p "$q/rom" "$q/overlay/upper/etc"
ln -s /tmp/untrusted "$q/overlay/upper/etc/config"
if wave7_ap_reset_upper "$q/overlay" "$q/rom"; then
  echo 'SYMLINKED_OVERLAY_PARENT_ACCEPTED' >&2
  exit 1
fi
# Pure firstboot gate test; no kernel/router calls.
. "$(dirname -- "$stage")/role-firstboot.sh"
boot=11111111-2222-3333-4444-555555555555
rev_static=r0+38346-0fbc2cc77b-ap-static-guard6
rev_dhcp=r0+38346-0fbc2cc77b-ap-dhcp-guard6
profile_static=$'role=secondary-ap\nmode=static\nmanagement_ipv4=192.168.76.1/24'
profile_dhcp=$'role=secondary-ap\nmode=dhcp'
ipstatic='3: br-lan    inet 192.168.76.1/24 brd 192.168.76.255 scope global br-lan'
ipdhcp='3: br-lan    inet 10.2.0.99/24 brd 10.2.0.255 scope global br-lan'
wave7_secondary_ap_contract_ok "$profile_static" "$rev_static" "$boot" "$boot $rev_static" 1 "$ipstatic"
wave7_secondary_ap_contract_ok "$profile_dhcp" "$rev_dhcp" "$boot" "$boot $rev_dhcp" 1 "$ipdhcp"
reject() {
  label=$1
  shift
  if wave7_secondary_ap_contract_ok "$@"; then
    echo "INVALID_FIRSTBOOT_ACCEPTED $label" >&2
    exit 1
  fi
}
reject stale "$profile_static" "$rev_static" "$boot" "aaaaaaaa-2222-3333-4444-555555555555 $rev_static" 1 "$ipstatic"
reject missing "$profile_static" "$rev_static" "$boot" "" 1 "$ipstatic"
reject wrongrev "$profile_static" "$rev_static" "$boot" "$boot $rev_dhcp" 1 "$ipstatic"
reject no_carrier "$profile_static" "$rev_static" "$boot" "$boot $rev_static" 0 "$ipstatic"
reject no_addr "$profile_dhcp" "$rev_dhcp" "$boot" "$boot $rev_dhcp" 1 ""
reject wrong_role "role=lab" "$rev_static" "$boot" "$boot $rev_static" 1 "$ipstatic"
reject mismatched_ip "$profile_static" "$rev_static" "$boot" "$boot $rev_static" 1 "$ipdhcp"
reject mismatched_mode "$profile_static" "$rev_dhcp" "$boot" "$boot $rev_dhcp" 1 "$ipstatic"
echo SECONDARY_AP_STAGE_AND_BOOT_GUARD_TEST_PASS
