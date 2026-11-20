#!/bin/sh
# preinit_mount_root is executed after mount_root pivots onto persistent
# UBIFS, ahead of procd network, WLAN, SSH, dnsmasq, and odhcpd startup.
wave7_ap_reset_preinit() {
    [ -e /rom/etc/wave7-role-profile ] || return 0
    if [ "$(board_name 2>/dev/null)" = acer,wave7 ] &&
       [ -r /lib/wave7/overlay-reset.sh ] &&
       [ -r /etc/openwrt_version ] &&
       cmp -s /rom/etc/wave7-role-profile /etc/wave7-role-profile &&
       [ -d /overlay/upper ] &&
       grep -q ' - ubifs ubi1:openwrt_data ' /proc/self/mountinfo &&
       grep -q ' root=/dev/ubiblock0_2 ' /proc/cmdline &&
       [ "$(sed -n 's/^role=//p' /etc/wave7-role-profile)" = secondary-ap ] &&
       [ "$(sed -n 's/^revision=//p' /etc/wave7-role-profile)" = "$(cat /etc/openwrt_version)" ] &&
       . /lib/wave7/overlay-reset.sh &&
       wave7_ap_reset_upper /; then
        clean=1
        for file in \
            etc/config/network etc/config/dhcp etc/config/dropbear \
            etc/config/wireless etc/config/firewall etc/config/system \
            etc/dropbear/authorized_keys etc/shadow; do
            cmp -s "/rom/$file" "/$file" || clean=0
        done
        if [ "$clean" = 1 ]; then
            sync
            touch /tmp/wave7-ap-overlay-ready
            echo '<6>wave7-ap: inherited lab config cleared before service startup' > /dev/kmsg 2>/dev/null || true
            return 0
        fi
    fi
    # The previously armed 120s kernel fallback fires while services are
    # blocked from starting. Do not allow legacy DHCP/RA/SSH to start.
    echo '<3>wave7-ap: overlay migration failed; blocking service startup until recovery' > /dev/kmsg 2>/dev/null || true
    sleep 130
    echo 1 > /proc/sys/kernel/sysrq 2>/dev/null || true
    echo c > /proc/sysrq-trigger
    while :; do sleep 3600; done
}
boot_hook_add preinit_mount_root wave7_ap_reset_preinit
