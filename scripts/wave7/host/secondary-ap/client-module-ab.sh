#!/usr/bin/env bash
# Exact Wyse lab kernel only; preserve the existing ROC-repaired override.
# Does not reboot or alter the NetworkManager profile.
set -Eeuo pipefail
[[ $(id -un) == jan && $# == 1 ]] || exit 2
kver=7.4.0-rc1-2-cachyos-rc
bundle=/home/jan/firmware/wave7/kernel-tests/mt7925-single-channel-split
dest=/usr/lib/modules/$kver/updates/mt7925/mt7925-common.ko
declare -A hashes=(
    [original]=546f70108a29c643d52cb35dfabc87dbaeb78847c57c657e0cf1b749d31920eb
    [baseline]=ef3332a9de5e212e4a79f13b7b8f021b3d15a489132f47884dfad40903c4f343
    [candidate]=bc4b790c90f196eb063b0d9605e3569d137069791fec9d192720962ffbf3c384
    [metadata]=e423dd7b34d8e038b7b1a229ae1f9d7af08a27ce7370ea55ad09540175e274b0
)
declare -A versions=(
    [original]=DB4C3E1671DC2EA009803A0
    [baseline]=DB4C3E1671DC2EA009803A0
    [candidate]=1FB10711FECFBF21CC8F072
    [metadata]=5505CE551C04266721B047A
)
hash() { sha256sum "$1" | cut -d' ' -f1; }
[[ $(uname -r) == "$kver" &&
   $(cat /sys/module/mt7925e/srcversion) == C1250959DB6A9D56BD392B9 &&
   $(cat /sys/class/net/wlp2s0/device/vendor) == 0x14c3 &&
   $(cat /sys/class/net/wlp2s0/device/device) == 0x7925 &&
   $(readlink -f "$(modinfo -n mt7925_common)") == "$dest" &&
   -f $dest && ! -L $dest &&
   $(nmcli -g GENERAL.STATE device show wlp2s0) == '30 (disconnected)' &&
   $(nmcli -g connection.autoconnect connection show Wave7-MLO-Lab) == no ]]
ip -4 route get 10.1.0.2 | grep -Fq 'dev eno1 '
instances=$(sudo -n ls /sys/kernel/tracing/instances)
[[ -z $instances ]]
[[ ! -e /usr/lib/firmware/updates ]]
if lsinitcpio -l "/boot/initramfs-linux-cachyos-rc.img" | grep -Eq 'mt7925|mt76'; then
    echo "Unexpected early-loaded Wi-Fi module" >&2
    exit 3
fi
for name in original baseline candidate metadata; do
    if [[ $name == metadata && ! -f $bundle/$name.ko ]]; then continue; fi
    [[ $(hash "$bundle/$name.ko") == "${hashes[$name]}" &&
       $(modinfo -F srcversion "$bundle/$name.ko") == "${versions[$name]}" &&
       $(modinfo -F vermagic "$bundle/$name.ko") == "$kver SMP preempt mod_unload " ]]
done
current=''
for name in original baseline candidate metadata; do
    if [[ $(hash "$dest") == "${hashes[$name]}" ]]; then current=$name; break; fi
done
[[ -n $current ]]
loaded=$(cat /sys/module/mt7925_common/srcversion)
case "$1" in
    --check)
        printf 'boot=%s installed=%s sha256=%s loaded_srcversion=%s\n' "$(cat /proc/sys/kernel/random/boot_id)" "$current" "${hashes[$current]}" "$loaded"
        [[ $loaded == "${versions[$current]}" ]]
        journalctl -k -b --no-pager | grep -E 'mt7925e.*(HW/SW Version|WM Firmware Version)'
        exit
        ;;
    --stage-baseline) [[ $current == original && $loaded == "${versions[original]}" ]]; next=baseline ;;
    --stage-nosplit) [[ $current == baseline && $loaded == "${versions[baseline]}" ]]; next=candidate ;;
    --stage-metadata) [[ $current == original && -f $bundle/metadata.ko && $loaded == "${versions[original]}" ]]; next=metadata ;;
    --restore) [[ $current == baseline || $current == candidate || $current == metadata ]]; next=original ;;
    *) exit 2 ;;
esac
[[ $loaded == "${versions[$current]}" ]]
# The original module is retained in a checksum-identified bundle.
# Apply the replacement atomically under the existing version-local override.
tmp="$dest.wave7-ab-new"
[[ ! -e $tmp && ! -L $tmp ]]
changed=0
cleanup() {
    local rc=$?
    trap - EXIT
    if (( rc != 0 )); then
        if (( changed )); then
            sudo -n install -m 0644 "$bundle/$current.ko" "$tmp"
            sudo -n mv -T "$tmp" "$dest"
            sudo -n depmod -a "$kver"
        elif [[ -f $tmp && ! -L $tmp ]]; then
            sudo -n rm -- "$tmp"
        fi
    fi
    exit "$rc"
}
trap cleanup EXIT
sudo -n install -m 0644 "$bundle/$next.ko" "$tmp"
[[ $(hash "$tmp") == "${hashes[$next]}" ]]
sudo -n mv -T "$tmp" "$dest"
changed=1
sudo -n depmod -a "$kver"
[[ $(hash "$dest") == "${hashes[$next]}" &&
   $(readlink -f "$(modinfo -n mt7925_common)") == "$dest" &&
   $(modinfo -F srcversion mt7925_common) == "${versions[$next]}" ]]
printf 'MT7925_MODULE_STAGED previous=%s next=%s sha256=%s reboot_required\n' "$current" "$next" "${hashes[$next]}"
