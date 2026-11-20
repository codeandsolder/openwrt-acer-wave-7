#!/usr/bin/env bash
# Derive from the exact accepted native-recovery secondary AP.
# Replace only the FIT and five root identity files.
set -euo pipefail
umask 077
[[ $# == 5 ]] || { echo 'usage: build-trial-image.sh PARENT FIT FIT_SHA RAW_KERNEL OUTPUT_DIR' >&2; exit 2; }
parent=$(realpath -e "$1")
fit=$(realpath -e "$2")
fit_sha=$3
raw=$(realpath -e "$4")
out=$(realpath -m "$5")
repo=$(cd "$(dirname "$0")/../../../.." && pwd)
prod=/home/jan/projects/wave7-prod-integrated
tools="$prod/staging_dir/host/bin"
parent_sha=1da743efe01ab63043b314a6d44de52e99d65456259f0dae0c1d53a013918f2c
parent_rev=r0+38346-0e69b8931c-ap-dhcp-guard8
kernel_sha=9258ee2d5c2b9d154552d000fc8deb647bc85a02efc9c1086700736473757be4
patch_commit=0418bb7af25d13406bb896696eb78541ccd2aa00
new_rev="r0+38346-${patch_commit:0:10}-ap-dhcp-guard8"
stripped_sha=ff6b4c93d9ce2cb71b2b8dfd0053df70cc4a3ad4960bd49c099eceea85d7fe91
digest() { sha256sum "$1" | cut -d' ' -f1; }
fail() { echo "PHY_IMAGE_FAIL $*" >&2; exit 1; }
[[ ! -e $out && -d $(dirname "$out") ]] || fail 'output must not exist'
[[ -z $(git -C "$repo" status --porcelain) ]] || fail 'dirty source'
git -C "$repo" merge-base --is-ancestor "$patch_commit" HEAD
builder=$(git -C "$repo" rev-parse HEAD)
[[ $(digest "$parent") == "$parent_sha" ]] || fail 'parent digest'
[[ $fit_sha =~ ^[0-9a-f]{64}$ && $(digest "$fit") == "$fit_sha" ]] || fail 'FIT digest'
[[ $(tar xOf "$parent" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || fail 'board'
work=$(mktemp -d "$(dirname "$out")/.wave7-phy.XXXXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir "$work/publish"
tar xOf "$parent" sysupgrade-acer_wave7/kernel > "$work/kernel.itb"
[[ $(digest "$work/kernel.itb") == "$kernel_sha" ]] || fail 'kernel digest'
uv run --no-project --offline --python /usr/bin/python3 python "$(dirname "$0")/verify-fit.py" "$work/kernel.itb" "$fit" "$raw" > "$work/publish/fit-verification.txt"
cp "$fit" "$work/kernel.itb"
tar xOf "$parent" sysupgrade-acer_wave7/root > "$work/root.sq"
"$tools/fwtool" -i "$work/old-metadata.json" "$parent"
[[ $(jq -er '.version.revision' "$work/old-metadata.json") == "$parent_rev" ]] || fail 'parent metadata'
echo dev/console > "$work/excluded"
"$tools/unsquashfs4" -ll "$work/root.sq" > "$work/old-list"
[[ $(rg -c '^[cbps]' "$work/old-list") == 1 && $(rg -c '^crw.* squashfs-root/dev/console$' "$work/old-list") == 1 ]] || fail 'device inventory'
(umask 000; "$tools/unsquashfs4" -no-progress -d "$work/root" -exclude-file "$work/excluded" "$work/root.sq") > "$work/extract.log"
rg -q '^created 0 devices$' "$work/extract.log"
cp -a "$work/root" "$work/orig"
root="$work/root"
rel=lib/modules/6.18.60/rtl8365mb.ko
[[ $(digest "$root/$rel") == "$stripped_sha" ]] || fail 'native switch module identity'
[[ $(cat "$root/etc/openwrt_version") == "$parent_rev" ]] || fail 'parent revision'
rg -qx 'mode=dhcp' "$root/etc/wave7-role-profile"
rg -Fxq "revision=$parent_rev" "$root/etc/wave7-role-profile"
# Changing the identity makes the old persistent approval ineligible.
for f in etc/openwrt_version etc/openwrt_release usr/lib/os-release etc/banner; do
  rg -Fq "$parent_rev" "$root/$f" || fail "revision missing: $f"
  sed -i "s/$parent_rev/$new_rev/g" "$root/$f"
done
m="$root/etc/wave7-role-profile"
sed -i -e "s/^source_revision=.*/source_revision=$parent_rev/" \
       -e "s/^revision=.*/revision=$new_rev/" \
       -e "s/^builder_commit=.*/builder_commit=$builder/" \
       -e "s/^base_image_sha256=.*/base_image_sha256=$parent_sha/" "$m"
printf 'trial_phy_kernel_patch_commit=%s\ntrial_fit_sha256=%s\n' "$patch_commit" "$fit_sha" >> "$m"
chmod --reference="$work/orig/etc/wave7-role-profile" "$m"
sh -c '. "$1"; wave7_ap_check_image "$2"' sh "$root/lib/wave7/overlay-reset.sh" "$root"
# The five root identity files are the entire root delta.
rsync -aincO --delete --out-format='%n' "$work/orig/" "$root/" | LC_ALL=C sort > "$work/delta"
printf '%s\n' etc/banner etc/openwrt_release etc/openwrt_version etc/wave7-role-profile usr/lib/os-release | LC_ALL=C sort > "$work/want"
diff -u "$work/want" "$work/delta"
export TOPDIR="$prod"
SOURCE_DATE_EPOCH=$(git -C "$repo" show -s --format=%ct HEAD)
export SOURCE_DATE_EPOCH
"$tools/mksquashfs4" "$root" "$work/new.sq" -nopad -noappend -root-owned -comp xz -Xpreset 9 -Xe -Xlc 0 -Xlp 2 -Xpb 2 -b 256k -p '/dev d 755 0 0' -p '/dev/console c 600 0 0 5 1' -no-xattrs -block-readers 4 -small-readers 4 > "$work/pack.log"
[[ $(stat -c %s "$work/new.sq") -le 29204480 ]] || fail 'rootfs limit'
"$tools/unsquashfs4" -ll "$work/new.sq" > "$work/new-list"
archive_modes() {
  awk 'match($0,/ squashfs-root(\/|$)/) {path=substr($0,RSTART+1); sub(/ -> .*/, "", path); print path "|" $1 "|" $2}' "$1" | LC_ALL=C sort
}
diff -u <(archive_modes "$work/old-list") <(archive_modes "$work/new-list")
(umask 000; "$tools/unsquashfs4" -no-progress -d "$work/roundtrip" -exclude-file "$work/excluded" "$work/new.sq") > "$work/reextract.log"
rsync -aincO --delete --out-format='%n' "$root/" "$work/roundtrip/" > "$work/roundtrip-delta"
[[ ! -s $work/roundtrip-delta ]] || fail 'roundtrip delta'
(cd "$work/roundtrip/lib/firmware/ath12k"; sha256sum -c --status "$prod/scripts/wave7/firmware.sha256"; sha256sum -c --status "$prod/scripts/wave7/diagnostic-firmware.sha256")
[[ $(digest "$work/roundtrip/$rel") == "$stripped_sha" ]] || fail 'roundtrip module'
image="$work/publish/wave7-stock-poll-fifo-dhcp-guard8-sysupgrade.bin"
sh "$repo/scripts/sysupgrade-tar.sh" --board acer_wave7 --kernel "$work/kernel.itb" --rootfs "$work/new.sq" "$image"
jq --arg rev "$new_rev" --arg parent "$parent_sha" --arg fit "$fit_sha" --arg patch "$patch_commit"   '.version.revision=$rev | .wave7_parent_image_sha256=$parent | .wave7_trial_phy_kernel_patch_commit=$patch | .wave7_trial_fit_sha256=$fit' "$work/old-metadata.json" > "$work/metadata"
"$tools/fwtool" -I "$work/metadata" "$image"
"$tools/fwtool" -i "$work/verified-metadata" "$image"
diff -u <(jq -S . "$work/metadata") <(jq -S . "$work/verified-metadata")
cmp "$work/kernel.itb" <(tar xOf "$image" sysupgrade-acer_wave7/kernel)
cmp -n "$(stat -c %s "$work/new.sq")" "$work/new.sq" <(tar xOf "$image" sysupgrade-acer_wave7/root)
[[ $(tar xOf "$image" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || fail 'packed board'
[[ $(stat -c %s "$image") -lt 30000000 ]] || fail 'packed size'
cat > "$work/publish/report.txt" <<REPORT
status=OFFLINE_VERIFIED
parent_revision=$parent_rev
parent_sha256=$parent_sha
revision=$new_rev
builder_commit=$builder
phy_kernel_patch_commit=$patch_commit
parent_kernel_sha256=$kernel_sha
kernel_sha256=$fit_sha
kernel_payload_sha256=$(digest "$raw")
native_switch_module_sha256=$stripped_sha
root_delta=five_identity_files
root_modes_owners=identical
root_roundtrip=identical
radio_firmware_files=46_sha256_verified
image_sha256=$(digest "$image")
REPORT
(cd "$work/publish"; sha256sum ./*sysupgrade.bin > SHA256SUMS)
mv "$work/publish" "$out"
echo PHY_IMAGE_OFFLINE_PASS
cat "$out/report.txt"
