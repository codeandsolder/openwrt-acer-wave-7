#!/usr/bin/env bash
# Derive 0497 from the exact approved 0491 secondary AP.
# Replace only the FIT, PCS module and five root identity files.
set -euo pipefail
umask 077
[[ $# == 4 ]] || { echo 'usage: build-trial-image.sh PARENT VERIFIED_KERNEL ACCEPTED_BUILD OUTPUT_DIR' >&2; exit 2; }
parent=$(realpath -e "$1")
verified=$(realpath -e "$2")
accepted=$(realpath -e "$3")
raw="$verified/candidate.Image"
out=$(realpath -m "$4")
repo=$(cd "$(dirname "$0")/../../../.." && pwd)
prod=/home/jan/projects/wave7-prod-integrated
tools="$prod/staging_dir/host/bin"
parent_sha=3ad42acf6fd9765dc9f92f937e5472bb2e19987d92896ce3e8994810e22badd9
parent_rev=r0+38346-0418bb7af2-ap-dhcp-guard8
kernel_sha=c289598628e75f7a603ec127dbb5cbd1fdcf6128ba15cea6c4fe9b0aa0232b8e
phy_commit=0418bb7af25d13406bb896696eb78541ccd2aa00
instant_commit=44d12aa1f75285c4b5209d227da200227d96588a
worker_commit=3688c57cd341560fd73365916b68a76465ef2f8a
patch_commit=ef7d41f2b18457e9576d8ee7a2aa4d6f549ec7a8
parent_pcs=74bd3fddd9e35f543100073a4f7a85ebfe7aca503e5c48191dd3c2ee8190b473
parent_ppe=1ff7a7d590f7ef45bdaf794a3e5dfeb66ffe9a0f9eed24cf4dd8df5a7c0b5fc0
new_rev="r0+38346-${patch_commit:0:10}-ap-dhcp-guard8"
stripped_sha=ff6b4c93d9ce2cb71b2b8dfd0053df70cc4a3ad4960bd49c099eceea85d7fe91
digest() { sha256sum "$1" | cut -d' ' -f1; }
fail() { echo "PHY_IMAGE_FAIL $*" >&2; exit 1; }
[[ ! -e $out && -d $(dirname "$out") ]] || fail 'output must not exist'
[[ -z $(git -C "$repo" status --porcelain) ]] || fail 'dirty source'
git -C "$repo" merge-base --is-ancestor "$patch_commit" HEAD
builder=$(git -C "$repo" rev-parse HEAD)
[[ $(digest "$parent") == "$parent_sha" ]] || fail 'parent digest'
(cd "$verified"; sha256sum -c SHA256SUMS)
report="$verified/report.json"
worker_patch="$repo/target/linux/qualcommbe/patches-6.18/0496-net-phy-qca8081-test-independent-fifo-poll.patch"
[[ $(digest "$worker_patch") == "$(jq -er .worker_patch_sha256 "$report")" ]] || fail "worker patch digest"
instant_patch="$repo/target/linux/qualcommbe/patches-6.18/0495-net-phy-qca8081-test-instantaneous-fifo-link.patch"
[[ $(digest "$raw") == "$(jq -er .candidate_raw_sha256 "$report")" &&
   $(digest "$instant_patch") == "$(jq -er .patch_sha256 "$report")" ]] || fail 'verified kernel digest'
jq -e '.baseline_normalized == true and .baseline_raw_sha256 == "927351279da9ca3fd29891d8a6a2b1e95fba5a7497a086711d09665985ca0950" and .config_sha256 == "541c909b5c40aeb38d418d0f2b1fbd1e166b2dc2ac357d420b50958df1615987" and .exports_sha256 == "e850879b87726135c25faf20f095a640563b3e5883a67aa2708d0d0aa1ea0c81" and .instant_fifo_fixture_pass == true and .instant_baseline_normalized == true and .instant_baseline_sha256 == "df864a78bf864f56e609320c3c8f08fbbd6fecef3722a5d6fbae2bce7f747eef" and .worker_fixture_pass == true and .before == .after and .after.nss_cc_parent_data_1 == [7,2,4,3,1,0] and .after.nss_cc_parent_data_2 == [7,2,6,5,1,0]' "$report" >/dev/null
down_patch="$repo/target/linux/qualcommbe/patches-6.18/0497-net-phy-pcs-wave7-test-warm-down-mode-prepare.patch"
[[ $(digest "$down_patch") == "$(jq -er .down_mode_patch_sha256 "$report")" ]] || fail 'down-mode patch digest'
pcs_sha=$(jq -er .pcs_candidate_sha256 "$report")
[[ $pcs_sha =~ ^[0-9a-f]{64}$ && $pcs_sha != "$parent_pcs" && $(digest "$verified/pcs-qcom-ipq9574.ko") == "$pcs_sha" ]] || fail 'candidate PCS digest'
jq -e --arg pcs "$parent_pcs" '.predecessor_proofs_verified == {"0495":"e72b3e51f28bb8807b27cf2fdaed3d8c5421f06838dd71daf078fb8a9eb69129","0496":"179b7b1a4f04162a097d7a3075b1805e837ca2409557602d0a816a22426a0fa3"} and .worker_baseline_normalized == true and .worker_baseline_sha256 == "5489c8ce35ec79a551c58054fd50e691682751893612ed4682c007f56f16d09c" and .down_mode_fixture_pass == true and .pcs_baseline_sha256 == $pcs and .pcs_baseline_byte_identical == true and .pcs_module_metadata_identical == true and .kernel_and_module_exports_identical == true' "$report" >/dev/null
git -C "$repo" merge-base --is-ancestor "$patch_commit" "$(jq -er .builder_commit "$report")"
git -C "$repo" merge-base --is-ancestor "$(jq -er .builder_commit "$report")" HEAD
[[ $(tar xOf "$parent" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || fail 'board'
work=$(mktemp -d "$(dirname "$out")/.wave7-phy.XXXXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir "$work/publish"
fit="$work/candidate.itb"
"$tools/lzma" e "$raw" "$work/candidate.lzma" -lc1 -lp2 -pb2
# Use the archived exact FIT template, replacing its data paths only.
sed -e "s|$accepted/fit/candidate.lzma|$work/candidate.lzma|" \
    -e "s|$accepted/fit/parent.dtb|$work/parent.dtb|" "$accepted/fit/candidate.its" > "$work/candidate.its"
[[ $(digest "$accepted/fit/parent.dtb") == 5eb62be61f9551eb44bb1b40622f2c77d515192da8fa3efe71430c61e90c6302 ]] || fail 'archived DTB digest'
cp "$accepted/fit/parent.dtb" "$work/parent.dtb"
rg -Fq "$work/candidate.lzma" "$work/candidate.its"
rg -Fq "$work/parent.dtb" "$work/candidate.its"
PATH="$tools:$PATH" "$tools/mkimage" -f "$work/candidate.its" "$fit" > "$work/mkimage.log"
fit_sha=$(digest "$fit")
cp "$report" "$work/publish/kernel-verification.json"
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
pcs_rel=lib/modules/6.18.60/pcs-qcom-ipq9574.ko
ppe_rel=lib/modules/6.18.60/qcom-ppe.ko
[[ $(digest "$root/$pcs_rel") == "$parent_pcs" && $(digest "$root/$ppe_rel") == "$parent_ppe" ]] || fail 'parent PCS/PPE identity'
cat "$verified/pcs-qcom-ipq9574.ko" > "$root/$pcs_rel"
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
rg -Fxq "trial_phy_kernel_patch_commit=$phy_commit" "$m" || fail 'parent PHY patch identity'
rg -Fxq "trial_fit_sha256=$kernel_sha" "$m" || fail 'parent FIT identity'
sed -i "s/^trial_fit_sha256=.*/trial_fit_sha256=$fit_sha/" "$m"
printf 'trial_instant_fifo_patch_commit=%s\ntrial_fifo_worker_patch_commit=%s\ntrial_down_mode_patch_commit=%s\ntrial_pcs_sha256=%s\ntrial_ppe_sha256=%s\n' "$instant_commit" "$worker_commit" "$patch_commit" "$pcs_sha" "$parent_ppe" >> "$m"
chmod --reference="$work/orig/etc/wave7-role-profile" "$m"
sh -c '. "$1"; wave7_ap_check_image "$2"' sh "$root/lib/wave7/overlay-reset.sh" "$root"
# The PCS module and five root identity files are the entire root delta.
rsync -aincO --delete --out-format='%n' "$work/orig/" "$root/" | LC_ALL=C sort > "$work/delta"
printf '%s\n' etc/banner etc/openwrt_release etc/openwrt_version etc/wave7-role-profile usr/lib/os-release "$pcs_rel" | LC_ALL=C sort > "$work/want"
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
[[ $(digest "$work/roundtrip/$rel") == "$stripped_sha" && $(digest "$work/roundtrip/$pcs_rel") == "$pcs_sha" && $(digest "$work/roundtrip/$ppe_rel") == "$parent_ppe" ]] || fail 'roundtrip module'
image="$work/publish/wave7-down-mode-dhcp-guard8-sysupgrade.bin"
sh "$repo/scripts/sysupgrade-tar.sh" --board acer_wave7 --kernel "$work/kernel.itb" --rootfs "$work/new.sq" "$image"
jq --arg rev "$new_rev" --arg parent "$parent_sha" --arg fit "$fit_sha" --arg patch "$worker_commit" --arg instant "$instant_commit" --arg down "$patch_commit" --arg pcs "$pcs_sha" --arg ppe "$parent_ppe"   '.version.revision=$rev | .wave7_parent_image_sha256=$parent | .wave7_trial_instant_fifo_patch_commit=$instant | .wave7_trial_fifo_worker_patch_commit=$patch | .wave7_trial_down_mode_patch_commit=$down | .wave7_trial_pcs_sha256=$pcs | .wave7_trial_ppe_sha256=$ppe | .wave7_trial_fit_sha256=$fit' "$work/old-metadata.json" > "$work/metadata"
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
phy_kernel_patch_commit=$phy_commit
instant_fifo_patch_commit=$instant_commit
fifo_worker_patch_commit=$worker_commit
down_mode_patch_commit=$patch_commit
pcs_sha256=$pcs_sha
ppe_sha256=$parent_ppe
parent_kernel_sha256=$kernel_sha
kernel_sha256=$fit_sha
kernel_payload_sha256=$(digest "$raw")
native_switch_module_sha256=$stripped_sha
root_delta=one_pcs_module_five_identity_files
root_modes_owners=identical
root_roundtrip=identical
radio_firmware_files=46_sha256_verified
image_sha256=$(digest "$image")
REPORT
cp "$work/delta" "$work/publish/root-delta.txt"
(cd "$work/publish"; sha256sum ./*sysupgrade.bin report.txt kernel-verification.json fit-verification.txt root-delta.txt > SHA256SUMS)
mv "$work/publish" "$out"
echo DOWN_MODE_IMAGE_OFFLINE_PASS
cat "$out/report.txt"
