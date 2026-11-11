#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
#
# Acer Wave 7: UBI0 has [wifi_fw, kernel, ubi_rootfs].
# UBI1 has vendor rootfs_data and our openwrt_data overlay.
# This same-slot upgrader modifies ONLY ubi0/kernel and ubi0/ubi_rootfs.
# Factory/vendor -> OpenWrt uses a different, supervised flash path.

WAVE7_UPGRADE_DIR=sysupgrade-acer_wave7
WAVE7_KERNEL=/dev/ubi0_1
WAVE7_ROOTFS=/dev/ubi0_2
RAMFS_COPY_BIN="$RAMFS_COPY_BIN /usr/sbin/ubiblock"

wave7_volume_matches() {
	local dir="/sys/class/ubi/$1"

	[ -r "$dir/name" ] || return 1
	[ "$(cat "$dir/name")" = "$2" ] || return 1
	[ "$(cat "$dir/type")" = "$3" ] || return 1
	[ -r "$dir/reserved_ebs" ] && [ -r "$dir/usable_eb_size" ]
}

wave7_check_layout() {
	local rootfs_mtd overlay_mtd

	rootfs_mtd=$(find_mtd_index rootfs)
	overlay_mtd=$(find_mtd_index rootfs_overlay)
	[ -n "$rootfs_mtd" ] && [ -n "$overlay_mtd" ] || return 1
	[ "$(cat /sys/class/ubi/ubi0/mtd_num 2>/dev/null)" = "$rootfs_mtd" ] || return 1
	[ "$(cat /sys/class/ubi/ubi1/mtd_num 2>/dev/null)" = "$overlay_mtd" ] || return 1

	wave7_volume_matches ubi0_0 wifi_fw static || return 1
	wave7_volume_matches ubi0_1 kernel static || return 1
	wave7_volume_matches ubi0_2 ubi_rootfs dynamic || return 1
	wave7_volume_matches ubi1_0 rootfs_data dynamic || return 1
	wave7_volume_matches ubi1_1 openwrt_data dynamic || return 1
	[ -c "$WAVE7_KERNEL" ] && [ -c "$WAVE7_ROOTFS" ]
}

wave7_check_tar() {
	local image="$1"
	local entries control

	[ -f "$image" ] || return 1
	entries=$(tar tf "$image") || return 1
	[ "$entries" = "sysupgrade-acer_wave7/
sysupgrade-acer_wave7/CONTROL
sysupgrade-acer_wave7/kernel
sysupgrade-acer_wave7/root" ] || return 1
	control=$(tar xOf "$image" "$WAVE7_UPGRADE_DIR/CONTROL") || return 1
	[ "$control" = BOARD=acer_wave7 ]
}

wave7_check_image_payload() {
	local image="$1"
	local kernel_size root_size kernel_capacity root_capacity
	local kernel_magic root_magic

	wave7_check_tar "$image" || return 1
	wave7_check_layout || return 1

	kernel_size=$(tar xOf "$image" "$WAVE7_UPGRADE_DIR/kernel" | wc -c) || return 1
	root_size=$(tar xOf "$image" "$WAVE7_UPGRADE_DIR/root" | wc -c) || return 1
	kernel_capacity=$(($(cat /sys/class/ubi/ubi0_1/reserved_ebs) *
			   $(cat /sys/class/ubi/ubi0_1/usable_eb_size))) || return 1
	root_capacity=$(($(cat /sys/class/ubi/ubi0_2/reserved_ebs) *
			 $(cat /sys/class/ubi/ubi0_2/usable_eb_size))) || return 1
	[ "$kernel_size" -gt 0 ] && [ "$root_size" -gt 0 ] || return 1
	[ "$kernel_size" -le "$kernel_capacity" ] || return 1
	[ "$root_size" -le "$root_capacity" ] || return 1

	kernel_magic=$(tar xOf "$image" "$WAVE7_UPGRADE_DIR/kernel" |
		       dd bs=4 count=1 2>/dev/null | hexdump -v -e '4/1 "%02x"') || return 1
	root_magic=$(tar xOf "$image" "$WAVE7_UPGRADE_DIR/root" |
		     dd bs=4 count=1 2>/dev/null | hexdump -v -e '4/1 "%02x"') || return 1
	[ "$kernel_magic" = d00dfeed ] && [ "$root_magic" = 68737173 ]
}

wave7_check_running_system() {
	[ "$(board_name)" = acer,wave7 ] || return 1
	[ -e /tmp/wave7-keep-boot ] || return 1
	grep -q ' root=/dev/ubiblock0_2 ' /proc/cmdline || return 1
	grep -q ' - ubifs ubi1:openwrt_data ' /proc/self/mountinfo || return 1
	[ "$(fw_printenv -n bootfail 2>/dev/null)" = 0 ]
}

platform_check_image() {
	wave7_check_running_system || {
		echo "Wave 7: upgrade requires accepted NAND OpenWrt boot" >&2
		return 1
	}
	wave7_check_image_payload "$1" || {
		echo "Wave 7: unrecognized image or unexpected UBI volume layout" >&2
		return 1
	}
	return 0
}

platform_pre_upgrade() {
	# Called before switching to ramfs; arm factory APPSBL fallback.
	platform_check_image "$1" || exit 1
	fw_setenv bootfail 4 || exit 1
	[ "$(fw_printenv -n bootfail 2>/dev/null)" = 4 ] || exit 1
	echo "wave7-upgrade: bootfail armed" > /dev/kmsg
}

platform_do_upgrade() {
	local image="$1"
	local kernel_image=/tmp/wave7-new-kernel.itb
	local root_image=/tmp/wave7-new-root.squashfs
	local kernel_len root_len

	# Called after pivoting to the RAM root. UBI1 must remain intact.
	wave7_check_image_payload "$image" || exit 1
	[ "$(fw_printenv -n bootfail 2>/dev/null)" = 4 ] || exit 1

	tar xOf "$image" "$WAVE7_UPGRADE_DIR/root" > "$root_image" || exit 1
	tar xOf "$image" "$WAVE7_UPGRADE_DIR/kernel" > "$kernel_image" || exit 1
	root_len=$(wc -c < "$root_image")
	kernel_len=$(wc -c < "$kernel_image")
	[ "$root_len" -gt 0 ] && [ "$kernel_len" -gt 0 ] || exit 1
	[ "$(dd if="$root_image" bs=4 count=1 2>/dev/null |
		hexdump -v -e '4/1 "%02x"')" = 68737173 ] || exit 1
	[ "$(dd if="$kernel_image" bs=4 count=1 2>/dev/null |
		hexdump -v -e '4/1 "%02x"')" = d00dfeed ] || exit 1

	# /rom must have been unmounted before releasing its ubiblock device.
	if grep -q ' /rom ' /proc/self/mountinfo; then
		echo "wave7-upgrade: root is still mounted; refusing write" >&2
		exit 1
	fi
	ubiblock -r "$WAVE7_ROOTFS" || exit 1

	# Update existing volumes IN PLACE; do not create/remove any UBI
	# volumes and do not touch the vendor's wifi_fw or rootfs_data.
	ubiupdatevol "$WAVE7_ROOTFS" -s "$root_len" "$root_image" || exit 1
	ubiupdatevol "$WAVE7_KERNEL" -s "$kernel_len" "$kernel_image" || exit 1

	echo "wave7-upgrade: kernel and rootfs committed" > /dev/kmsg
	sync
	return 0
}
