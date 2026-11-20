#!/bin/sh
# The image is authoritative for exactly these role-owned settings. Keep
# SSH host keys, fw_env.config, ubihealthd and unrelated UBIFS state.
wave7_ap_policy_paths() {
    printf '%s\n' \
        etc/config/network etc/config/dhcp etc/config/dropbear \
        etc/config/wireless etc/config/firewall \
        etc/dropbear/authorized_keys etc/shadow \
        etc/openwrt_version etc/openwrt_release etc/wave7-role-profile \
        etc/init.d/wave7-firstboot-failsafe etc/banner \
        usr/lib/os-release \
        lib/preinit/05_wave7_firstboot_watchdog \
        lib/preinit/76_wave7_ap_overlay_reset \
        lib/wave7/overlay-reset.sh lib/wave7/role-firstboot.sh
}

# Check the complete migration contract before touching the volume, also
# called by the image packager against the actual extracted SquashFS.
wave7_ap_check_image() (
    [ "$#" -eq 1 ] || return 1
    for file in $(wave7_ap_policy_paths); do
        [ -f "$1/$file" ] && [ ! -L "$1/$file" ] || {
            echo "unexpected lower file: $file" >&2; return 1;
        }
    done
)

# Operate only on an unmounted-from-overlayfs writable volume. The caller
# supplies the temporary UBIFS mount and the immutable root independently.
wave7_ap_reset_upper() (
    [ "$#" -eq 2 ] || return 1
    upper="$1/upper"
    rom="$2"
    wave7_ap_check_image "$rom" || return 1
    # A fresh UBIFS need not have an upper directory yet.
    [ ! -L "$upper" ] || { echo 'invalid upper symlink' >&2; return 1; }
    [ -e "$upper" ] || return 0
    [ -d "$upper" ] || { echo 'invalid upper type' >&2; return 1; }
    for dir in etc etc/config etc/dropbear etc/init.d usr usr/lib \
               lib lib/preinit lib/wave7; do
        [ ! -L "$upper/$dir" ] || { echo "symlink parent: $dir" >&2; return 1; }
        [ ! -e "$upper/$dir" ] || [ -d "$upper/$dir" ] || {
            echo "non-directory parent: $dir" >&2; return 1;
        }
    done
    for file in $(wave7_ap_policy_paths); do
        if [ -d "$upper/$file" ] && [ ! -L "$upper/$file" ]; then
            echo "upper is directory: $file" >&2
            return 1
        fi
        rm -f "$upper/$file" || { echo "remove failed: $file" >&2; return 1; }
        [ ! -e "$upper/$file" ] && [ ! -L "$upper/$file" ] || {
            echo "upper still present: $file" >&2; return 1;
        }
    done
)

# Verify the mounted overlay view truly exposes the trusted SquashFS policy.
# A stale opaque directory or whiteout can otherwise keep old settings.
wave7_ap_policy_matches_lower() (
    root=/
    [ "$#" -eq 0 ] || root=$1
    case "$root" in /) root='' ;; esac
    for file in $(wave7_ap_policy_paths); do
        cmp -s "$root/rom/$file" "$root/$file" || {
            echo "merged policy differs: $file" >&2; return 1;
        }
    done
)
