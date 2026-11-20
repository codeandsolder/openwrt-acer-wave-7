#!/bin/sh
# Clear inherited router policy overrides without removing independent
# persistent UBIFS data: bootloader env config, SSH host keys, etc.
wave7_ap_reset_upper() {
    root=/
    [ "$#" -eq 0 ] || root=$1
    case "$root" in /) root='' ;; esac
    upper="$root/overlay/upper"
    rom="$root/rom"

    [ -d "$upper" ] && [ ! -L "$upper" ] || return 1
    for dir in etc etc/config etc/dropbear; do
        [ ! -L "$upper/$dir" ] || return 1
        [ ! -e "$upper/$dir" ] || [ -d "$upper/$dir" ] || return 1
    done
    [ -d "$rom/etc/config" ] && [ ! -L "$rom/etc/config" ] || return 1
    [ -d "$rom/etc/dropbear" ] && [ ! -L "$rom/etc/dropbear" ] || return 1

    # Only role-specific policy defaults; leave fw_env.config,
    # ubihealthd, boot metadata and SSH host identity untouched.
    for file in \
        etc/config/network etc/config/dhcp etc/config/dropbear \
        etc/config/wireless etc/config/firewall etc/config/system \
        etc/dropbear/authorized_keys etc/shadow; do
        [ -f "$rom/$file" ] && [ ! -L "$rom/$file" ] || return 1
        if [ -d "$upper/$file" ] && [ ! -L "$upper/$file" ]; then
            return 1
        fi
        rm -f "$upper/$file" || return 1
        [ ! -e "$upper/$file" ] && [ ! -L "$upper/$file" ] || return 1
    done
}
