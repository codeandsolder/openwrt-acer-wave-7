#!/usr/bin/env bash
# Laboratory A/B: derive from the exact approved DHCP Guard8 image; replace
# one kernel module and identity metadata only. No router access.
set -euo pipefail
umask 077
[[ $# == 5 ]] || { echo 'usage: build-trial-image.sh trunk|native PARENT MODULE MODULE_SHA OUTPUT_DIR' >&2; exit 2; }
variant=$1; shift
parent=$(realpath -e "$1")
module=$(realpath -e "$2")
module_sha=$3
out=$(realpath -m "$4")
repo=$(cd "$(dirname "$0")/../../../.." && pwd)
prod=/home/jan/projects/wave7-prod-integrated
tools="$prod/staging_dir/host/bin"
toolchain="$prod/staging_dir/toolchain-aarch64_cortex-a53_gcc-14.4.0_musl/bin"
parent_sha=3a84923c5c18b1f1354985de975a775e3fbea464fc69dbf8e086267f0b917172
parent_rev=r0+38346-0fbc2cc77b-ap-dhcp-guard8
kernel_sha=9258ee2d5c2b9d154552d000fc8deb647bc85a02efc9c1086700736473757be4
case "$variant" in
  trunk)
    patch_commit=895ed9016db597e47be58e4373b986b17bb41fe3
    image_kind=trunk-health
    ;;
  native)
    patch_commit=0e69b8931cb9639367b293f825842703c0f39d29
    image_kind=native-recovery
    ;;
  *) echo 'unknown trunk trial variant' >&2; exit 2 ;;
esac
new_rev="r0+38346-${patch_commit:0:10}-ap-dhcp-guard8"
old_module_sha=ef2fd6186279e997be4368e358f6bda9c2f4222150c9704ad6c24c69a1f99ed7
digest() { sha256sum "$1" | cut -d' ' -f1; }
fail() { echo "TRUNK_IMAGE_FAIL $*" >&2; exit 1; }
[[ ! -e $out && -d $(dirname "$out") ]] || fail 'output must not exist'
[[ -z $(git -C "$repo" status --porcelain) ]] || fail 'dirty source'
git -C "$repo" merge-base --is-ancestor "$patch_commit" HEAD
builder=$(git -C "$repo" rev-parse HEAD)
[[ $(digest "$parent") == "$parent_sha" ]] || fail 'parent digest'
[[ $module_sha =~ ^[0-9a-f]{64}$ && $(digest "$module") == "$module_sha" ]] || fail 'module digest'
[[ $(tar xOf "$parent" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || fail 'board'
work=$(mktemp -d "$(dirname "$out")/.wave7-trunk.XXXXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir "$work/publish"
tar xOf "$parent" sysupgrade-acer_wave7/kernel > "$work/kernel.itb"
[[ $(digest "$work/kernel.itb") == "$kernel_sha" ]] || fail 'kernel digest'
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
[[ $(digest "$root/$rel") == "$old_module_sha" ]] || fail 'original module identity'
[[ $(cat "$root/etc/openwrt_version") == "$parent_rev" ]] || fail 'parent revision'
rg -qx 'mode=dhcp' "$root/etc/wave7-role-profile"
rg -Fxq "revision=$parent_rev" "$root/etc/wave7-role-profile"
# Use the same module-strip implementation/settings as the production image.
cp "$module" "$work/candidate.ko"
CROSS="$toolchain/aarch64-openwrt-linux-musl-" NO_RENAME=1 "$repo/scripts/strip-kmod.sh" "$work/candidate.ko"
for field in name vermagic depends import_ns license alias; do
  diff -u <(modinfo -F "$field" "$root/$rel" | sort) <(modinfo -F "$field" "$work/candidate.ko" | sort) || fail "module $field"
done
imports() { readelf -Ws "$1" | awk '$7=="UND" && $8!="" {print $8}' | LC_ALL=C sort -u; }
diff -u <(imports "$root/$rel") <(imports "$work/candidate.ko") || fail 'undefined symbol delta'
readelf -h "$work/candidate.ko" | rg -q 'Machine:.*AArch64'
strings "$work/candidate.ko" | rg 'SerDes CPU port %d corrupt-only ingress:' >/dev/null
if [[ $variant == native ]]; then
  strings "$work/candidate.ko" | rg -F 'trying stock-derived recovery pulse' >/dev/null
  strings "$work/candidate.ko" | rg -F 'SerDes recovery pulse completed' >/dev/null
fi
stripped_sha=$(digest "$work/candidate.ko")
cat "$work/candidate.ko" > "$root/$rel"
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
printf 'trial_kernel_patch_commit=%s\ntrial_module_sha256=%s\n' "$patch_commit" "$stripped_sha" >> "$m"
chmod --reference="$work/orig/etc/wave7-role-profile" "$m"
sh -c '. "$1"; wave7_ap_check_image "$2"' sh "$root/lib/wave7/overlay-reset.sh" "$root"
# The exact six-file delta is the entire experiment.
rsync -aincO --delete --out-format='%n' "$work/orig/" "$root/" | LC_ALL=C sort > "$work/delta"
printf '%s\n' etc/banner etc/openwrt_release etc/openwrt_version etc/wave7-role-profile "$rel" usr/lib/os-release | LC_ALL=C sort > "$work/want"
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
image="$work/publish/wave7-$image_kind-dhcp-guard8-sysupgrade.bin"
sh "$repo/scripts/sysupgrade-tar.sh" --board acer_wave7 --kernel "$work/kernel.itb" --rootfs "$work/new.sq" "$image"
jq --arg rev "$new_rev" --arg parent "$parent_sha" --arg module "$stripped_sha" --arg patch "$patch_commit"   '.version.revision=$rev | .wave7_parent_image_sha256=$parent | .wave7_trial_module_sha256=$module | .wave7_trial_kernel_patch_commit=$patch' "$work/old-metadata.json" > "$work/metadata"
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
kernel_patch_commit=$patch_commit
kernel_sha256=$kernel_sha
original_module_sha256=$old_module_sha
unstripped_candidate_sha256=$module_sha
module_sha256=$stripped_sha
module_intree=$(modinfo -F intree "$work/candidate.ko")
module_abi_imports=identical
root_delta=module_and_five_identity_files
root_modes_owners=identical
root_roundtrip=identical
radio_firmware_files=46_sha256_verified
image_sha256=$(digest "$image")
REPORT
(cd "$work/publish"; sha256sum ./*sysupgrade.bin > SHA256SUMS)
mv "$work/publish" "$out"
echo TRUNK_IMAGE_OFFLINE_PASS
cat "$out/report.txt"
