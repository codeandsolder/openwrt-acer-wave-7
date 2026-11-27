#!/bin/sh
# Boot-time acceptance gate for *derived* secondary AP firmware.
# The default lab image must never load this helper.
#
# A new candidate boot is accepted only after an external controller has
# authenticated to Dropbear using the preserved public SSH key and written
# "<current boot UUID> <current AP revision>" to the volatile marker.
# If the independent host cannot log in, firstboot's 120s hard deadline
# remains armed and the existing bootloader fallback handles recovery.
wave7_secondary_ap_contract_ok() {
  profile=$1
  revision=$2
  boot_id=$3
  marker=$4
  carrier=$5
  addresses=$6
  printf '%s\n' "$profile" | grep -Fxq 'role=secondary-ap' || return 1
  mode=$(printf '%s\n' "$profile" | sed -n 's/^mode=//p')
  case "$mode:$revision" in
    static:r0+*-ap-static-guard8|dhcp:r0+*-ap-dhcp-guard8) ;;
    *) return 1 ;;
  esac
  [ "$carrier" = 1 ] || return 1
  # Fail if the token is from the old boot or from another image role.
  [ -n "$boot_id" ] && [ "$marker" = "$boot_id $revision" ] || return 1
  case "$boot_id" in
    ????????-????-????-????-????????????) ;;
    *) return 1 ;;
  esac
  if [ "$mode" = static ]; then
    management=$(printf '%s\n' "$profile" | sed -n 's/^management_ipv4=//p')
    [ -n "$management" ] || return 1
    printf '%s\n' "$addresses" | grep -Fq "inet $management " || return 1
  else
    printf '%s\n' "$addresses" | grep -Eq 'inet [0-9]+(\.[0-9]+){3}/[0-9]+ ' || return 1
  fi
}
# An approval covers the complete immutable manifest, including the exact
# source image hash, role builder commit, mode and management configuration.
wave7_secondary_ap_identity() (
  manifest=$1
  revision=$2
  grep -Fxq 'role=secondary-ap' "$manifest" || exit 1
  grep -Fxq "revision=$revision" "$manifest" || exit 1
  grep -Eq '^builder_commit=[0-9a-f]{40}$' "$manifest" || exit 1
  grep -Eq '^base_image_sha256=[0-9a-f]{64}$' "$manifest" || exit 1
  digest=$(sha256sum "$manifest") || exit 1
  printf '%s %s\n' "$revision" "${digest%% *}"
)

wave7_secondary_ap_approval_matches() (
  manifest=$1
  revision=$2
  record=$3
  [ -f "$record" ] && [ ! -L "$record" ] || exit 1
  # BusyBox stat is not installed in the accepted base image.
  metadata=$(ls -ldn "$record") || exit 1
  set -- $metadata
  [ "$1" = -rw------- ] && [ "$3" = 0 ] && [ "$4" = 0 ] || exit 1
  expected=$(wave7_secondary_ap_identity "$manifest" "$revision") || exit 1
  # Use byte comparison so suffix garbage or duplicate lines cannot pass.
  printf '%s\n' "$expected" | cmp -s - "$record"
)

# Pure policy: approved DHCP APs must not crash-loop when the upstream
# DHCP server is unavailable. Unapproved images always need a live token,
# an address and a wired carrier. Static addresses remain mandatory.
wave7_secondary_ap_gate_ok() (
  profile=$1
  revision=$2
  approved=$3
  addresses=$4
  shift 4
  if [ "$approved" != 1 ]; then
    wave7_secondary_ap_contract_ok "$profile" "$revision" "$1" "$2" "$3" "$addresses"
    exit $?
  fi
  printf '%s\n' "$profile" | grep -Fxq 'role=secondary-ap' || exit 1
  mode=$(printf '%s\n' "$profile" | sed -n 's/^mode=//p')
  case "$mode:$revision" in
    dhcp:r0+*-ap-dhcp-guard8) exit 0 ;;
    static:r0+*-ap-static-guard8)
      management=$(printf '%s\n' "$profile" | sed -n 's/^management_ipv4=//p')
      [ -n "$management" ] || exit 1
      printf '%s\n' "$addresses" | grep -Fq "inet $management "
      ;;
    *) exit 1 ;;
  esac
)

