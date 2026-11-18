#!/bin/sh
set -eu

[ "$#" -eq 3 ] || {
    echo "Usage: $0 nand|ram DTB DTC" >&2
    exit 2
}
mode=$1
dtb=$2
dtc=$3
[ -s "$dtb" ] && [ -x "$dtc" ] || {
    echo "Wave 7 boot DTB/compiler missing" >&2
    exit 1
}

# Fail closed on drift from either known-good, distinct boot mode.
case "$mode" in
    nand)
        expected=' ubi.mtd=rootfs_overlay,0,4,1 ubi.block=0,ubi_rootfs root=/dev/ubiblock0_2 rootwait=90 fstools_overlay_name=openwrt_data panic=10 reboot=panic_w wave7.defer_wifi=1 wave7.autoprobe=1 clk_ignore_unused'
        ;;
    ram)
        expected=' root=/dev/ram0 rdinit=/init panic=10 reboot=panic_w wave7.defer_wifi=1 wave7.autoprobe=1 clk_ignore_unused ubi.no_autoattach=1'
        ;;
    *)
        echo "Unknown Wave 7 boot mode: $mode" >&2
        exit 2
        ;;
esac

args=$("$dtc" -q -I dtb -O dts "$dtb" |
    sed -n 's/^[[:space:]]*bootargs-append = "\([^"]*\)";[[:space:]]*$/\1/p')
if [ "$args" != "$expected" ]; then
    echo "Wave 7 $mode bootargs-append does not match its pinned mode: $dtb" >&2
    exit 1
fi
echo "Wave 7 $mode bootargs-append verified"
