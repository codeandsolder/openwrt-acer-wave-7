#!/usr/bin/env bash
set -euo pipefail
# Run on Asus during a supervised NAND-root trial. Read-only.
if (( $# != 1 )) || [[ ! "$1" =~ ^[0-9a-f]{10}$ ]]; then
    echo "Usage: $0 EXPECTED_REVISION_SHA10" >&2
    exit 2
fi
expected_rev=$1
ssh -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=5 \
    -o ConnectionAttempts=1 -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -i /home/jan/.ssh/wave7-root-rsa root@192.168.76.1 \
    "EXPECTED_REV=$expected_rev sh -s" <<'ROUTER'
set -eu
check() {
    if "$@"; then :; else
        printf 'NANDROOT_CHECK_FAILED: %s\n' "$*" >&2
        exit 1
    fi
}
check test "$(uname -r)" = 6.18.60
check grep -q "$EXPECTED_REV" /etc/openwrt_release
check test "$(cat /sys/class/mtd/mtd18/ecc_strength)" = 8
dev=$(cat /sys/class/block/ubiblock0_2/dev)
check test -n "$dev"
check awk -v dev="$dev" '
    $3 == dev && $5 == "/rom" && / - squashfs / { found = 1 }
    END { exit !found }
' /proc/self/mountinfo
check awk '/ - ubifs / { bad = 1 } END { exit bad }' /proc/self/mountinfo
check test -f /tmp/wave7-keep-boot
echo 'ROOT_DEVICE=ubiblock0_2'
echo 'ROOTFS_MOUNT=verified-squashfs'
echo 'VENDOR_UBIFS_MOUNT=absent'
echo 'KEEP_BOOT_ARMED=1'
echo '=== ROOT_AND_OVERLAY ==='
awk '$5 == "/" || $5 == "/rom" || $5 == "/overlay" {print}' /proc/self/mountinfo
echo '=== RELEASE ==='
cat /etc/openwrt_release
echo '=== UBI ==='
ubinfo -a
echo '=== MTD ==='
cat /proc/mtd
echo '=== NETWORK ==='
ip -4 addr show dev br-lan
check ping -I br-lan -c 2 -W 1 192.168.76.2
echo '=== RADIO ==='
for r in /sys/class/remoteproc/remoteproc*;do
    check test "$(cat "$r/state")" = running
    printf '%s: %s\n' "$(basename "$r")" "$(cat "$r/name")"
done
iw dev
check sh -c 'iw dev | grep -Eq "link ID[[:space:]]+0"'
check sh -c 'iw dev | grep -Eq "link ID[[:space:]]+1"'
check test "$(cat /sys/class/mtd/mtd18/ecc_failures)" = 0
echo "ART_ECC_CORRECTED_BITS=$(cat /sys/class/mtd/mtd18/corrected_bits)"
echo "BOOT_UPTIME=$(cat /proc/uptime)"
echo 'NANDROOT_LIVE_VALIDATION=PASS'
ROUTER
