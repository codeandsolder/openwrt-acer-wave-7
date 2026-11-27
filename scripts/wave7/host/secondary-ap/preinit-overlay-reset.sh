#!/bin/sh
# The first hook runs after 75_wave7_overlay_provision and before 80_mount_root.
# The second verifies the mounted merged view, without editing the raw upper.
wave7_ap_migration_fail() {
    echo "<3>wave7-ap: migration failed: $*" > /dev/kmsg 2>/dev/null || :
    # The original firstboot watchdog remains armed. Never launch services
    # with an unverified configuration.
    while :; do sleep 3600; done
}

wave7_ap_prepare_overlay() (
    [ -e /etc/wave7-role-profile ] || return 0
    [ "$(board_name)" = acer,wave7 ] || wave7_ap_migration_fail board
    [ "$(sed -n 's/^role=//p' /etc/wave7-role-profile)" = secondary-ap ] ||
        wave7_ap_migration_fail role
    [ "$(sed -n 's/^revision=//p' /etc/wave7-role-profile)" = "$(cat /etc/openwrt_version)" ] ||
        wave7_ap_migration_fail revision
    [ "$(cat /sys/class/ubi/ubi1_1/name 2>/dev/null)" = openwrt_data ] ||
        wave7_ap_migration_fail volume-name
    [ "$(cat /sys/class/ubi/ubi1_1/reserved_ebs 2>/dev/null)" = 56 ] ||
        wave7_ap_migration_fail volume-size
    [ "$(cat /sys/class/ubi/ubi1/mtd_num 2>/dev/null)" = 23 ] ||
        wave7_ap_migration_fail partition
    [ "$(cat /sys/class/mtd/mtd23/name 2>/dev/null)" = rootfs_overlay ] ||
        wave7_ap_migration_fail partition-name
    case " $(cat /proc/cmdline) " in
        *" root=/dev/ubiblock0_2 "*) ;;
        *) wave7_ap_migration_fail root-device ;;
    esac
    # Only migrate this volume before native mount_root uses it.
    tmp=/tmp/wave7-ap-policy-volume
    mkdir -m 0700 "$tmp" || wave7_ap_migration_fail temporary-mountpoint
    mount -t ubifs -o noatime ubi1:openwrt_data "$tmp" ||
        wave7_ap_migration_fail mount-volume
    . /lib/wave7/overlay-reset.sh || wave7_ap_migration_fail load-policy
    if ! result=$(wave7_ap_reset_upper "$tmp" / 2>&1); then
        umount "$tmp" || :
        wave7_ap_migration_fail "$result"
    fi
    sync
    umount "$tmp" || wave7_ap_migration_fail unmount-volume
    rmdir "$tmp" || wave7_ap_migration_fail cleanup-mountpoint
    touch /tmp/wave7-ap-overlay-prepared || wave7_ap_migration_fail prepared-marker
    echo '<6>wave7-ap: prepared dedicated UBIFS before overlay mount' > /dev/kmsg
)

wave7_ap_reset_preinit() (
    [ -e /rom/etc/wave7-role-profile ] || return 0
    [ -e /tmp/wave7-ap-overlay-prepared ] || wave7_ap_migration_fail not-prepared
    # Do not depend on one spelling of the UBIFS device source. Match the
    # mountpoint and filesystem, together with verified UBI identity.
    awk '$5 == "/overlay" { for(i=7;i<NF;i++) if($i=="-" && $(i+1)=="ubifs" && ($(i+2)=="ubi1:openwrt_data" || $(i+2)=="/dev/ubi1_1")) ok=1 } END {exit !ok}' \
        /proc/self/mountinfo || wave7_ap_migration_fail overlay-mount
    . /rom/lib/wave7/overlay-reset.sh || wave7_ap_migration_fail load-lower-helper
    result=$(wave7_ap_policy_matches_lower / 2>&1) ||
        wave7_ap_migration_fail "$result"
    touch /tmp/wave7-ap-overlay-ready || wave7_ap_migration_fail ready-marker
    echo '<6>wave7-ap: verified image policy in merged filesystem' > /dev/kmsg
)
boot_hook_add preinit_main wave7_ap_prepare_overlay
boot_hook_add preinit_mount_root wave7_ap_reset_preinit
