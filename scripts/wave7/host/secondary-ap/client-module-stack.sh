#!/usr/bin/env bash
# Live matched PCIe stack trials; no changes to installed modules/initramfs.
set -Eeuo pipefail
[[ $# == 2 && ( $(id -un) == jan || $EUID == 0 ) ]] || exit 2
variant=$1
[[ $variant == quota || $variant == upstream-base || $variant == upstream-prefix12 || $variant == upstream-prefix24 || $variant == upstream-mlo ]] || exit 2
action=$2
kver=7.4.0-rc1-2-cachyos-rc
bundle=/home/jan/firmware/wave7/kernel-tests/mt7925-single-channel-split/$variant
stage=/run/wave7-$variant-stack
timer=wave7-$variant-rollback.timer
modules=(mt76 mt76_connac_lib mt792x_lib mt7925_common mt7925e)
declare -A names=(
    [mt76]=mt76.ko
    [mt76_connac_lib]=mt76-connac-lib.ko
    [mt792x_lib]=mt792x-lib.ko
    [mt7925_common]=mt7925-common.ko
    [mt7925e]=mt7925e.ko
)
declare -A original_hash=(
    [mt76]=20c31e7c6ace30a613cd00fca9eb480809dc1d15db962d24a4d1ae44980a4e7d
    [mt76_connac_lib]=b06b4eb13743a352bae0ad9c52e59dee7ad68bd7fc405e34cb67279db00b8d16
    [mt792x_lib]=f5cc1fb4ad04d82002f817fdecae50dae39d8549b9eb6c50596142a3934ec120
    [mt7925_common]=546f70108a29c643d52cb35dfabc87dbaeb78847c57c657e0cf1b749d31920eb
    [mt7925e]=c5efe032e376f65d732a450b834ef4f7c31d679df54df6870ba5db0d040128b1
)
declare -A original_version=(
    [mt76]=D15DCBD555EF496E6A3289C
    [mt76_connac_lib]=28C58B8C1B27F42E194BA9E
    [mt792x_lib]=80A4F5B125A334C827CCD89
    [mt7925_common]=DB4C3E1671DC2EA009803A0
    [mt7925e]=C1250959DB6A9D56BD392B9
)
declare -A original_id=(
    [mt76]=93f5557bbb5672ab21596f86c86aaaa80d1b0984
    [mt76_connac_lib]=f1807a546ad9daedeeaba24e47318ec33a11bd17
    [mt792x_lib]=5645e041ffb7d3509557e24726492edd99c0dffc
    [mt7925_common]=a21f51d6bfde49340e3d05c4016d0395102caa69
    [mt7925e]=3322f96eed6473fb1aa3ee4100b9ef46092a0c21
)
case "$variant" in
quota)
declare -A candidate_hash=(
    [mt76]=05af6d762cf36e5109d9cff363ce764ae96b0703737d14022991ac64a0efbf60
    [mt76_connac_lib]=7bf307b342ec69f027a5fe9b3f6c92cc208f6fc3b09cf7e9a33d9f636c73d641
    [mt792x_lib]=77854efde3ab7d347d8c2022b23df915d58c9df005362b995d76c10c35891d08
    [mt7925_common]=4421685b5b07aac716cccf6f43113d324be55eb3427fc06e1c0c1a2e7f62f178
    [mt7925e]=ccc37f5d558e15b9f8912a0583d00c6bca344955aee53c34c8cfed30a5e48d9e
)
declare -A candidate_version=(
    [mt76]=24FD3CB8BD6EC4F8FF9B294
    [mt76_connac_lib]=9FEA98BF053467F9FB24EBD
    [mt792x_lib]=0F773A06E6A47065D1EAF20
    [mt7925_common]=E882C202FF34ABD6AFFEC2C
    [mt7925e]=71791C8DAD7FB01A84B3182
)
declare -A candidate_id=(
    [mt76]=5ce11fcdfddf16225e46e501f563d010951a8c03
    [mt76_connac_lib]=4010329d2479518ade6d7f0fd6aa620cd1ede997
    [mt792x_lib]=d55c01c189ab3fbd710539bef960cc317a1cfcfb
    [mt7925_common]=bdf64419ed55f334a370340944db19e6617c85bb
    [mt7925e]=c6db5ad30247861370b10ee8625cc511e8296f99
)
;;
upstream-base)
declare -A candidate_hash=(
    [mt76]=01d9c0b93eb61bf2259b005967f6fadd43718822c006df95613893c8e2a16fba
    [mt76_connac_lib]=f4d820123842237c338f8eafb93b8cf9d340ae38ad06dfe19c83edf8bc3bcb83
    [mt792x_lib]=cb5e396e3fa260206300ad5b51808aebadc70d0346ef011fcd88be10aba085c2
    [mt7925_common]=0f622c21070fd494304e10418eed9ca1d294ea06587f0097d9c1b1cee85a4215
    [mt7925e]=1fb8753ba3b989f722809ec0a7fee4a3afbbc6be724462cc831078466e27a0c8
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=8E0AFCBE21728971D1B12BD
    [mt792x_lib]=2FFD9248FB2CFA09C140033
    [mt7925_common]=2133CAC6AEA50398F57A5C6
    [mt7925e]=64076F735AF69D874943994
)
declare -A candidate_id=(
    [mt76]=72770fced7989400c0314046b03d00fb55fc8aa1
    [mt76_connac_lib]=748fbf5962be05a2bc223adc9f98899740be0451
    [mt792x_lib]=279286781fc7a2ef7f77974664c592eb23de9bb0
    [mt7925_common]=47874e23be3b7c5e71c2c38787df7da9bd054250
    [mt7925e]=94d57200722a856e04100ff9556a216f7a37ea24
)
;;
upstream-prefix12)
declare -A candidate_hash=(
    [mt76]=02763e1c5dcadd4b124be3532514c3dcb09d4716329e305a8c8e3fab7f700e49
    [mt76_connac_lib]=501bf569cd0e84c7b365b5629fd32248a842e8cce6f8e976f36aaf94ac677e92
    [mt792x_lib]=53a6518a24a1658732fd6ffe28eac39995f7e0b184da3e675ca11c491106619e
    [mt7925_common]=20f02f932eec876d5fe561c95987979263410102d3b3f07343ed9728d0c92e26
    [mt7925e]=df6b67be5b3a0ef12447ab3bfa43d2274aa39f9f9da670cf95719e1faa1bdb4b
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=1B9080F5C0CBA13F0F80B07
    [mt7925e]=A4B170554BA46F84100DE24
)
declare -A candidate_id=(
    [mt76]=531cda207c2ba2a03887062cae653e20ff1ae24e
    [mt76_connac_lib]=59f5ed570f7e6ff9ff70142c861c7193902a82e7
    [mt792x_lib]=66cf4ffdf8bbead0e21bbea22226a9db29994522
    [mt7925_common]=1c16532df29f7bc84d3ec0d936ae7a3ff446f061
    [mt7925e]=f7a07472d7e01e1d3adc7f40a870428e63ae6cfd
)
;;
upstream-prefix24)
declare -A candidate_hash=(
    [mt76]=f929e473d2eaefaa42beb2060906280f177a21bec22db07aa2079147697ab2ab
    [mt76_connac_lib]=3800b47c2e2c088f88bc4eed0dc3f1ccfc4ee07277b3f7caa59db46009b4e0b7
    [mt792x_lib]=afdb5842b0ba1256e8ad882aaf62a41723bed0dc3cfa3ea5d6a6c32692d6eb50
    [mt7925_common]=be1821cf31d44b780bcaa98c14b08e09004ae877c8a8b0ecea9ef40889ce78cd
    [mt7925e]=1b152364a21665c697b6e2f7f7c6582a27aa922ed7ea979ec62fe650aa2771f6
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=9FAF8F56A5317D3F0883990
    [mt7925e]=FBA0887DAE5E4E080B4761A
)
declare -A candidate_id=(
    [mt76]=81e0cffb11e04d485c3cca7d0cc98db861c7ddbd
    [mt76_connac_lib]=af4829695206e00797623d48ebd9288389820eaf
    [mt792x_lib]=570c3d1d44f134476ca846435477a6355be8a023
    [mt7925_common]=8761ca32f34a1294aa9e218c1b60242716122786
    [mt7925e]=0add8d2fa98cbdfaeef6b9522659be449a8fd3a7
)
;;
upstream-mlo)
declare -A candidate_hash=(
    [mt76]=c0c66bbdfeabd774ba2236c69bdec5c8e4bb3b37a4a54c629b41635bfa2baea5
    [mt76_connac_lib]=dcc942fdc3b0c3e26e25832b20b738e1bb5eed523675286d3e76e50561c073d9
    [mt792x_lib]=771a6caeabef3cf8b0cf22d2be51e89b51b076bf938895e41e6b129758d23e78
    [mt7925_common]=0ab5eceb65fade61650a3c32c6dff07af6b211b3283b4864bb89daaf39dc4f45
    [mt7925e]=7992986999d9cec7be3feb74a31279173a1bd21589a74695e0ee091b8c7d7db6
)
declare -A candidate_version=(
    [mt76]=DEF56EC1D966C3C1D7AC35A
    [mt76_connac_lib]=5BED2D7D2B4E7822BCF126C
    [mt792x_lib]=E646D7CFCCF4E8A2A319BEA
    [mt7925_common]=6B2DB0A319E60718A55A35B
    [mt7925e]=59C609541F7228695F13B8E
)
declare -A candidate_id=(
    [mt76]=a8291ddff22eadbb14b6f44d5200614f4db14b3d
    [mt76_connac_lib]=23ce263ab674f6005eaae7983db24cc4323f37a4
    [mt792x_lib]=2eb4ec10063d2f3b94713a2d54b34dfa2f78c633
    [mt7925_common]=279be35b30cf4b37b0597a22a08e63474e2b1bf2
    [mt7925e]=5ba0854aa38c909217516106f4f2df8a384a3906
)
;;
esac
declare -A holders=(
    [mt76]='mt76_connac_lib,mt7925_common,mt7925e,mt792x_lib'
    [mt76_connac_lib]='mt7925_common,mt7925e,mt792x_lib'
    [mt792x_lib]='mt7925_common,mt7925e'
    [mt7925_common]=mt7925e
    [mt7925e]=''
)
hash() { sha256sum "$1" | cut -d' ' -f1; }
note_id() {
    local note
    note=$(od -An -v -tx1 "/sys/module/$1/notes/.note.gnu.build-id" | tr -d ' \n')
    [[ $note =~ ^040000001400000003000000474e5500([0-9a-f]{40})$ ]]
    printf '%s' "${BASH_REMATCH[1]}"
}
scope() {
    [[ $(uname -r) == "$kver" && $(cat /proc/sys/kernel/hostname) == wifi7-lab &&
       $(cat /sys/bus/pci/devices/0000:02:00.0/vendor) == 0x14c3 &&
       $(cat /sys/bus/pci/devices/0000:02:00.0/device) == 0x7925 &&
       $(ip -4 route get 10.1.0.2) == *'dev eno1 src 10.1.0.221 '* &&
       $(nmcli -g connection.autoconnect connection show Wave7-MLO-Lab) == no ]]
}
interface_ready() {
    [[ $(readlink -f /sys/class/net/wlp2s0/device) == "$(readlink -f /sys/bus/pci/devices/0000:02:00.0)" &&
       $(basename "$(readlink -f /sys/bus/pci/devices/0000:02:00.0/driver)") == mt7925e &&
       $(nmcli -g GENERAL.STATE device show wlp2s0) == '30 (disconnected)' ]]
}
disk_original() {
    local name path
    for name in "${modules[@]}"; do
        path=$(modinfo -n "$name")
        [[ $(hash "$path") == "${original_hash[$name]}" &&
           $(modinfo -F srcversion "$path") == "${original_version[$name]}" ]]
        if [[ $name == mt7925_common ]]; then
            [[ $(readlink -f "$path") == /usr/lib/modules/"$kver"/updates/mt7925/mt7925-common.ko ]]
        else
            [[ $(readlink -f "$path") == /usr/lib/modules/"$kver"/kernel/drivers/net/wireless/mediatek/mt76/* ]]
        fi
    done
}
loaded_closure() {
    local variant=$1 name actual expected_version expected_id
    actual=$(awk '/^(mt76|mt792)/ {print $1}' /proc/modules | LC_ALL=C sort | paste -sd, -)
    [[ $actual == "$(printf '%s\n' "${modules[@]}" | LC_ALL=C sort | paste -sd, -)" ]]
    for name in "${modules[@]}"; do
        [[ $(find "/sys/module/$name/holders" -mindepth 1 -maxdepth 1 -printf '%f\n' |
              LC_ALL=C sort | paste -sd, -) == "${holders[$name]}" ]]
        if [[ $variant == original ]]; then
            expected_version=${original_version[$name]}
            expected_id=${original_id[$name]}
        else
            expected_version=${candidate_version[$name]}
            expected_id=${candidate_id[$name]}
        fi
        [[ $(cat "/sys/module/$name/srcversion") == "$expected_version" &&
           $(note_id "$name") == "$expected_id" ]]
        printf '%s srcversion=%s build_id=%s\n' "$name" "$expected_version" "$expected_id"
    done
}
candidate_files() {
    local dir=$1 name f
    for name in "${modules[@]}"; do
        f="$dir/${names[$name]}"
        [[ -f $f && ! -L $f &&
           $(hash "$f") == "${candidate_hash[$name]}" &&
           $(modinfo -F name "$f") == "$name" &&
           $(modinfo -F srcversion "$f") == "${candidate_version[$name]}" &&
           $(modinfo -F vermagic "$f") == "$kver SMP preempt mod_unload " &&
           $(llvm-readelf -n "$f" | awk '/Build ID:/ {print $3}') == "${candidate_id[$name]}" ]]
        printf 'candidate %s sha256=%s\n' "$name" "${candidate_hash[$name]}"
    done
}
check_original() {
    scope
    interface_ready
    disk_original
    loaded_closure original
    local other
    for other in quota upstream-base upstream-prefix12 upstream-prefix24 upstream-mlo; do
        [[ ! -e /run/wave7-$other-stack ]]
        if systemctl is-active --quiet "wave7-$other-rollback.timer"; then return 1; fi
    done
    printf 'STACK_ORIGINAL_PASS boot=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
}
check_candidate() {
    scope
    interface_ready
    disk_original
    [[ $(stat -c '%u:%g:%a' "$stage") == 0:0:755 &&
       $(cat "$stage/boot") == "$(cat /proc/sys/kernel/random/boot_id)" ]]
    systemctl is-active --quiet "$timer"
    candidate_files "$stage"
    loaded_closure candidate
    printf 'STACK_CANDIDATE_PASS variant=%s boot=%s\n' "$variant" "$(cat /proc/sys/kernel/random/boot_id)"
}
case "$action" in
    --check-original) check_original ;;
    --check-candidate) check_candidate ;;
    --activate)
        [[ $EUID == 0 ]]
        check_original
        candidate_files "$bundle"
        [[ -z $(ls /sys/kernel/tracing/instances) &&
           $(cat /sys/kernel/tracing/current_tracer) == nop &&
           $(cat /sys/module/mt7925e/refcnt) == 0 ]]
        changed=0
        staged=0
        armed=0
        cleanup() {
            local rc=$?
            trap - EXIT
            if (( rc != 0 )); then
                echo STACK_ACTIVATION_FAILED >&2
                if (( changed )); then
                    systemctl reboot --no-block
                else
                    if (( armed )); then systemctl stop "$timer"; fi
                    if (( staged )); then rm -rf -- "$stage"; fi
                fi
            fi
            exit "$rc"
        }
        trap cleanup EXIT
        mkdir -m 0755 "$stage"
        staged=1
        for name in "${modules[@]}"; do
            install -m 0644 "$bundle/${names[$name]}" "$stage/${names[$name]}"
        done
        candidate_files "$stage"
        cat /proc/sys/kernel/random/boot_id > "$stage/boot"
        date +%s > "$stage/epoch"
        chmod 0644 "$stage"/{boot,epoch}
        systemd-run --quiet --collect --unit="wave7-$variant-rollback" \
            --on-active=15min --timer-property=AccuracySec=1s /usr/bin/systemctl reboot
        armed=1
        systemctl is-active --quiet "$timer"
        changed=1
        for ((i=${#modules[@]}-1; i>=0; i--)); do rmmod "${modules[i]}"; done
        for name in "${modules[@]}"; do [[ ! -e /sys/module/$name ]]; done
        for name in "${modules[@]}"; do insmod "$stage/${names[$name]}"; done
        for _ in {1..60}; do
            if interface_ready; then break; fi
            sleep 1
        done
        check_candidate
        firmware=$(journalctl -k -b --no-pager --since "@$(cat "$stage/epoch")" |
            rg 'mt7925e.*(HW/SW Version|WM Firmware Version)')
        printf '%s\n' "$firmware"
        [[ $firmware == *20260813113015a* && $firmware == *20260813113118* ]]
        trap - EXIT
        ;;
    --restore)
        [[ $EUID == 0 ]]
        check_candidate
        systemctl reboot --no-block
        ;;
    *) exit 2 ;;
esac
