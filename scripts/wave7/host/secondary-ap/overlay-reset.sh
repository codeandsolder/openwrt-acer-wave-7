#!/bin/sh
# The image is authoritative for exactly these role-owned settings. Keep
# SSH host keys, fw_env.config, ubihealthd and unrelated UBIFS state.
wave7_ap_policy_paths() {
    printf '%s\n' \
        etc/config/network etc/config/dhcp etc/config/dropbear \
        etc/config/wireless etc/config/firewall etc/config/system \
        etc/dropbear/authorized_keys etc/shadow \
        etc/openwrt_version etc/openwrt_release etc/wave7-role-profile \
        etc/init.d/wave7-firstboot-failsafe etc/banner \
        usr/lib/os-release \
        lib/preinit/05_wave7_firstboot_watchdog \
        lib/preinit/76_wave7_ap_overlay_reset \
        lib/wave7/overlay-reset.sh lib/wave7/role-firstboot.sh
}

# Use subshell functions so early preinit state/variables are not modified.
wave7_ap_reset_upper() (
    root=/
    [ "$#" -eq 0 ] || root=$1
    case "$root" in /) root='' ;; esac
    upper="$root/overlay/upper"
    rom="$root/rom"

    [ -d "$upper" ] && [ ! -L "$upper" ] || return 1
    for dir in etc etc/config etc/dropbear etc/init.d usr usr/lib \
               lib lib/preinit lib/wave7; do
        [ ! -L "$upper/$dir" ] || return 1
        [ ! -e "$upper/$dir" ] || [ -d "$upper/$dir" ] || return 1
    done
    for file in $(wave7_ap_policy_paths); do
        [ -f "$rom/$file" ] && [ ! -L "$rom/$file" ] || return 1
        if [ -d "$upper/$file" ] && [ ! -L "$upper/$file" ]; then
            return 1
        fi
        rm -f "$upper/$file" || return 1
        [ ! -e "$upper/$file" ] && [ ! -L "$upper/$file" ] || return 1
    done
)

# Verify the mounted overlay view truly exposes the trusted SquashFS policy.
# A stale opaque directory or whiteout can otherwise keep old settings.
wave7_ap_policy_matches_lower() (
    root=/
    [ "$#" -eq 0 ] || root=$1
    case "$root" in /) root='' ;; esac
    for file in $(wave7_ap_policy_paths); do
        cmp -s "$root/rom/$file" "$root/$file" || return 1
    done
)
