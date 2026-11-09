#!/usr/bin/env bash
# Build a Wave 7 vendor-format NAND OTA from a normal OpenWrt sysupgrade tar.
# All vendor-only inputs remain outside the Git tree.
set -euo pipefail
umask 077

if (( $# != 3 )); then
    echo "Usage: $0 OPENWRT_SYSUPGRADE_TAR VENDOR_ASSET_DIR NEW_OUTPUT_DIR" >&2
    exit 2
fi

source_tar=$(realpath -e -- "$1")
vendor=$(realpath -e -- "$2")
output=$3
if [[ -e "$output" ]]; then
    echo "Refusing existing output directory: $output" >&2
    exit 2
fi

stock="$vendor/TA_P1.1.1_V1.01.000067_5312_NB_BE6400_20260530.bin"
wifi="$vendor/extracted-ubi-067/ubi-root.img/img-2040351930_vol-wifi_fw.ubifs"
flash="$vendor/work/flash.scr"
tools=$(realpath -e -- "$vendor/../.tools/root/usr/bin")
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
unsquashfs="$repo/staging_dir/host/bin/unsquashfs4"
for file in "$source_tar" "$stock" "$wifi" "$flash" "$vendor/fitpad_vendor.py"; do
    [[ -s $file ]] || { echo "Missing input: $file" >&2; exit 2; }
done
for tool in ubinize mkimage dumpimage; do
    [[ -x $tools/$tool ]] || { echo "Missing tool: $tools/$tool" >&2; exit 2; }
done
[[ -x $unsquashfs ]] || { echo "Missing host unsquashfs: $unsquashfs" >&2; exit 2; }

mkdir -p -- "$output"
output=$(realpath -e -- "$output")
work="$output/.pack-work"
mkdir -- "$work"
trap 'rm -rf -- "$work"' EXIT

tar -xOf "$source_tar" sysupgrade-acer_wave7/kernel > "$work/kernel.itb"
tar -xOf "$source_tar" sysupgrade-acer_wave7/root > "$work/root.squashfs"
cp -- "$flash" "$work/flash.scr"

# Validate the *normal* (non-initramfs) FIT and the actual OpenWrt root.
"$tools/mkimage" -l "$work/kernel.itb" > "$work/kernel-fit.txt"
if rg -q '(Type:[[:space:]]+RAMDisk|with-initrd)' "$work/kernel-fit.txt"; then
    echo "Refusing initramfs FIT in NAND production image" >&2
    exit 2
fi
"$unsquashfs" -s "$work/root.squashfs" > "$work/rootfs-info.txt"
rootbytes=$(stat -c%s "$work/root.squashfs")
kernelbytes=$(stat -c%s "$work/kernel.itb")
(( rootbytes > 0 && rootbytes <= 29204480 ))
(( kernelbytes > 0 && kernelbytes < 71434240 ))
# Qualcomm 2KiB-page NAND, 128KiB PEB, 126,976-byte UBI logical blocks.
leb=126976
peb=131072
kernel_pebs=$(( (kernelbytes + leb - 1) / leb ))
kernel_reserved=$((kernel_pebs + 4))
(( kernel_reserved >= 50 )) || kernel_reserved=50
(( 87 + kernel_reserved + 230 <= 500 )) || {
    echo 'UBI reserved volume space exceeds physical rootfs envelope' >&2
    exit 2
}

# The A/B bootloader expects these three exact volume IDs and names.
# The Wi-Fi firmware stays the known-good vendor blob; ubi_rootfs MUST
# be the supplied OpenWrt SquashFS, never the stock/vendor root.
cat > "$work/ubinize.cfg" <<CFG
[wifi_fw]
mode=ubi
image=$wifi
vol_id=0
vol_type=static
vol_name=wifi_fw
vol_size=11046912
vol_alignment=1

[kernel]
mode=ubi
image=$work/kernel.itb
vol_id=1
vol_type=static
vol_name=kernel
vol_size=$((kernel_reserved * leb))
vol_alignment=1

[ubi_rootfs]
mode=ubi
image=$work/root.squashfs
vol_id=2
vol_type=dynamic
vol_name=ubi_rootfs
vol_size=29204480
vol_alignment=1
CFG

"$tools/ubinize" -o "$work/rootfs.ubi" -m 2048 -p "$peb" -s 2048 \
    -Q 2040351930 "$work/ubinize.cfg"
ubibytes=$(stat -c%s "$work/rootfs.ubi")
(( ubibytes > 0 && ubibytes <= 71434240 && ubibytes % peb == 0 ))

cat > "$work/update.its" <<'ITS'
/dts-v1/;
/ {
    description = "Flashing nand 800 20000";
    images {
        script {
            description = "flash.scr";
            data = /incbin/("flash.scr");
            type = "script";
            arch = "arm";
            compression = "none";
            hash@1 { algo = "crc32"; };
        };
        ubi-26cc256673bb597e301857108aeb953eaba3182d {
            description = "openwrt-ipq53xx-ipq53xx_32-ubi-root.img";
            data = /incbin/("rootfs.ubi");
            type = "firmware";
            arch = "arm";
            compression = "none";
            hash@1 { algo = "crc32"; };
        };
    };
};
ITS
(
    cd "$work"
    SOURCE_DATE_EPOCH=1780147339 "$tools/mkimage" -f update.its update.fit > mkimage.log
    uv run --no-project python "$vendor/fitpad_vendor.py" update.fit 768
)
"$tools/dumpimage" -l "$work/update.fit" > "$work/ota-fit.txt"
rg -q 'Flashing nand 800 20000' "$work/ota-fit.txt"
rg -q 'ubi-26cc256673bb597e301857108aeb953eaba3182d' "$work/ota-fit.txt"

# Preserve the exact vendor TLV records preceding type 1 (the FIT payload).
# The known stock container has type-1 length field at offset 204 and
# payload starts at 220. MD5 covers bytes from offset 36 onwards.
magic=$(od -An -tx1 -j 220 -N4 "$stock" | tr -d '[:space:]')
[[ $magic == d00dfeed ]] || {
    echo "Unexpected vendor TLV FIT offset" >&2
    exit 2
}
payloadbytes=$(stat -c%s "$work/update.fit")
(( ${#payloadbytes} <= 16 ))
image="$output/wave7-nand-squashfs-vendor-ota.bin"
tmp="$work/ota-tlv.tmp"
printf '%032d' 0 > "$tmp"
dd if="$stock" bs=1 skip=32 count=172 status=none >> "$tmp"
printf '%-16s' "$payloadbytes" | tr ' ' '\000' >> "$tmp"
cat -- "$work/update.fit" >> "$tmp"
[[ $(stat -c%s "$tmp") == $((220+payloadbytes)) ]]
md5=$(tail -c +37 "$tmp" | md5sum | cut -d' ' -f1)
printf '%s' "$md5" | dd of="$tmp" bs=1 count=32 conv=notrunc status=none
[[ $(dd if="$tmp" bs=1 count=32 status=none) == "$md5" ]]
mv -f -- "$tmp" "$image"

# Publication manifest; artifacts in .pack-work are ephemeral.
{
    printf 'sysupgrade_sha256=%s\n' "$(sha256sum "$source_tar" | cut -d' ' -f1)"
    printf 'kernel_sha256=%s\n' "$(sha256sum "$work/kernel.itb" | cut -d' ' -f1)"
    printf 'kernel_bytes=%s\n' "$kernelbytes"
    printf 'openwrt_squashfs_sha256=%s\n' "$(sha256sum "$work/root.squashfs" | cut -d' ' -f1)"
    printf 'openwrt_squashfs_bytes=%s\n' "$rootbytes"
    printf 'kernel_ubi_reserved_pebs=%s\n' "$kernel_reserved"
    printf 'rootfs_ubi_image_bytes=%s\n' "$ubibytes"
    printf 'firmware_bytes=%s\n' "$(stat -c%s "$image")"
    printf 'firmware_sha256=%s\n' "$(sha256sum "$image" | cut -d' ' -f1)"
} > "$output/manifest.txt"
echo "WAVE7_NAND_SQUASHFS_OTA_BUILT"
cat "$output/manifest.txt"
