#!/usr/bin/env bash
# Wyse-only October 2026 MT7925 firmware comparison. The package and the
# installed ROC-repair module are never overwritten.
set -Eeuo pipefail
[[ $(id -un) == jan && $# == 1 && ( $1 == --install || $1 == --restore || $1 == --check ) ]] || exit 2
kver=7.4.0-rc1-2-cachyos-rc
src=/home/jan/firmware/wave7/kernel-tests/mt7925-firmware-ab/20261016
base=mediatek/mt7925
dest=/usr/lib/firmware/updates/$kver/$base
old=/usr/lib/firmware/$base
names=(WIFI_MT7925_PATCH_MCU_1_1_hdr.bin WIFI_RAM_CODE_MT7925_1_1.bin)
newsha=(67ff85f1a39d1a100a51abd8e2a26edd2f198d7052514b6b8981948b231e5016 329c0e27f780550789e4eba47452731b1723f69f9e67f525d0e50bf3cd2978ac)
oldsha=(8eb46014d2a6b4124472eee7476d995008a6f40b1daffef87eb42f30d98699e1 23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120)
hash() { sha256sum "$1" | cut -d' ' -f1; }
[[ $(uname -r) == "$kver" &&
   $(cat /sys/module/mt7925_common/srcversion) == DB4C3E1671DC2EA009803A0 &&
   $(cat /sys/class/net/wlp2s0/device/vendor) == 0x14c3 &&
   $(cat /sys/class/net/wlp2s0/device/device) == 0x7925 &&
   -z $(cat /sys/module/firmware_class/parameters/path) ]]
ip -4 route get 10.1.0.2 | grep -Fq 'dev eno1 '
[[ $(nmcli -g GENERAL.STATE device show wlp2s0) == '30 (disconnected)' &&
   $(nmcli -g connection.autoconnect connection show Wave7-MLO-Lab) == no ]]
for i in "${!names[@]}"; do
    n=${names[$i]}
    [[ $(zstd -dc "$old/$n.zst" | sha256sum | cut -d' ' -f1) == "${oldsha[$i]}" ]]
done
if [[ $1 == --check ]]; then
    printf 'boot=%s kernel=%s\n' "$(cat /proc/sys/kernel/random/boot_id)" "$(uname -r)"
    journalctl -k -b --no-pager | rg 'mt7925e.*(HW/SW Version|WM Firmware Version)'
    for i in "${!names[@]}"; do
        n=${names[$i]}
        if [[ -f $dest/$n ]]; then
            [[ $(hash "$dest/$n") == "${newsha[$i]}" ]]
            printf '%s override=%s\n' "$n" "${newsha[$i]}"
        else
            printf '%s package=%s\n' "$n" "${oldsha[$i]}"
        fi
    done
    exit
fi
if [[ $1 == --restore ]]; then
    # Only remove our verified files, never a foreign override.
    for i in "${!names[@]}"; do
        n=${names[$i]}
        [[ -f $dest/$n && ! -L $dest/$n && $(hash "$dest/$n") == "${newsha[$i]}" ]]
    done
    sudo -n rm -- "$dest/${names[0]}" "$dest/${names[1]}"
    sudo -n rmdir "$dest" "$dest/.." "$dest/../.." /usr/lib/firmware/updates
    echo "MT7925_AUGUST_RESTORED_ON_DISK reboot_required"
    exit
fi
# Refuse to modify existing unrelated override trees or use an early initramfs
# that would silently select a different firmware version.
[[ ! -e /usr/lib/firmware/updates && ! -L /usr/lib/firmware/updates ]]
if lsinitcpio -l "/boot/initramfs-linux-cachyos-rc.img" | rg -q 'mt7925|mt76|firmware/updates'; then
    echo "Unexpected early-loaded wireless module/firmware" >&2
    exit 3
fi
for i in "${!names[@]}"; do
    [[ $(hash "$src/${names[$i]}") == "${newsha[$i]}" ]]
done
created=0
cleanup() {
    local rc=$?
    trap - EXIT
    if (( rc != 0 && created )); then
        for n in "${names[@]}"; do
            if [[ -f $dest/$n && ! -L $dest/$n ]]; then
                sudo -n rm -- "$dest/$n"
            fi
        done
        sudo -n rmdir "$dest" "$dest/.." "$dest/../.." /usr/lib/firmware/updates || :
    fi
    exit "$rc"
}
trap cleanup EXIT
created=1
sudo -n install -d -m 0755 "$dest"
for i in "${!names[@]}"; do
    n=${names[$i]}
    sudo -n install -m 0644 "$src/$n" "$dest/$n"
    [[ $(hash "$dest/$n") == "${newsha[$i]}" ]]
done
echo "MT7925_OCTOBER_STAGED reboot_required"
