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
    static:r0+*-ap-static-guard6|dhcp:r0+*-ap-dhcp-guard6) ;;
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
wave7_secondary_ap_link_ready() {
  [ -e /tmp/wave7-ap-overlay-ready ] || return 1
  [ "$(cat /sys/class/net/lan/carrier 2>/dev/null)" = 1 ] || return 1
  [ -r /etc/wave7-role-profile ] || return 1
  [ -r /tmp/wave7-ap-management-verified ] || return 1
  wave7_secondary_ap_contract_ok \
    "$(cat /etc/wave7-role-profile)" \
    "$(cat /etc/openwrt_version)" \
    "$(cat /proc/sys/kernel/random/boot_id)" \
    "$(cat /tmp/wave7-ap-management-verified)" \
    "$(cat /sys/class/net/lan/carrier)" \
    "$(ip -4 -o addr show dev br-lan 2>/dev/null)"
}
