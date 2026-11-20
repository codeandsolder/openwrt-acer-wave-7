#!/usr/bin/env bash
# Offline Wave7 secondary-AP sysupgrade variant builder. No live router access.
set -euo pipefail
umask 077
if (( $# < 4 || $# > 5 )); then
  echo "usage: $0 SOURCE_IMAGE SHA256 dhcp|static OUTPUT_DIR [IPv4/CIDR]" >&2
  exit 2
fi
source_image=$(realpath -e "$1")
source_sha=$2
mode=$3
out=$4
address=""
if (( $# == 5 )); then address=$5; fi
[[ $source_sha =~ ^[a-f0-9]{64}$ ]] || { echo bad-source-sha >&2; exit 2; }
[[ $mode == dhcp || $mode == static ]] || { echo invalid-mode >&2; exit 2; }
[[ $mode == static && -n $address || $mode == dhcp && -z $address ]] || {
  echo 'static address required only in static mode' >&2; exit 2
}
[[ ! -e "$out" ]] || { echo 'refusing existing output' >&2; exit 2; }
out_parent=$(dirname -- "$out")
[[ -d "$out_parent" ]] || { echo 'missing output parent' >&2; exit 2; }
out=$(realpath -m "$out")
repo=$(cd -- "$(dirname -- "$0")/../../../.." && pwd)
buildrepo=$repo
if [[ -v WAVE7_OPENWRT_BUILD_ROOT && -n $WAVE7_OPENWRT_BUILD_ROOT ]]; then buildrepo=$WAVE7_OPENWRT_BUILD_ROOT; fi
tools="$buildrepo/staging_dir/host/bin"
for name in unsquashfs4 mksquashfs4 fwtool; do
  [[ -x "$tools/$name" ]] || { echo "missing host tool $name" >&2; exit 2; }
done
for name in sha256sum jq tar awk rg rsync; do command -v "$name" >/dev/null; done
[[ $(sha256sum "$source_image" | cut -d' ' -f1) == "$source_sha" ]] || {
  echo 'image SHA256 mismatch' >&2; exit 3
}
test "$(tar -xOf "$source_image" sysupgrade-acer_wave7/CONTROL)" = BOARD=acer_wave7
work=$(mktemp -d "$out_parent/.wave7-ap-profile.XXXXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir "$work/publish"
tar -xOf "$source_image" sysupgrade-acer_wave7/kernel > "$work/kernel.itb"
tar -xOf "$source_image" sysupgrade-acer_wave7/root > "$work/root.squashfs"
"$tools/fwtool" -i "$work/source-metadata.json" "$source_image"
source_rev=$(jq -er 'select(.version.target=="qualcommbe/ipq53xx" and .version.board=="acer_wave7") | .version.revision' "$work/source-metadata.json")
[[ $source_rev == r0+* && $source_rev != *-ap-* ]] || {
  echo 'invalid source revision' >&2; exit 3
}
new_rev="$source_rev-ap-$mode-auth"
echo 'dev/console' > "$work/excluded-console"
"$tools/unsquashfs4" -ll "$work/root.squashfs" > "$work/baseline-list.txt"
test "$(rg -c '^crw.* squashfs-root/dev/console$' "$work/baseline-list.txt")" = 1
test "$(rg -c '^[cbps]' "$work/baseline-list.txt")" = 1
"$tools/unsquashfs4" -no-progress -d "$work/root" -exclude-file "$work/excluded-console" "$work/root.squashfs" > "$work/extract.log"
rg -q '^created 0 devices$' "$work/extract.log"
test "$(cat "$work/root/etc/openwrt_version")" = "$source_rev"
cp -a "$work/root" "$work/original-root"
"$repo/scripts/wave7/host/secondary-ap/stage-root.sh" "$work/root" "$mode" "$address" > "$work/stage.log"
test "$(cat "$work/root/etc/openwrt_version")" = "$new_rev"
cmp "$work/original-root/etc/config/wireless" "$work/root/etc/config/wireless"
cmp "$work/original-root/etc/dropbear/authorized_keys" "$work/root/etc/dropbear/authorized_keys"
(cd "$work/root/lib/firmware/ath12k" &&
 sha256sum -c --status "$buildrepo/scripts/wave7/firmware.sha256" &&
 sha256sum -c --status "$buildrepo/scripts/wave7/diagnostic-firmware.sha256")
# rsync compares symlink *targets* and metadata without following OpenWrt's
# deliberately dangling runtime links (/etc/board.json, /etc/TZ, BusyBox).
# Dry-run + checksum prevents false negatives due timestamps.
rsync -aincO --delete --out-format='%n' \
  "$work/original-root/" "$work/root/" > "$work/differences.txt"
expected=$'deleting etc/wave7-role-profile\ndeleting lib/wave7/role-firstboot.sh\ndeleting lib/wave7/\netc/banner\netc/config/dhcp\netc/config/dropbear\netc/config/network\netc/openwrt_release\netc/openwrt_version\netc/shadow\nlib/preinit/05_wave7_firstboot_watchdog\nusr/lib/os-release'
# Accepted images may already ship the authorized key with mode 0600;
# a permission-only change is allowed but not required.
actual=$(LC_ALL=C sort "$work/differences.txt" | sed '/^etc\/dropbear\/authorized_keys$/d')
want=$(printf '%s\n' "$expected" | LC_ALL=C sort)
if [[ "$actual" != "$want" ]]; then
  printf 'ROLE_CHANGESET_MISMATCH\n%s\n' "$actual" >&2
  diff -u <(printf '%s\n' "$want") <(printf '%s\n' "$actual") >&2 || :
  exit 4
fi
root_sq="$work/profile-root.squashfs"
"$tools/mksquashfs4" "$work/root" "$root_sq" \
  -nopad -noappend -root-owned -comp xz -Xpreset 9 -Xe \
  -Xlc 0 -Xlp 2 -Xpb 2 -b 256k \
  -p '/dev d 755 0 0' -p '/dev/console c 600 0 0 5 1' \
  -no-xattrs -block-readers 4 -small-readers 4 > "$work/mksquashfs.log"
root_size=$(stat -c %s "$root_sq")
test "$root_size" -le 29204480
"$tools/unsquashfs4" -ll "$root_sq" > "$work/profile-list.txt"
test "$(rg -c '^crw.* squashfs-root/dev/console$' "$work/profile-list.txt")" = 1
"$tools/unsquashfs4" -no-progress -d "$work/verified-root" \
  -exclude-file "$work/excluded-console" "$root_sq" > "$work/reextract.log"
rg -q '^created 0 devices$' "$work/reextract.log"
rsync -aincO --delete --out-format='%n' \
  "$work/root/" "$work/verified-root/" > "$work/roundtrip-diff.txt"
test ! -s "$work/roundtrip-diff.txt"
(cd "$work/verified-root/lib/firmware/ath12k" &&
 sha256sum -c --status "$buildrepo/scripts/wave7/firmware.sha256" &&
 sha256sum -c --status "$buildrepo/scripts/wave7/diagnostic-firmware.sha256")
test "$(cat "$work/verified-root/etc/openwrt_version")" = "$new_rev"
rg -q '^root:!:.*' "$work/verified-root/etc/shadow"
name="wave7-secondary-ap-$mode-auth-sysupgrade.bin"
export TOPDIR="$buildrepo"
SOURCE_DATE_EPOCH=$(git -C "$buildrepo" show -s --format=%ct HEAD)
export SOURCE_DATE_EPOCH
sh "$buildrepo/scripts/sysupgrade-tar.sh" --board acer_wave7 \
  --kernel "$work/kernel.itb" --rootfs "$root_sq" "$work/publish/$name" > "$work/sysupgrade-pack.log"
jq --arg rev "$new_rev" --arg mode "$mode" --arg sha "$source_sha" \
  '.version.revision=$rev | .wave7_role="secondary-ap" | .wave7_mode=$mode |
   .wave7_parent_image_sha256=$sha' \
  "$work/source-metadata.json" > "$work/profile-metadata.json"
"$tools/fwtool" -I "$work/profile-metadata.json" "$work/publish/$name"
"$tools/fwtool" -i "$work/verify-metadata.json" "$work/publish/$name"
diff -u <(jq -S . "$work/profile-metadata.json") <(jq -S . "$work/verify-metadata.json")
cmp "$work/kernel.itb" <(tar -xOf "$work/publish/$name" sysupgrade-acer_wave7/kernel)
test "$(tar -xOf "$work/publish/$name" sysupgrade-acer_wave7/CONTROL)" = BOARD=acer_wave7
cmp -n "$root_size" "$root_sq" <(tar -xOf "$work/publish/$name" sysupgrade-acer_wave7/root)
test "$(stat -c %s "$work/publish/$name")" -lt 30000000
(cd "$work/publish" && sha256sum "$name" > SHA256SUMS)
{
  echo "status=SECONDARY_AP_IMAGE_OFFLINE_VERIFIED"
  echo "build_source_commit=$(git -C "$buildrepo" rev-parse HEAD)"
  echo "base_image_sha256=$source_sha"
  echo "base_revision=$source_rev"
  echo "profile_revision=$new_rev"
  echo "mode=$mode"
  echo "management_ipv4=$address"
  echo "kernel_sha256=$(sha256sum "$work/kernel.itb" | cut -d' ' -f1)"
  echo "profile_squashfs_sha256=$(sha256sum "$root_sq" | cut -d' ' -f1)"
  echo "radio_firmware_files=46_sha256_verified"
  echo "changed_root_files=9_plus_role_marker_and_auth_helper"
  echo "repacked_rootfs_roundtrip=identical"
  echo "image_sha256=$(sha256sum "$work/publish/$name" | cut -d' ' -f1)"
  echo "root_password=locked"
  echo "ssh_password_login=disabled"
  echo "dhcpv4v6_ra_dns_service=disabled"
  echo "kernel_unchanged=yes"
} > "$work/publish/profile-report.txt"
mv "$work/publish" "$out"
echo "SECONDARY_AP_OFFLINE_PASS mode=$mode path=$out"
cat "$out/SHA256SUMS"