wave7_secondary_ap_local_ready() (
  [ -e /tmp/wave7-ap-overlay-ready ] || exit 1
  # shellcheck disable=SC1091
  . /rom/lib/wave7/overlay-reset.sh
  wave7_ap_policy_matches_lower / || exit 1
  for port in lan lan1 lan2 game ap-mld0; do
    [ -e "/sys/class/net/br-lan/brif/$port" ] || exit 1
  done
  for pd in 0 1 2; do
    [ "$(cat "/sys/class/remoteproc/remoteproc$pd/state" 2>/dev/null)" = running ] || exit 1
  done
  info=$(iw dev ap-mld0 info 2>/dev/null) || exit 1
  for link in 0 1; do
    printf '%s\n' "$info" | grep -Eq "link ID[[:space:]]+$link([[:space:]]|$)" || exit 1
  done
  logs=$(dmesg) || exit 1
  if printf '%s\n' "$logs" | grep -q 'NOC ERROR DETECTED'; then exit 1; fi
)

wave7_secondary_ap_any_wired_carrier() (
  for port in lan lan1 lan2 game; do
    if [ "$(cat "/sys/class/net/$port/carrier" 2>/dev/null)" = 1 ]; then
      printf '1\n'
      exit 0
    fi
  done
  printf '0\n'
)

wave7_secondary_ap_link_ready() (
  wave7_secondary_ap_local_ready || exit 1
  manifest=/rom/etc/wave7-role-profile
  revision=$(cat /rom/etc/openwrt_version) || exit 1
  profile=$(cat "$manifest") || exit 1
  approved=0
  if wave7_secondary_ap_approval_matches "$manifest" "$revision" /overlay/wave7-ap-approved; then
    approved=1
  fi
  addresses=$(ip -4 -o addr show dev br-lan 2>/dev/null) || exit 1
  wave7_secondary_ap_gate_ok "$profile" "$revision" "$approved" "$addresses" \
    "$(cat /proc/sys/kernel/random/boot_id)" \
    "$(cat /tmp/wave7-ap-management-verified 2>/dev/null || :)" \
    "$(wave7_secondary_ap_any_wired_carrier)"
)

# Called explicitly via authenticated management AFTER the independent soak
# and client/wire tests. It can neither set bootfail nor create keep-boot.
wave7_secondary_ap_approve() (
  [ "$#" = 2 ] || exit 1
  expected_boot=$1
  expected_revision=$2
  [ "$(cat /proc/sys/kernel/random/boot_id)" = "$expected_boot" ] || exit 1
  [ "$(cat /rom/etc/openwrt_version)" = "$expected_revision" ] || exit 1
  [ "$(fw_printenv -n bootfail)" = 0 ] || exit 1
  [ -e /tmp/wave7-keep-boot ] || exit 1
  wave7_secondary_ap_local_ready || exit 1
  manifest=/rom/etc/wave7-role-profile
  wave7_secondary_ap_contract_ok "$(cat "$manifest")" "$expected_revision" \
    "$expected_boot" "$(cat /tmp/wave7-ap-management-verified)" \
    "$(wave7_secondary_ap_any_wired_carrier)" "$(ip -4 -o addr show dev br-lan)" || exit 1
  identity=$(wave7_secondary_ap_identity "$manifest" "$expected_revision") || exit 1
  umask 077
  tmp=$(mktemp /overlay/.wave7-ap-approved.XXXXXXXX) || exit 1
  trap 'rm -f "$tmp"' EXIT
  printf '%s\n' "$identity" > "$tmp" || exit 1
  chmod 0600 "$tmp" && chown 0:0 "$tmp" || exit 1
  dest=/overlay/wave7-ap-approved
  [ ! -d "$dest" ] && [ ! -L "$dest" ] || exit 1
  mv -f "$tmp" "$dest" && sync || exit 1
  wave7_secondary_ap_approval_matches "$manifest" "$expected_revision" "$dest" || exit 1
  printf 'AP_PERSISTENT_APPROVAL_STORED\n'
)
