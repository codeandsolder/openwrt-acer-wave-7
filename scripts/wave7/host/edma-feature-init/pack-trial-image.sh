#!/usr/bin/env bash
# Exact force-order parent, identical FIT, only PPE and five identity files.
set -euo pipefail
umask 077
[[ $# == 3 ]] || { echo 'usage: pack-trial-image.sh PARENT VERIFIED_MODULE_DIR OUTPUT_DIR' >&2; exit 2; }
parent=$(realpath -e "$1")
modules=$(realpath -e "$2")
out=$(realpath -m "$3")
repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
prod=/home/jan/projects/wave7-prod-integrated
tools="$prod/staging_dir/host/bin"
parent_sha=eeeb7057cf93a0a9babbb7941ba086a8cc5519e8f8a8b14b680744af0f2f4bfd
parent_rev=r0+38346-b9db617b17-ap-dhcp-guard8
kernel_sha=c289598628e75f7a603ec127dbb5cbd1fdcf6128ba15cea6c4fe9b0aa0232b8e
patch_commit=88d0753b1b952e9707004585bcbed79fba9fd5f7
switch_sha=bea25a2aafd1bc236740ad089bc9500b4f064034fd11cec959abd9bb208d322e
parent_pcs=6e1293e83985caf4eb352e163036d050de5eb2d3f4272ca8a2a71667833658bf
parent_ppe=1ff7a7d590f7ef45bdaf794a3e5dfeb66ffe9a0f9eed24cf4dd8df5a7c0b5fc0
digest() { sha256sum "$1" | cut -d' ' -f1; }
fail() { echo "EDMA_FEATURE_INIT_IMAGE_FAIL $*" >&2; exit 1; }
[[ ! -e $out && -d $(dirname "$out") ]] || fail 'output must not exist'
[[ -z $(git -C "$repo" status --porcelain) ]] || fail 'dirty source'
git -C "$repo" merge-base --is-ancestor "$patch_commit" HEAD
builder=$(git -C "$repo" rev-parse HEAD)
[[ $(digest "$parent") == "$parent_sha" ]] || fail 'parent digest'
(cd "$modules"; sha256sum -c SHA256SUMS)
report="$modules/report.json"
[[ $(jq -er .parent_image_sha256 "$report") == "$parent_sha" ]] || fail 'module parent'
[[ $(jq -er .baseline_byte_identical "$report") == true ]] || fail 'baseline parity'
module_builder=$(jq -er .builder_commit "$report")
[[ $module_builder =~ ^[0-9a-f]{40}$ ]] || fail 'module builder'
git -C "$repo" merge-base --is-ancestor "$patch_commit" "$module_builder"
git -C "$repo" merge-base --is-ancestor "$module_builder" HEAD
patch=target/linux/qualcommbe/patches-6.18/0499-net-ethernet-qualcomm-edma-init-features-before-register.patch
[[ $(digest "$repo/$patch") == "$(jq -er .patch_sha256 "$report")" ]] || fail 'patch provenance'
experiment=$(jq -er .experiment "$report")
[[ $experiment == edma-dsa-feature-check ]] || fail 'wrong experiment'
[[ $(jq -er .module_exports_identical "$report") == true &&
   $(jq -er .module_metadata_identical "$report") == true &&
   $(jq -er .fixture_pass "$report") == true &&
   $(jq -er .accepted_ppe_sha256 "$report") == "$parent_ppe" &&
   $(jq -er .unchanged_pcs_sha256 "$report") == "$parent_pcs" &&
   $(jq -er .nand_config_sha256 "$report") == 541c909b5c40aeb38d418d0f2b1fbd1e166b2dc2ac357d420b50958df1615987 &&
   $(jq -er .kernel_exports_sha256 "$report") == e850879b87726135c25faf20f095a640563b3e5883a67aa2708d0d0aa1ea0c81 ]] || fail 'module verification'
new_rev="r0+38346-${patch_commit:0:10}-ap-dhcp-guard8"
pcs_sha=$parent_pcs
ppe_sha=$(jq -er .candidate_ppe_sha256 "$report")
[[ $ppe_sha =~ ^[0-9a-f]{64}$ && $ppe_sha != "$parent_ppe" ]] || fail 'candidate digest'
[[ $(digest "$modules/modules/qcom-ppe.ko") == "$ppe_sha" ]] || fail 'candidate module digest'
[[ $(tar xOf "$parent" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || fail 'board'
work=$(mktemp -d "$(dirname "$out")/.wave7-edma-feature-init.XXXXXXXX")
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
rel=lib/modules/6.18.60
[[ $(digest "$root/$rel/rtl8365mb.ko") == "$switch_sha" ]] || fail 'native switch module identity'
[[ $(digest "$root/$rel/pcs-qcom-ipq9574.ko") == "$parent_pcs" &&
   $(digest "$root/$rel/qcom-ppe.ko") == "$parent_ppe" ]] || fail 'parent module identity'
cat "$modules/modules/qcom-ppe.ko" > "$root/$rel/qcom-ppe.ko"
[[ $(cat "$root/etc/openwrt_version") == "$parent_rev" ]] || fail 'parent revision'
rg -qx 'mode=dhcp' "$root/etc/wave7-role-profile"
rg -Fxq "revision=$parent_rev" "$root/etc/wave7-role-profile"
rg -Fxq "trial_fit_sha256=$kernel_sha" "$root/etc/wave7-role-profile"
for f in etc/openwrt_version etc/openwrt_release usr/lib/os-release etc/banner; do
  rg -Fq "$parent_rev" "$root/$f" || fail "revision missing: $f"
  sed -i "s/$parent_rev/$new_rev/g" "$root/$f"
done
m="$root/etc/wave7-role-profile"
sed -i -e "s/^source_revision=.*/source_revision=$parent_rev/" \
       -e "s/^revision=.*/revision=$new_rev/" \
       -e "s/^builder_commit=.*/builder_commit=$builder/" \
       -e "s/^base_image_sha256=.*/base_image_sha256=$parent_sha/" "$m"
rg -Fxq "trial_ppe_sha256=$parent_ppe" "$m"
sed -i "s/^trial_ppe_sha256=.*/trial_ppe_sha256=$ppe_sha/" "$m"
printf 'trial_edma_feature_init_patch_commit=%s\n' "$patch_commit" >> "$m"
chmod --reference="$work/orig/etc/wave7-role-profile" "$m"
sh -c '. "$1"; wave7_ap_check_image "$2"' sh "$root/lib/wave7/overlay-reset.sh" "$root"
rsync -aincO --delete --out-format='%n' "$work/orig/" "$root/" | LC_ALL=C sort > "$work/delta"
printf '%s\n' etc/banner etc/openwrt_release etc/openwrt_version etc/wave7-role-profile usr/lib/os-release "$rel/qcom-ppe.ko" | LC_ALL=C sort > "$work/want"
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
[[ $(digest "$work/roundtrip/$rel/rtl8365mb.ko") == "$switch_sha" &&
   $(digest "$work/roundtrip/$rel/pcs-qcom-ipq9574.ko") == "$pcs_sha" &&
   $(digest "$work/roundtrip/$rel/qcom-ppe.ko") == "$ppe_sha" ]] || fail 'roundtrip module'
image="$work/publish/wave7-${experiment}-dhcp-guard8-sysupgrade.bin"
sh "$repo/scripts/sysupgrade-tar.sh" --board acer_wave7 --kernel "$work/kernel.itb" --rootfs "$work/new.sq" "$image"
jq --arg rev "$new_rev" --arg parent "$parent_sha" --arg patch "$patch_commit" --arg pcs "$pcs_sha" --arg ppe "$ppe_sha" \
  '.version.revision=$rev | .wave7_parent_image_sha256=$parent | .wave7_trial_edma_feature_init_patch_commit=$patch | .wave7_trial_pcs_sha256=$pcs | .wave7_trial_ppe_sha256=$ppe' "$work/old-metadata.json" > "$work/metadata"
"$tools/fwtool" -I "$work/metadata" "$image"
"$tools/fwtool" -i "$work/verified-metadata" "$image"
diff -u <(jq -S . "$work/metadata") <(jq -S . "$work/verified-metadata")
cmp "$work/kernel.itb" <(tar xOf "$image" sysupgrade-acer_wave7/kernel)
cmp -n "$(stat -c %s "$work/new.sq")" "$work/new.sq" <(tar xOf "$image" sysupgrade-acer_wave7/root)
[[ $(tar xOf "$image" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || fail 'packed board'
[[ $(stat -c %s "$image") -lt 30000000 ]] || fail 'packed size'
cat > "$work/publish/report.txt" <<REPORT
status=OFFLINE_VERIFIED
experiment=$experiment
parent_revision=$parent_rev
parent_sha256=$parent_sha
revision=$new_rev
builder_commit=$builder
module_builder_commit=$module_builder
edma_feature_init_patch_commit=$patch_commit
kernel_sha256=$kernel_sha
kernel_fit=BYTE_IDENTICAL_PARENT
native_switch_module_sha256=$switch_sha
pcs_sha256=$pcs_sha
ppe_sha256=$ppe_sha
root_delta=one_ppe_module_five_identity_files
root_modes_owners=identical
root_roundtrip=identical
radio_firmware_files=46_sha256_verified
image_sha256=$(digest "$image")
REPORT
cp "$work/delta" "$work/publish/root-delta.txt"
cp "$report" "$work/publish/module-build-report.json"
(cd "$work/publish"; sha256sum ./*sysupgrade.bin report.txt root-delta.txt module-build-report.json > SHA256SUMS)
mv "$work/publish" "$out"
echo EDMA_FEATURE_INIT_IMAGE_OFFLINE_PASS
cat "$out/report.txt"
