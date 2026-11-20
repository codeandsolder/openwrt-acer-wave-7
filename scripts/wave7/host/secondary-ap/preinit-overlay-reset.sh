#!/bin/sh
# Called after mount_root's persistent UBIFS pivot but before board config
# generation or any network/SSH/DHCP/RA service starts.
wave7_ap_reset_preinit() (
    [ -e /rom/etc/wave7-role-profile ] || return 0
    role=$(sed -n 's/^role=//p' /rom/etc/wave7-role-profile)
    revision=$(sed -n 's/^revision=//p' /rom/etc/wave7-role-profile)

    # Read the role marker and executable helper strictly from the image
    # lowerdir; inherited overlay files are not trusted to define policy.
    if [ "$(board_name 2>/dev/null)" = acer,wave7 ] &&
       [ "$role" = secondary-ap ] &&
       [ "$revision" = "$(cat /rom/etc/openwrt_version)" ] &&
       [ -r /rom/lib/wave7/overlay-reset.sh ] &&
       [ -d /overlay/upper ] &&
       grep -q ' - ubifs ubi1:openwrt_data ' /proc/self/mountinfo &&
       grep -q ' root=/dev/ubiblock0_2 ' /proc/cmdline &&
       . /rom/lib/wave7/overlay-reset.sh &&
       wave7_ap_reset_upper / &&
       wave7_ap_policy_matches_lower /; then
        sync
        touch /tmp/wave7-ap-overlay-ready
        echo '<6>wave7-ap: inherited role policy cleared before startup' > /dev/kmsg 2>/dev/null || true
        return 0
    fi
    # The 120s kernel failsafe timer has already been armed. Stop before
    # procd launches potentially stale lab DHCP/RA/password SSH services.
    echo '<3>wave7-ap: unsafe persisted role policy; blocking services until recovery' > /dev/kmsg 2>/dev/null || true
    sleep 130
    echo 1 > /proc/sys/kernel/sysrq 2>/dev/null || true
    echo c > /proc/sysrq-trigger
    while :; do sleep 3600; done
)
boot_hook_add preinit_mount_root wave7_ap_reset_preinit
