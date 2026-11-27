#!/usr/bin/env bash
# Independent Asus guarded native trial; explicit candidate role.
set -Eeuo pipefail
umask 077
(( $# >= 2 )) || { echo "usage: $0 static|dhcp|trunk|native|phy|relink|mac-order|nsscc|instant|worker|down-mode|serial-speed --selftest|--check|--check-baseline|--run|--arm-reboot|--restore-baseline|--check-reboot-1g|--reboot-1g|--selftest-reboot-1g" >&2; exit 2; }
trial_kind=$1; profile=$1; mode=$2; shift 2
root=/home/jan/firmware/wave7/trials
guard8="$root/20261120-secondary-ap-guard8"
candidate_builder=13d84dd2b19cdfd2e7d52bbe107581eaf0ddda4b
candidate_rev="r0+38346-0fbc2cc77b-ap-$profile-guard8"
accepted_mode=static
accepted_builder=''
candidate_module_sha=''
accepted_module_sha=''
accepted_module_taint=''
trunk_trial=0
phy_trial=0
relink_trial=0
kernel_variant_trial=0
candidate_direct_speed=2500
reboot_1g=0
candidate_clock_patch=''
candidate_instant_patch=''
candidate_instant_marker=0
candidate_worker_patch=''
candidate_worker_marker=0
candidate_down_patch=''
candidate_serial_patch=''
accepted_phy_patch=''
accepted_fit_sha=''
accepted_phy_marker=0
candidate_fit_sha=''
candidate_phy_patch=''
candidate_artifact=''
case "$profile" in
  static)
    base="$guard8/guard8-static-lab"
    expected_candidate_sha=b3c5c96ed47fb8ea4c9ea6fd726b499fe52b1391b6591b7016a349f296c35ec8
    accepted="$root/20261120-secondary-ap-guard7/guard7-static-lab/wave7-secondary-ap-static-guard7-sysupgrade.bin"
    accepted_sha=54c3f108efb740339a1f3241ef86d74453745b4918655575ec62789d3d109055
    accepted_rev=r0+38346-0fbc2cc77b-ap-static-guard7
    ;;
  dhcp)
    base="$guard8/guard8-dhcp-managed"
    expected_candidate_sha=3a84923c5c18b1f1354985de975a775e3fbea464fc69dbf8e086267f0b917172
    accepted="$guard8/guard8-static-lab/wave7-secondary-ap-static-guard8-sysupgrade.bin"
    accepted_sha=b3c5c96ed47fb8ea4c9ea6fd726b499fe52b1391b6591b7016a349f296c35ec8
    accepted_rev=r0+38346-0fbc2cc77b-ap-static-guard8
    accepted_builder=$candidate_builder
    ;;
  trunk)
    trunk_trial=1
    candidate_artifact=wave7-trunk-health-dhcp-guard8-sysupgrade.bin
    profile=dhcp
    base="$guard8/trunk-health-dhcp-guard8"
    candidate_rev=r0+38346-895ed9016d-ap-dhcp-guard8
    candidate_builder=72a0c4fc9e797ceeb2776b09233aa824120935fb
    expected_candidate_sha=31e62fa9e107acbc8e70adaf9dd8fa55c24d4e5ed083948f15579761af987305
    candidate_module_sha=b854937955dc136b626b95c06f1e96ca457725bcb30c9747a5d3a4b581362b85
    accepted="$guard8/guard8-dhcp-managed/wave7-secondary-ap-dhcp-guard8-sysupgrade.bin"
    accepted_sha=3a84923c5c18b1f1354985de975a775e3fbea464fc69dbf8e086267f0b917172
    accepted_rev=r0+38346-0fbc2cc77b-ap-dhcp-guard8
    accepted_mode=dhcp
    accepted_builder=13d84dd2b19cdfd2e7d52bbe107581eaf0ddda4b
    accepted_module_sha=ef2fd6186279e997be4368e358f6bda9c2f4222150c9704ad6c24c69a1f99ed7
    ;;
  native)
    trunk_trial=1
    candidate_artifact=wave7-native-recovery-dhcp-guard8-sysupgrade.bin
    profile=dhcp
    base="$guard8/native-recovery-dhcp-guard8"
    candidate_rev=r0+38346-0e69b8931c-ap-dhcp-guard8
    candidate_builder=3d057f1f70b76a1bc3d032d3f16357b6a7f4dc0f
    expected_candidate_sha=1da743efe01ab63043b314a6d44de52e99d65456259f0dae0c1d53a013918f2c
    candidate_module_sha=ff6b4c93d9ce2cb71b2b8dfd0053df70cc4a3ad4960bd49c099eceea85d7fe91
    accepted="$guard8/trunk-health-dhcp-guard8/wave7-trunk-health-dhcp-guard8-sysupgrade.bin"
    accepted_sha=31e62fa9e107acbc8e70adaf9dd8fa55c24d4e5ed083948f15579761af987305
    accepted_rev=r0+38346-895ed9016d-ap-dhcp-guard8
    accepted_mode=dhcp
    accepted_builder=72a0c4fc9e797ceeb2776b09233aa824120935fb
    accepted_module_sha=b854937955dc136b626b95c06f1e96ca457725bcb30c9747a5d3a4b581362b85
    accepted_module_taint=O
    ;;
  phy)
    trunk_trial=1
    phy_trial=1
    candidate_artifact=wave7-stock-poll-fifo-dhcp-guard8-sysupgrade.bin
    profile=dhcp
    base="$guard8/stock-poll-fifo-dhcp-guard8"
    candidate_rev=r0+38346-0418bb7af2-ap-dhcp-guard8
    candidate_builder=749c36c682119f223341d30e7a6d9992160966c0
    expected_candidate_sha=3ad42acf6fd9765dc9f92f937e5472bb2e19987d92896ce3e8994810e22badd9
    candidate_module_sha=ff6b4c93d9ce2cb71b2b8dfd0053df70cc4a3ad4960bd49c099eceea85d7fe91
    candidate_fit_sha=c289598628e75f7a603ec127dbb5cbd1fdcf6128ba15cea6c4fe9b0aa0232b8e
    candidate_phy_patch=0418bb7af25d13406bb896696eb78541ccd2aa00
    accepted="$guard8/native-recovery-dhcp-guard8/wave7-native-recovery-dhcp-guard8-sysupgrade.bin"
    accepted_sha=1da743efe01ab63043b314a6d44de52e99d65456259f0dae0c1d53a013918f2c
    accepted_rev=r0+38346-0e69b8931c-ap-dhcp-guard8
    accepted_mode=dhcp
    accepted_builder=3d057f1f70b76a1bc3d032d3f16357b6a7f4dc0f
    accepted_module_sha=$candidate_module_sha
    accepted_module_taint=O
    ;;
  relink|mac-order|nsscc|instant|worker|down-mode|serial-speed)
    trunk_trial=1
    phy_trial=1
    relink_trial=1
    profile=dhcp
    base="$guard8/conditional-relink-dhcp-guard8"
    candidate_artifact=wave7-conditional-relink-dhcp-guard8-sysupgrade.bin
    candidate_rev=r0+38346-fe5568a4fb-ap-dhcp-guard8
    candidate_builder=7d325fb175ddf66a9066b995d9054d5ad797c3f0
    expected_candidate_sha=175e06c0611b7ec971bc67f1861e2b04991734fdf88e0e94e12a1c73e4fb4213
    candidate_module_sha=ff6b4c93d9ce2cb71b2b8dfd0053df70cc4a3ad4960bd49c099eceea85d7fe91
    candidate_fit_sha=c289598628e75f7a603ec127dbb5cbd1fdcf6128ba15cea6c4fe9b0aa0232b8e
    candidate_phy_patch=0418bb7af25d13406bb896696eb78541ccd2aa00
    candidate_relink_patch=fe5568a4fbd93516f7cbc3d4f2e6ca622e62accc
    candidate_pcs_sha=168d278179537c5a463119c4c89fa6642c800ce00a455b4714ebb54d94d11dc1
    candidate_ppe_sha=eb9083d152f717c3069532ef121107ef5ca3209164e42ef205c964aa64857b49
    accepted="$guard8/stock-poll-fifo-dhcp-guard8/wave7-stock-poll-fifo-dhcp-guard8-sysupgrade.bin"
    accepted_sha=3ad42acf6fd9765dc9f92f937e5472bb2e19987d92896ce3e8994810e22badd9
    accepted_rev=r0+38346-0418bb7af2-ap-dhcp-guard8
    accepted_builder=749c36c682119f223341d30e7a6d9992160966c0
    accepted_mode=dhcp
    accepted_module_sha=$candidate_module_sha
    accepted_module_taint=O
    accepted_phy_patch=$candidate_phy_patch
    accepted_fit_sha=$candidate_fit_sha
    accepted_phy_marker=1
    accepted_pcs_sha=74bd3fddd9e35f543100073a4f7a85ebfe7aca503e5c48191dd3c2ee8190b473
    accepted_ppe_sha=1ff7a7d590f7ef45bdaf794a3e5dfeb66ffe9a0f9eed24cf4dd8df5a7c0b5fc0
    if [[ $trial_kind == mac-order ]]; then
      base="$guard8/stock-mac-order-dhcp-guard8"
      candidate_artifact=wave7-stock-mac-order-dhcp-guard8-sysupgrade.bin
      candidate_rev=r0+38346-7aa198ca4c-ap-dhcp-guard8
      candidate_builder=e2b9f3380f3b1e767cea062419276b790b340786
      expected_candidate_sha=d2e356f9d2fb2be85dc8c605684f23515255c676dfe918fb058a0924762200fc
      candidate_relink_patch=7aa198ca4c876708dcd7731885377fdea41416f7
      candidate_ppe_sha=e93841080d3b66662b02fdae2427d0aa0add1bda5a1684e2559a868ccb16eb19
    elif [[ $trial_kind == nsscc ]]; then
      kernel_variant_trial=1
      base="$guard8/nsscc-parent-order-dhcp-guard8"
      candidate_artifact=wave7-nsscc-parent-order-dhcp-guard8-sysupgrade.bin
      candidate_rev=r0+38346-e771c4f65a-ap-dhcp-guard8
      candidate_builder=2cc6be3dcd8f1f9e9134f0258b598e71f9ead961
      expected_candidate_sha=ccc7406520d8e9fa2b499f34c1460375b7a24b6c074e13532f559943c81a66a3
      candidate_fit_sha=133b2b0cbd00e4f9934b96d924c10ebd64a109a859371f31226795c92c3ffbf2
      candidate_clock_patch=e771c4f65ab76440aba347d895332b3c442caab7
      candidate_relink_patch=''
      candidate_pcs_sha=$accepted_pcs_sha
      candidate_ppe_sha=$accepted_ppe_sha
    elif [[ $trial_kind == instant ]]; then
      kernel_variant_trial=1
      base="$guard8/instant-fifo-dhcp-guard8"
      candidate_artifact=wave7-instant-fifo-dhcp-guard8-sysupgrade.bin
      candidate_rev=r0+38346-44d12aa1f7-ap-dhcp-guard8
      candidate_builder=e2923b57530a715a187bf7a518cd398ebdbbce69
      expected_candidate_sha=9d54b86cf11ef664edff9692636eedce21444fe6c3969310736837aaa6c7d2a5
      candidate_fit_sha=c4ae7f047a1dc246c44ec93490015dbe4fa1fe6d847758087921a7dd219ac704
      candidate_instant_patch=44d12aa1f75285c4b5209d227da200227d96588a
      candidate_instant_marker=1
      candidate_relink_patch=''
      candidate_pcs_sha=$accepted_pcs_sha
      candidate_ppe_sha=$accepted_ppe_sha
    elif [[ $trial_kind == worker ]]; then
      kernel_variant_trial=1
      base="$guard8/independent-fifo-dhcp-guard8"
      candidate_artifact=wave7-independent-fifo-dhcp-guard8-sysupgrade.bin
      candidate_rev=r0+38346-3688c57cd3-ap-dhcp-guard8
      candidate_builder=bf2d41b2372be677f91ef78d55852a6595c268b4
      expected_candidate_sha=1e86a20cc10608fc9c7639980af8723b66cbff2a07fd0a48f930af6c02db34f6
      candidate_fit_sha=11d60fc94983348d7951a3eb31f9bb6b5de4a77ed4f5262824365c9c761870cb
      candidate_instant_patch=44d12aa1f75285c4b5209d227da200227d96588a
      candidate_instant_marker=1
      candidate_worker_patch=3688c57cd341560fd73365916b68a76465ef2f8a
      candidate_worker_marker=1
      candidate_relink_patch=''
      candidate_pcs_sha=$accepted_pcs_sha
      candidate_ppe_sha=$accepted_ppe_sha
    elif [[ $trial_kind == down-mode ]]; then
      kernel_variant_trial=1
      base="$guard8/down-mode-dhcp-guard8"
      candidate_artifact=wave7-down-mode-dhcp-guard8-sysupgrade.bin
      candidate_rev=r0+38346-ef7d41f2b1-ap-dhcp-guard8
      candidate_builder=fae9cfe596c54e65b491963dec82b024dbdff6d8
      expected_candidate_sha=6737fe3c8969b83802eaafcac9fa7ba8d65700ce20b145cd2ecb54718e9fc431
      candidate_fit_sha=fab4ba3fc1c282f92f95f0274295c6af8832a97ea4c3767d4b197bd76dbd66a4
      candidate_instant_patch=44d12aa1f75285c4b5209d227da200227d96588a
      candidate_instant_marker=1
      candidate_worker_patch=3688c57cd341560fd73365916b68a76465ef2f8a
      candidate_worker_marker=1
      candidate_relink_patch=''
      candidate_pcs_sha=c62c6baff502d1338c34c3e2fa94b7b1c7fe6b765422cda46db96749a28ed4c5
      candidate_down_patch=ef7d41f2b18457e9576d8ee7a2aa4d6f549ec7a8
      candidate_ppe_sha=$accepted_ppe_sha
    elif [[ $trial_kind == serial-speed ]]; then
      kernel_variant_trial=1
      base="$guard8/serial-speed-dhcp-guard8"
      candidate_artifact=wave7-serial-speed-dhcp-guard8-sysupgrade.bin
      candidate_rev=r0+38346-f9aa3e1fa3-ap-dhcp-guard8
      candidate_builder=bcaae0c7eac821a46fdfdecd1dad4f6ad13adbf9
      expected_candidate_sha=ec5e99d208cbc811f4ce5536f4fb3f7ff2a66eea728d497ab6397e76c1dfc516
      candidate_fit_sha=$accepted_fit_sha
      candidate_relink_patch=''
      candidate_pcs_sha=6e1293e83985caf4eb352e163036d050de5eb2d3f4272ca8a2a71667833658bf
      candidate_serial_patch=f9aa3e1fa3a541bb52e11223c7297cbd4dbc0ecc
      candidate_ppe_sha=$accepted_ppe_sha
    fi
    ;;
  *) echo 'unknown candidate profile'    >&2; exit 2 ;;
esac
if [[ ( $trial_kind == down-mode || $trial_kind == serial-speed ) && $mode != --selftest ]]; then
  [[ $candidate_builder =~ ^[0-9a-f]{40}$ ]] || { echo 'candidate builder not pinned' >&2; exit 2; }
  for pin in "$expected_candidate_sha" "$candidate_fit_sha" "$candidate_pcs_sha"; do
    [[ $pin =~ ^[0-9a-f]{64}$ ]] || { echo 'candidate digest not pinned by final QA' >&2; exit 2; }
  done
fi
case "$mode" in
  --check-reboot-1g|--reboot-1g|--watch-reboot-1g|--selftest-reboot-1g)
    [[ $trial_kind == serial-speed ]] || { echo '1G reboot restricted to 0498' >&2; exit 2; }
    reboot_1g=1
    candidate_direct_speed=1000
    case "$mode" in
      --watch-reboot-1g) mode=--watch ;;
      --selftest-reboot-1g) mode=--selftest ;;
    esac
    ;;
esac
candidate="$base/${candidate_artifact:-wave7-secondary-ap-$profile-guard8-sysupgrade.bin}"
candidate_sha=$(awk -v name="${candidate##*/}" '$2 == name || $2 == "./"name {print $1}' "$base/SHA256SUMS" 2>/dev/null || :)
leasefile="$guard8/upstream/dnsmasq.leases"
upstream_unit=wave7-lab-upstream-guard8
key=/home/jan/.ssh/wave7-root-rsa
known=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8/known_hosts
host=root@192.168.76.1
attestor=/home/jan/scripts/wave7/secondary-ap-guard8/attest-management.sh
management_ip=192.168.76.250
management_iface=enp4s0f4u2u2u4
switch_iface=$management_iface
switch_ip=$management_ip
direct_iface=enp4s0f4u2u4
direct_ip=192.168.76.2
peer_iface=$switch_iface
peer_ip=$switch_ip
if [[ $phy_trial == 1 ]]; then
  # QCA8081 is the DUT. Keep authenticated management on RTL8367D.
  peer_iface=$direct_iface
  peer_ip=$direct_ip
elif [[ $trunk_trial == 1 ]]; then
  # RTL8367D is the DUT; keep authenticated control on QCA8081.
  management_ip=$direct_ip
  management_iface=$direct_iface
fi
remote() {
  ssh -n -T -i "$key" -o "BindInterface=$management_iface" -o "BindAddress=$management_ip" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 \
    -o ConnectionAttempts=1 -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" "$host" "$@"
}
remote_timed() {
  timeout 135 ssh -n -T -i "$key" -o "BindInterface=$management_iface" -o "BindAddress=$management_ip" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=4 \
    -o ConnectionAttempts=1 -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" "$host" "$@"
}
upload() {
  scp -q -O -i "$key" -o "BindInterface=$management_iface" -o "BindAddress=$management_ip" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=5 \
    -o ConnectionAttempts=1 -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" "$1" "$host:$2"
}
fatal() { printf 'PREFLIGHT_BLOCKED: %s\n' "$*" >&2; exit 3; }
value() { sed -n "s/^$2=//p" <<< "$1" | head -1; }
read_state_core() {
  remote 'echo "boot=$(cat /proc/sys/kernel/random/boot_id)";
    echo "rev=$(cat /etc/openwrt_version)";
    set -- $SSH_CONNECTION;
    echo "management_peer=$1";
    echo "kernel=$(uname -r)";
    echo "bootfail=$(fw_printenv -n bootfail 2>/dev/null || :)";
    echo "keep=$(test -e /tmp/wave7-keep-boot && echo 1 || echo 0)";
    echo "ap=$(iw dev ap-mld0 info 2>/dev/null | grep -Ec "link ID[[:space:]]+[01]" || :)";
    echo "q6=$(good=0; for p in /sys/class/remoteproc/remoteproc0 /sys/class/remoteproc/remoteproc1 /sys/class/remoteproc/remoteproc2; do [ "$(cat "$p/state" 2>/dev/null)" = running ] && good=$((good+1)); done; echo "$good")";
    echo "ping=$(ping -I br-lan -c 1 -W 1 192.168.76.2 >/dev/null 2>&1 && echo 1 || echo 0)";
    echo "noc=$(dmesg | grep -c "NOC ERROR DETECTED" || :)";
    echo "lan=$(cat /sys/class/net/lan/carrier 2>/dev/null || echo absent)";
    echo "lan_speed=$(cat /sys/class/net/lan/speed 2>/dev/null || echo absent)";
    echo "lan1=$(cat /sys/class/net/lan1/carrier 2>/dev/null || echo absent)";
    echo "bridge=$(readlink /sys/class/net/lan1/master 2>/dev/null | grep -q br-lan && echo 1 || echo 0)";
    echo "speed=$(cat /sys/class/net/lan1/speed 2>/dev/null || echo absent)";
    echo "role=$(sed -n "s/^role=//p" /etc/wave7-role-profile 2>/dev/null | head -1)";
    echo "mode=$(sed -n "s/^mode=//p" /etc/wave7-role-profile 2>/dev/null | head -1)";
    echo "overlay_ready=$(test -e /tmp/wave7-ap-overlay-ready && echo 1 || echo 0)";
    echo "proto=$(uci -q get network.lan.proto)";
    echo "dnsmasq_disabled=$(uci -q get dhcp.main.disabled)";
    echo "dhcpv4=$(uci -q get dhcp.lan.dhcpv4)";
    echo "dhcpv6=$(uci -q get dhcp.lan.dhcpv6)";
    echo "ra=$(uci -q get dhcp.lan.ra)";
    echo "root_password=$(awk -F: '\''$1=="root" {print $2}'\'' /etc/shadow)";
    echo "password_auth=$(uci -q get dropbear.main.PasswordAuth)";
    echo "root_password_auth=$(uci -q get dropbear.main.RootPasswordAuth)";
    echo "builder_commit=$(sed -n "s/^builder_commit=//p" /etc/wave7-role-profile 2>/dev/null | head -1)";
    echo "bridge_ip=$(ip -4 -o addr show dev br-lan | awk '\''$3=="inet" {print $4}'\'' | head -1)";
    echo "approval=$(if [ -r /rom/lib/wave7/role-firstboot.sh ]; then . /rom/lib/wave7/role-firstboot.sh; if command -v wave7_secondary_ap_approval_matches >/dev/null 2>&1 && wave7_secondary_ap_approval_matches /rom/etc/wave7-role-profile "$(cat /rom/etc/openwrt_version)" /overlay/wave7-ap-approved; then echo 1; else echo 0; fi; else echo 0; fi)";
    echo "token=$(test -e /tmp/wave7-ap-management-verified && echo 1 || echo 0)";
    echo "local_ready=$(if [ -r /rom/lib/wave7/role-firstboot.sh ]; then . /rom/lib/wave7/role-firstboot.sh; if command -v wave7_secondary_ap_local_ready >/dev/null 2>&1 && wave7_secondary_ap_local_ready; then echo 1; else echo 0; fi; else echo 0; fi)";
    echo "uptime=$(cut -d. -f1 /proc/uptime)"'
}
# Sample switch counters over the independent management path.
# The second key-authenticated session must traverse the other NIC.
read_state() {
  local s extra peer boot
  s=$(read_state_core) || return 1
  printf '%s\n' "$s"
  [[ $trunk_trial == 1 && $(value "$s" kernel) == 6.18.60 ]] || return 0
  boot=$(value "$s" boot)
  extra=$(remote '
    echo "sample_boot=$(cat /proc/sys/kernel/random/boot_id)"
    p=lib/modules/6.18.60/rtl8365mb.ko
    echo "module_sha=$(sha256sum /$p 2>/dev/null | cut -d" " -f1)"
    echo "module_rom_sha=$(sha256sum /rom/$p 2>/dev/null | cut -d" " -f1)"
    echo "module_live=$(test "$(cat /sys/module/rtl8365mb/initstate 2>/dev/null)" = live && echo 1 || echo 0)"
    echo "module_taint=$(cat /sys/module/rtl8365mb/taint 2>/dev/null)"
    echo "module_upper_clear=$(test ! -e /overlay/upper/lib/modules && test ! -L /overlay/upper/lib/modules && echo 1 || echo 0)"
    echo "manifest_module_sha=$(sed -n "s/^trial_module_sha256=//p" /rom/etc/wave7-role-profile)"
    echo "manifest_phy_patch=$(sed -n "s/^trial_phy_kernel_patch_commit=//p" /rom/etc/wave7-role-profile)"
    echo "manifest_fit_sha=$(sed -n "s/^trial_fit_sha256=//p" /rom/etc/wave7-role-profile)"
    echo "phy_poll_marker=$(dmesg | grep -q "fifo_action=stock_status_poll" && echo 1 || echo 0)"
    for item in pcs:pcs-qcom-ipq9574:pcs_qcom_ipq9574 ppe:qcom-ppe:qcom_ppe; do
      name=${item%%:*}; rest=${item#*:}; file=${rest%%:*}; mod=${rest#*:}
      p=lib/modules/6.18.60/$file.ko
      echo "${name}_sha=$(sha256sum /$p 2>/dev/null | cut -d" " -f1)"
      echo "${name}_rom_sha=$(sha256sum /rom/$p 2>/dev/null | cut -d" " -f1)"
      echo "${name}_live=$(cat /sys/module/$mod/initstate 2>/dev/null || echo absent)"
      echo "${name}_taint=$(cat /sys/module/$mod/taint 2>/dev/null || echo absent)"
      echo "manifest_${name}_sha=$(sed -n "s/^trial_${name}_sha256=//p" /rom/etc/wave7-role-profile)"
    done
    echo "manifest_clock_patch=$(sed -n "s/^trial_clock_kernel_patch_commit=//p" /rom/etc/wave7-role-profile)"
    echo "manifest_instant_patch=$(sed -n "s/^trial_instant_fifo_patch_commit=//p" /rom/etc/wave7-role-profile)"
    echo "instant_fifo_marker=$(dmesg | grep -q "wave7-diag: fifo-instant ss=" && echo 1 || echo 0)"
    echo "manifest_down_patch=$(sed -n "s/^trial_down_mode_patch_commit=//p" /rom/etc/wave7-role-profile)"
    echo "manifest_worker_patch=$(sed -n "s/^trial_fifo_worker_patch_commit=//p" /rom/etc/wave7-role-profile)"
    echo "fifo_worker_marker=$(dmesg | grep -Eq "wave7-diag: fifo-worker tick=[0-9]+ edge=[0-9]+ ss=[0-9]+ phylib=[01] result=0$" && echo 1 || echo 0)"
    echo "manifest_serial_patch=$(sed -n "s/^trial_serial_speed_patch_commit=//p" /rom/etc/wave7-role-profile)"
    echo "manifest_relink_patch=$(sed -n "s/^trial_relink_patch_commit=//p" /rom/etc/wave7-role-profile)"
    ethtool -S switch 2>/dev/null | awk '\''$1=="s00_p06_dot3StatsFCSErrors:"{print "cpu_fcs=" $2}
      $1=="s00_p06_etherStatsFragments:"{print "cpu_fragments=" $2}
      $1=="s00_p06_ifInUcastPkts:"{print "cpu_ucast=" $2}
      $1=="s00_p06_ifInMulticastPkts:"{print "cpu_mcast=" $2}
      $1=="s00_p06_ifInBroadcastPkts:"{print "cpu_bcast=" $2}
      $1=="s00_p06_etherStatsDropEvents:"{print "cpu_drops=" $2}'\''
  ') || return 1
  [[ $(value "$extra" sample_boot) == "$boot" ]] || return 1
  printf '%s\n' "$extra"
  if [[ $reboot_1g == 1 ]]; then
    echo "direct_peer_speed=$(cat "/sys/class/net/$direct_iface/speed" 2>/dev/null || echo absent)"
  fi
  peer=$(ssh -n -T -i "$key" -o "BindInterface=$peer_iface" -o "BindAddress=$peer_ip" \
    -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=3 -o ConnectionAttempts=1 \
    -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" "$host" \
    'printf "%s %s\n" "$(cat /proc/sys/kernel/random/boot_id)" "${SSH_CONNECTION%% *}"' 2>/dev/null) || peer=''
  if [[ $phy_trial == 1 ]]; then
    if [[ $(value "$s" management_peer) == "$switch_ip" ]]; then echo switch_verified=1; else echo switch_verified=0; fi
    if [[ $peer == "$boot $direct_ip" ]]; then echo direct_verified=1; else echo direct_verified=0; fi
  else
    if [[ $peer == "$boot $switch_ip" ]]; then echo switch_verified=1; else echo switch_verified=0; fi
    if [[ $(value "$s" management_peer) == "$direct_ip" ]]; then echo direct_verified=1; else echo direct_verified=0; fi
  fi
}
module_matches() {
  local s=$1 hash=$2 taint=$3
  for exp in "module_sha=$hash" "module_rom_sha=$hash" "module_taint=$taint" module_live=1 module_upper_clear=1; do
    grep -Fxq "$exp" <<< "$s" || return 1
  done
}
relink_matches() {
  local s=$1 pcs=$2 ppe=$3 patch=$4 down=$5 serial=$6 manifest_pcs='' manifest_ppe='' exp
  if [[ -n $patch || -n $down || -n $serial ]]; then manifest_pcs=$pcs; manifest_ppe=$ppe; fi
  for exp in "pcs_sha=$pcs" "pcs_rom_sha=$pcs" pcs_live=live pcs_taint= \
    "ppe_sha=$ppe" "ppe_rom_sha=$ppe" ppe_live=live ppe_taint= \
    "manifest_relink_patch=$patch" "manifest_serial_patch=$serial" "manifest_pcs_sha=$manifest_pcs" "manifest_ppe_sha=$manifest_ppe" module_upper_clear=1; do
    grep -Fxq "$exp" <<< "$s" || return 1
  done
}
phy_matches() {
  local s=$1 patch=$2 fit=$3 marker=$4
  grep -Fxq "manifest_phy_patch=$patch" <<< "$s" &&
    grep -Fxq "manifest_fit_sha=$fit" <<< "$s" &&
    grep -Fxq "phy_poll_marker=$marker" <<< "$s"
}
kernel_variant_matches() {
  local s=$1 clock=$2 instant=$3 marker=$4 worker=$5 worker_marker=$6 down=$7 exp
  for exp in "manifest_clock_patch=$clock" "manifest_instant_patch=$instant" "instant_fifo_marker=$marker" \
    "manifest_worker_patch=$worker" "fifo_worker_marker=$worker_marker" "manifest_down_patch=$down"; do
    grep -Fxq "$exp" <<< "$s" || return 1
  done
}
trunk_counters_valid() {
  local s=$1 field
  for field in cpu_fcs cpu_fragments cpu_ucast cpu_mcast cpu_bcast cpu_drops; do
    [[ $(value "$s" "$field") =~ ^[0-9]+$ ]] || return 1
  done
}
# Both native-flash and approved-reboot guards use the same counter
# sampling and continuous error-free window.
trunk_counter_header() {
  printf 'wall_epoch\tboot\tuptime\tfcs\tfragments\tucast\tmcast\tbcast\tdrops\tswitch\tkeep\n'
}
trunk_counter_row() {
  local s=$1 now=$2 boot=$3 field
  trunk_counters_valid "$s" || return 1
  printf '%s\t%s' "$now" "$boot"
  for field in uptime cpu_fcs cpu_fragments cpu_ucast cpu_mcast cpu_bcast cpu_drops switch_verified keep; do
    printf '\t%s' "$(value "$s" "$field")"
  done
  printf '\n'
}
trunk_error_key() {
  printf '%s:%s:%s\n' "$(value "$1" cpu_fcs)" "$(value "$1" cpu_fragments)" "$(value "$1" cpu_drops)"
}
trunk_path_healthy() {
  grep -Fxq switch_verified=1 <<< "$1" &&
    grep -Fxq direct_verified=1 <<< "$1" &&
    grep -Fxq local_ready=1 <<< "$1" &&
    trunk_counters_valid "$1"
}
# A permanently configured local address is required, not a DHCP lease
# that may expire when the AP disables its own DHCP server.
has_permanent_address() {
  local addresses=$1 cidr=$2
  awk -v wanted="$cidr" '
    $3 == "inet" && $4 == wanted {
      if ($0 ~ /(^|[[:space:]])dynamic([[:space:]]|$)/) next
      if ($0 ~ /valid_lft forever preferred_lft forever/) found=1
    }
    END {exit !found}
  ' <<< "$addresses"
}
# One definition of the healthy accepted baseline, used before the trial
# and when checking that the rollback has actually booted successfully.
baseline_healthy() {
  role_healthy "$1" "$accepted_rev" "$accepted_mode" 2500 || return 1
  if [[ -n $accepted_builder ]]; then
    grep -Fxq "builder_commit=$accepted_builder" <<< "$1" || return 1
  fi
  if [[ $trunk_trial == 1 ]]; then
    module_matches "$1" "$accepted_module_sha" "$accepted_module_taint" && trunk_path_healthy "$1" || return 1
    if [[ -n $accepted_module_taint ]]; then
      grep -Fxq "manifest_module_sha=$accepted_module_sha" <<< "$1" || return 1
    fi
  fi
  if [[ $phy_trial == 1 ]]; then
    phy_matches "$1" "$accepted_phy_patch" "$accepted_fit_sha" "$accepted_phy_marker" || return 1
  fi
  if [[ $relink_trial == 1 ]]; then
    relink_matches "$1" "$accepted_pcs_sha" "$accepted_ppe_sha" '' '' '' || return 1
  fi
  if [[ $kernel_variant_trial == 1 ]]; then
    kernel_variant_matches "$1" '' '' 0 '' 0 '' || return 1
  fi
}
rollback_eligible() {
  local s=$1
  [[ $(value "$s" rev) == "$candidate_rev" &&
     $(value "$s" keep) == 1 && $(value "$s" bootfail) == 0 ]]
}
healthy() {
  role_healthy "$1" "$candidate_rev" "$profile" "$candidate_direct_speed" &&
    grep -Fxq "builder_commit=$candidate_builder" <<< "$1" || return 1
  if [[ $trunk_trial == 1 ]]; then
    module_matches "$1" "$candidate_module_sha" O &&
      grep -Fxq "manifest_module_sha=$candidate_module_sha" <<< "$1" &&
      trunk_path_healthy "$1" || return 1
  fi
  if [[ $phy_trial == 1 ]]; then
    phy_matches "$1" "$candidate_phy_patch" "$candidate_fit_sha" 1 || return 1
  fi
  if [[ $relink_trial == 1 ]]; then
    relink_matches "$1" "$candidate_pcs_sha" "$candidate_ppe_sha" "$candidate_relink_patch" "$candidate_down_patch" "$candidate_serial_patch" || return 1
  fi
  if [[ $kernel_variant_trial == 1 ]]; then
    kernel_variant_matches "$1" "$candidate_clock_patch" "$candidate_instant_patch" "$candidate_instant_marker" "$candidate_worker_patch" "$candidate_worker_marker" "$candidate_down_patch" || return 1
  fi
}
role_healthy() {
  local s=$1 expected_revision=$2 expected_mode=$3 expected_direct_speed=$4
  for expect in "rev=$expected_revision" kernel=6.18.60 "management_peer=$management_ip" bootfail=0 keep=1 ap=2 \
    q6=3 ping=1 noc=0 lan=1 "lan_speed=$expected_direct_speed" lan1=1 bridge=1 speed=1000 \
    role=secondary-ap "mode=$expected_mode" "proto=$expected_mode" bridge_ip=192.168.76.1/24 dnsmasq_disabled=1 \
    dhcpv4=disabled dhcpv6=disabled ra=disabled root_password='!' \
    password_auth=off root_password_auth=off overlay_ready=1; do
    grep -Fxq "$expect" <<< "$s" || return 1
  done
  if [[ $reboot_1g == 1 ]]; then
    grep -Fxq "direct_peer_speed=$expected_direct_speed" <<< "$s" || return 1
  fi
}
lease_valid() {
  local records=$1 now=$2
  awk -v now="$now" '$1 > now && tolower($2)=="70:5a:6f:5a:bb:14" && $3=="192.168.76.1" {n++} END {exit n!=1}' <<< "$records"
}
upstream_ready() {
  systemctl is-active --quiet "$upstream_unit.service" &&
    /home/jan/scripts/wave7/secondary-ap-guard8/lab-upstream.sh --check >/dev/null
}
candidate_healthy() {
  healthy "$1" || return 1
  if [[ $profile == dhcp ]]; then
    systemctl is-active --quiet "$upstream_unit.service" && lease_valid "$(cat "$leasefile" 2>/dev/null || :)" "$(date +%s)"
  fi
}
autonomous_approval_ok() {
  grep -Fxq approval=1 <<< "$1" &&
    grep -Fxq token=0 <<< "$1" &&
    grep -Fxq local_ready=1 <<< "$1"
}
autonomous_healthy() {
  candidate_healthy "$1" && autonomous_approval_ok "$1"
}
restore_profile() {
  [[ $trial_kind == relink || $trial_kind == mac-order || $trial_kind == nsscc || $trial_kind == instant || $trial_kind == worker || $trial_kind == down-mode || $trial_kind == serial-speed ]]
}
reboot_source_valid() {
  [[ $reboot_1g == 1 && $trial_kind == serial-speed ]] &&
    healthy "$1" && grep -Fxq approval=0 <<< "$1" && grep -Fxq token=1 <<< "$1"
}
restore_source_valid() {
  restore_profile && healthy "$1" && grep -Fxq approval=0 <<< "$1"
}
restore_record_matches() {
  [[ $2 =~ ^[0-9a-f-]{36}$ ]] &&
    [[ $1 == $'be5e8dc71ca78591010165da43e4408dfe5c6234a07ec7addc821bda77023972  /overlay/wave7-ap-approved\n'"$2" ]]
}
restore_target_valid() {
  baseline_healthy "$1" && autonomous_approval_ok "$1"
}
XDG_RUNTIME_DIR=/run/user/$(id -u)
export XDG_RUNTIME_DIR
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
# Wait for the actual locked observer acknowledgement, not a guessed
# process-starting delay. Both systemd units must remain live throughout.
await_observers() {
  local guard=$1 fallback=$2 out=$3 i status
  for ((i=0; i<30; i++)); do
    systemctl --user is-active --quiet "$guard.service" || fatal 'observer failed to arm'
    systemctl --user is-active --quiet "$fallback.service" || fatal 'fallback collector failed to arm'
    if [[ -r $out/status ]]; then
      status=$(cat "$out/status")
      [[ $status == ARMED ]] || fatal "unexpected observer status: $status"
      return 0
    fi
    sleep 1
  done
  fatal 'observer acknowledgement timed out'
}
if [[ $mode == --selftest ]]; then
  s=$'rev=r0+38346-0fbc2cc77b-ap-static-guard8\nkernel=6.18.60\nmanagement_peer=192.168.76.250\nbootfail=0\nkeep=1\nap=2\nq6=3\nping=1\nnoc=0\nlan=1\nlan_speed=2500\nlan1=1\nbridge=1\nspeed=1000\nrole=secondary-ap\nmode=static\nproto=static\ndnsmasq_disabled=1\ndhcpv4=disabled\ndhcpv6=disabled\nra=disabled\nroot_password=!\npassword_auth=off\nroot_password_auth=off\noverlay_ready=1\nbuilder_commit=13d84dd2b19cdfd2e7d52bbe107581eaf0ddda4b'
  s=$(sed -e "s/^rev=.*/rev=$candidate_rev/" -e "s/^mode=.*/mode=$profile/" -e "s/^proto=.*/proto=$profile/" \
    -e "s/^builder_commit=.*/builder_commit=$candidate_builder/" -e "s/^management_peer=.*/management_peer=$management_ip/" <<< "$s")
  s+=$'\nbridge_ip=192.168.76.1/24'
  if [[ $reboot_1g == 1 ]]; then
    s=$(sed "s/^lan_speed=.*/lan_speed=$candidate_direct_speed/" <<< "$s")
    s+=$'\ndirect_peer_speed=1000'
  fi
  if [[ $trunk_trial == 1 ]]; then
    s+=$(printf '\nmodule_sha=%s\nmodule_rom_sha=%s\nmanifest_module_sha=%s\nmodule_taint=O\nmodule_live=1\nmodule_upper_clear=1\nswitch_verified=1\ndirect_verified=1\nlocal_ready=1\ncpu_fcs=0\ncpu_fragments=0\ncpu_ucast=1\ncpu_mcast=1\ncpu_bcast=1\ncpu_drops=0' "$candidate_module_sha" "$candidate_module_sha" "$candidate_module_sha")
  fi
  if [[ $phy_trial == 1 ]]; then
    s+=$(printf '\nmanifest_phy_patch=%s\nmanifest_fit_sha=%s\nphy_poll_marker=1' "$candidate_phy_patch" "$candidate_fit_sha")
  fi
  if [[ $relink_trial == 1 ]]; then
    s+=$(printf '\npcs_sha=%s\npcs_rom_sha=%s\npcs_live=live\npcs_taint=\nppe_sha=%s\nppe_rom_sha=%s\nppe_live=live\nppe_taint=\nmanifest_pcs_sha=%s\nmanifest_ppe_sha=%s\nmanifest_relink_patch=%s\nmanifest_serial_patch=%s' "$candidate_pcs_sha" "$candidate_pcs_sha" "$candidate_ppe_sha" "$candidate_ppe_sha" "$candidate_pcs_sha" "$candidate_ppe_sha" "$candidate_relink_patch" "$candidate_serial_patch")
  fi
  if [[ $kernel_variant_trial == 1 ]]; then
    s+=$(printf '\nmanifest_clock_patch=%s\nmanifest_instant_patch=%s\ninstant_fifo_marker=%s\nmanifest_worker_patch=%s\nfifo_worker_marker=%s\nmanifest_down_patch=%s' "$candidate_clock_patch" "$candidate_instant_patch" "$candidate_instant_marker" "$candidate_worker_patch" "$candidate_worker_marker" "$candidate_down_patch")
    # Kernel-only candidates inherit the original 0491 modules.
    if [[ -z $candidate_down_patch && -z $candidate_serial_patch ]]; then
      s=$(sed -e 's/^manifest_pcs_sha=.*/manifest_pcs_sha=/' -e 's/^manifest_ppe_sha=.*/manifest_ppe_sha=/' <<< "$s")
    fi
  fi
  healthy "$s" || fatal 'good state rejected'
  if [[ $phy_trial == 1 ]]; then
    for change in manifest_phy_patch=wrong manifest_fit_sha=wrong phy_poll_marker=0 direct_verified=0; do
      bad=$(sed "s|^${change%%=*}=.*|$change|" <<< "$s")
      if healthy "$bad"; then fatal "bad PHY state accepted: $change"; fi
    done
  fi
  for change in builder_commit=wrong management_peer=192.168.76.190 q6=2 ap=1 ping=0 noc=1 lan=0 "lan_speed=$((3500-candidate_direct_speed))" lan1=0 bridge=0 speed=2500 bootfail=4 role=lab mode=wrong proto=wrong bridge_ip=192.168.76.99/24 dnsmasq_disabled=0 dhcpv4=server dhcpv6=server ra=server root_password=notlocked password_auth=on root_password_auth=on overlay_ready=0; do
    field=$(cut -d= -f1 <<< "$change")
    bad=$(sed "s|^$field=.*|$change|" <<< "$s")
    if healthy "$bad"; then fatal "bad state accepted: $change"; fi
  done
  permanent="87: eth0 inet $management_ip/24 scope global valid_lft forever preferred_lft forever"
  leased="87: eth0 inet $management_ip/24 scope global dynamic valid_lft 300sec preferred_lft 300sec"
  has_permanent_address "$permanent" "$management_ip/24" || fatal 'static address rejected'
  if has_permanent_address "$leased" "$management_ip/24"; then fatal 'DHCP lease accepted'; fi
  if has_permanent_address "$permanent" '192.168.76.190/24'; then fatal 'wrong address accepted'; fi
  rollback_eligible "$s" || fatal 'accepted trial ineligible for rollback'
  for change in bootfail=1 keep=0 "rev=$accepted_rev"; do
    field=$(cut -d= -f1 <<< "$change")
    bad=$(sed "s|^$field=.*|$change|" <<< "$s")
    if rollback_eligible "$bad"; then fatal "unsafe rollback accepted: $change"; fi
  done
  baseline=$(sed -e "s/^rev=.*/rev=$accepted_rev/" -e "s/^mode=.*/mode=$accepted_mode/" -e "s/^proto=.*/proto=$accepted_mode/" \
    -e "s/^builder_commit=.*/builder_commit=$accepted_builder/" <<< "$s")
  if [[ $reboot_1g == 1 ]]; then
    baseline=$(sed -e 's/^lan_speed=.*/lan_speed=2500/' -e 's/^direct_peer_speed=.*/direct_peer_speed=2500/' <<< "$baseline")
    for change in direct_peer_speed=2500 direct_peer_speed=absent; do
      bad=$(sed "s/^direct_peer_speed=.*/$change/" <<< "$s")
      if healthy "$bad"; then fatal "wrong peer speed accepted: $change"; fi
    done
    if healthy "$(sed '/^direct_peer_speed=/d' <<< "$s")"; then fatal 'missing peer speed accepted'; fi
  fi
  if [[ $trunk_trial == 1 ]]; then
    baseline=$(sed -e "s/^module_sha=.*/module_sha=$accepted_module_sha/" -e "s/^module_rom_sha=.*/module_rom_sha=$accepted_module_sha/" -e "s/^module_taint=.*/module_taint=$accepted_module_taint/" -e "s/^manifest_module_sha=.*/manifest_module_sha=$accepted_module_sha/" <<< "$baseline")
    for change in module_sha=wrong module_rom_sha=wrong manifest_module_sha=wrong module_live=0 module_upper_clear=0 module_taint= switch_verified=0 direct_verified=0 local_ready=0 cpu_fcs=missing; do
      field=${change%%=*}
      bad=$(sed "s|^$field=.*|$change|" <<< "$s")
      if healthy "$bad"; then fatal "bad trunk state accepted $change"; fi
    done
  fi
  if [[ $phy_trial == 1 ]]; then
    baseline=$(sed -e "s/^manifest_phy_patch=.*/manifest_phy_patch=$accepted_phy_patch/" -e "s/^manifest_fit_sha=.*/manifest_fit_sha=$accepted_fit_sha/" -e "s/^phy_poll_marker=.*/phy_poll_marker=$accepted_phy_marker/" <<< "$baseline")
  fi
  if [[ $kernel_variant_trial == 1 ]]; then
    baseline=$(sed -e 's/^manifest_clock_patch=.*/manifest_clock_patch=/' -e 's/^manifest_instant_patch=.*/manifest_instant_patch=/' -e 's/^instant_fifo_marker=.*/instant_fifo_marker=0/' -e 's/^manifest_worker_patch=.*/manifest_worker_patch=/' -e 's/^fifo_worker_marker=.*/fifo_worker_marker=0/' -e 's/^manifest_down_patch=.*/manifest_down_patch=/' <<< "$baseline")
  fi
  if [[ $relink_trial == 1 ]]; then
    baseline=$(sed -e "s/^pcs_sha=.*/pcs_sha=$accepted_pcs_sha/" -e "s/^pcs_rom_sha=.*/pcs_rom_sha=$accepted_pcs_sha/" -e "s/^ppe_sha=.*/ppe_sha=$accepted_ppe_sha/" -e "s/^ppe_rom_sha=.*/ppe_rom_sha=$accepted_ppe_sha/" -e 's/^manifest_pcs_sha=.*/manifest_pcs_sha=/' -e 's/^manifest_ppe_sha=.*/manifest_ppe_sha=/' -e 's/^manifest_relink_patch=.*/manifest_relink_patch=/' -e 's/^manifest_serial_patch=.*/manifest_serial_patch=/' <<< "$baseline")
    for field in pcs_sha pcs_rom_sha pcs_live pcs_taint ppe_sha ppe_rom_sha ppe_live ppe_taint manifest_pcs_sha manifest_ppe_sha manifest_relink_patch manifest_serial_patch manifest_phy_patch manifest_fit_sha phy_poll_marker; do
      for replacement in wrong MISSING; do
        if [[ $replacement == MISSING ]]; then
          bad=$(sed "/^$field=/d" <<< "$s")
          bad_baseline=$(sed "/^$field=/d" <<< "$baseline")
        else
          bad=$(sed "s/^$field=.*/$field=$replacement/" <<< "$s")
          bad_baseline=$(sed "s/^$field=.*/$field=$replacement/" <<< "$baseline")
        fi
        if healthy "$bad" || baseline_healthy "$bad_baseline"; then fatal "bad relink identity accepted: $field $replacement"; fi
      done
    done
  fi
  if [[ $kernel_variant_trial == 1 ]]; then
    for field in manifest_clock_patch manifest_instant_patch instant_fifo_marker manifest_worker_patch fifo_worker_marker manifest_down_patch; do
      for replacement in wrong MISSING; do
        if [[ $replacement == MISSING ]]; then
          bad=$(sed "/^$field=/d" <<< "$s")
          bad_baseline=$(sed "/^$field=/d" <<< "$baseline")
        else
          bad=$(sed "s/^$field=.*/$field=$replacement/" <<< "$s")
          bad_baseline=$(sed "s/^$field=.*/$field=$replacement/" <<< "$baseline")
        fi
        if healthy "$bad" || baseline_healthy "$bad_baseline"; then fatal "bad kernel variant identity accepted: $field $replacement"; fi
      done
    done
    bad=$(sed "s/^instant_fifo_marker=.*/instant_fifo_marker=$((1-candidate_instant_marker))/" <<< "$s")
    if healthy "$bad"; then fatal 'wrong instantaneous FIFO marker accepted'; fi
    bad=$(sed "s/^fifo_worker_marker=.*/fifo_worker_marker=$((1-candidate_worker_marker))/" <<< "$s")
    if healthy "$bad"; then fatal 'wrong independent FIFO marker accepted'; fi
  fi
  baseline_healthy "$baseline" || fatal 'healthy restored baseline rejected'
  if [[ $reboot_1g == 1 ]]; then
    reboot_source_valid "$s"$'\napproval=0\ntoken=1' || fatal 'valid 1G reboot source rejected'
    for extra in $'approval=1\ntoken=1' $'approval=0\ntoken=0' approval=0 token=1; do
      if reboot_source_valid "$s"$'\n'"$extra"; then fatal 'bad 1G reboot source accepted'; fi
    done
    if reboot_source_valid "$baseline"$'\napproval=0\ntoken=1'; then fatal 'baseline accepted as 1G reboot source'; fi
    if baseline_healthy "$(sed 's/^direct_peer_speed=.*/direct_peer_speed=1000/' <<< "$baseline")"; then fatal 'rollback accepted at wrong peer speed'; fi
  fi
  if [[ -n $accepted_module_taint ]]; then
    for change in module_sha=wrong module_rom_sha=wrong manifest_module_sha=wrong module_taint=; do
      field=${change%%=*}
      bad=$(sed "s|^$field=.*|$change|" <<< "$baseline")
      if baseline_healthy "$bad"; then fatal "bad external-module rollback accepted $change"; fi
    done
  fi
  for change in bootfail=1 keep=0 q6=2 ap=1 noc=1 lan1=0 ping=0; do
    field=$(cut -d= -f1 <<< "$change")
    bad=$(sed "s|^$field=.*|$change|" <<< "$baseline")
    if baseline_healthy "$bad"; then fatal "unhealthy restore accepted: $change"; fi
  done
  lease_valid '200 70:5a:6f:5a:bb:14 192.168.76.1 test *' 100 || fatal 'valid lease rejected'
  for bad in '99 70:5a:6f:5a:bb:14 192.168.76.1 test *' '200 00:00:00:00:00:00 192.168.76.1 test *' '200 70:5a:6f:5a:bb:14 192.168.76.2 test *' ''; do
    if lease_valid "$bad" 100; then fatal 'wrong lease accepted'; fi
  done
  # Exercise the identity gate without depending on a real upstream service.
  good="$s"
  good=$(sed '/^local_ready=/d' <<< "$good")
  good+=$'\napproval=1\ntoken=0\nlocal_ready=1'
  autonomous_approval_ok "$good" || fatal 'autonomous approval rejected'
  if [[ $profile == static ]]; then
    autonomous_healthy "$good" || fatal 'autonomous healthy state rejected'
  fi
  for change in approval=0 token=1 local_ready=0; do
    field=${change%%=*}
    bad=$(sed "s|^$field=.*|$change|" <<< "$good")
    if autonomous_approval_ok "$bad"; then fatal "autonomous false positive: $change"; fi
  done
  if [[ $trunk_trial == 1 ]]; then
    sample="$s"$'\nuptime=42'
    [[ $(trunk_counter_row "$sample" 123 boot) == $'123\tboot\t42\t0\t0\t1\t1\t1\t0\t1\t1' ]] ||
      fatal 'counter row mismatch'
    [[ $(trunk_error_key "$sample") == 0:0:0 ]] || fatal 'counter key mismatch'
    bad=$(sed 's/^cpu_fcs=.*/cpu_fcs=missing/' <<< "$sample")
    if trunk_counter_row "$bad" 123 boot >/dev/null; then fatal 'malformed counter accepted'; fi
  fi
  if restore_profile; then
    restore_source_valid "$s"$'\napproval=0' || fatal 'failed experiment restore source rejected'
    if restore_source_valid "$s"$'\napproval=1' || restore_source_valid "$baseline"$'\napproval=0'; then
      fatal 'invalid restore source accepted'
    fi
    uuid=12345678-1234-1234-1234-123456789abc
    record=$'be5e8dc71ca78591010165da43e4408dfe5c6234a07ec7addc821bda77023972  /overlay/wave7-ap-approved\n'"$uuid"
    restore_record_matches "$record" "$uuid" || fatal 'pinned approval rejected'
    if restore_record_matches "$record" 00000000-0000-0000-0000-000000000000 ||
       restore_record_matches "bad$record" "$uuid"; then
      fatal 'incorrect approval accepted'
    fi
    restore_target_valid "$baseline"$'\napproval=1\ntoken=0' || fatal 'autonomous restore rejected'
    if restore_target_valid "$baseline"$'\napproval=0\ntoken=0' ||
       restore_target_valid "$baseline"$'\napproval=1\ntoken=1' ||
       restore_target_valid "$s"$'\napproval=1\ntoken=0'; then
      fatal 'invalid restored approval accepted'
    fi
  fi
  echo "AP_GUARD8_SELFTEST_PASS profile=$trial_kind"
  exit 0
fi
[[ $(id -un) == jan && -r $known && -r $key ]] || fatal 'Asus jan SSH identity absent'
test -x "$attestor" ||
  fatal 'independent key-only management attestor not installed'
"$attestor" --selftest ||
  fatal 'management attestor selftest failed'

# Serialize observer arming/setup against active upstream wire tests.
# The persistent systemd observers guard the interval after this caller
# exits; the wire test also checks their active/activating state.
if [[ $mode == --run || $mode == --arm-reboot || $mode == --restore-baseline || $mode == --reboot-1g ]]; then
  lock="$guard8/.lab-control.lock"
  [[ -f $lock && ! -L $lock && -O $lock ]] ||
    fatal 'missing or invalid lab-control lock (initialize once as Jan)'
  exec 8<>"$lock"
  flock -n 8 || fatal 'lab control held by another trial/setup or wire test'
fi

# Read-only SSH observation of a new approved boot; intentionally no
# attestor, upload, sysupgrade or manual bootfail/keep modification.
if [[ $mode == --observe-reboot ]]; then
  [[ $# == 2 ]] || fatal 'reboot observer requires predecessor and run directory'
  old_boot=$1
  out=$2
  [[ $old_boot =~ ^[0-9a-f-]{36}$ && $out == "$base"/runs/autonomous-* ]] ||
    fatal 'invalid reboot observation arguments'
  exec 9>"$out/.watch.lock"
  flock -n 9 || fatal 'observer already running'
  log() { echo "$(date -Is) $*" | tee -a "$out/observer.log"; }
  finish() { log "$1"; echo "$1" > "$out/status"; exit "${2:-0}"; }
  log "ARMED predecessor=$old_boot"
  echo ARMED > "$out/status"
  new_boot=
  healthy_since=0
  last_errors=''
  if [[ $trunk_trial == 1 ]]; then
    trunk_counter_header > "$out/trunk-counters.tsv"
  fi
  deadline=$(( $(date +%s) + 900 ))
  until (( $(date +%s) >= deadline )); do
    if s=$(read_state 2>/dev/null); then
      boot=$(value "$s" boot)
      rev=$(value "$s" rev)
      [[ $boot =~ ^[0-9a-f-]{36}$ ]] || { sleep 3; continue; }
      if [[ $(value "$s" kernel) == 5.4.213 ]]; then
        finish VENDOR_FALLBACK 4
      elif [[ $boot == "$old_boot" ]]; then
        [[ -z $new_boot ]] || finish PREDECESSOR_REAPPEARED 5
      else
        printf '%s\n' "$s" > "$out/latest-state.txt"
        [[ $rev == "$candidate_rev" ]] || finish WRONG_REVISION 5
        if [[ -z $new_boot ]]; then
          new_boot=$boot
          log "NEW_BOOT boot=$boot"
        fi
        [[ $new_boot == "$boot" ]] || finish UNEXPECTED_REBOOT 5
        [[ $(value "$s" token) == 0 ]] || finish EXTERNAL_TOKEN_DETECTED 5
        [[ $(value "$s" noc) == 0 ]] || finish NOC_FATAL 5
        now=$(date +%s)
        if [[ $trunk_trial == 1 ]] && trunk_counter_row "$s" "$now" "$boot" >> "$out/trunk-counters.tsv"; then
          errors=$(trunk_error_key "$s")
          if [[ -n $last_errors && $errors != "$last_errors" ]]; then
            log "TRUNK_ERROR_COUNTER_CHANGE $last_errors->$errors"
            healthy_since=0
          fi
          last_errors=$errors
        fi
        if autonomous_healthy "$s"; then
          if (( healthy_since == 0 )); then
            healthy_since=$now
            log "AUTONOMOUS_ACCEPTED boot=$boot uptime=$(value "$s" uptime)"
            cp "$out/latest-state.txt" "$out/first-healthy-state.txt"
            echo SOAKING > "$out/status"
          fi
          if (( now-healthy_since >= 300 )); then
            log "AUTONOMOUS_SOAK_PASS seconds=$((now-healthy_since))"
            echo SOAK_PASS > "$out/status"
            exit 0
          fi
        else
          healthy_since=0
          log "WAIT uptime=$(value "$s" uptime) approval=$(value "$s" approval) keep=$(value "$s" keep) q6=$(value "$s" q6) ap=$(value "$s" ap)"
          echo WAITING > "$out/status"
        fi
      fi
    else
      healthy_since=0
    fi
    sleep 3
  done
  finish WATCH_TIMEOUT 6
fi

if [[ $mode == --arm-reboot ]]; then
  [[ $# == 0 ]] || fatal 'reboot arming takes no extra arguments'
  s=$(read_state) || fatal 'router inaccessible'
  boot=$(value "$s" boot)
  [[ $boot =~ ^[0-9a-f-]{36}$ ]] || fatal 'invalid predecessor'
  candidate_healthy "$s" && grep -Fxq approval=1 <<< "$s" &&
    grep -Fxq local_ready=1 <<< "$s" || fatal 'predecessor not approved and healthy'
  for name in wave7-q6-devcoredump-capture wave7-q6-noc-kmsg wave7-q6-noc-events; do
    systemctl --user is-active --quiet "$name.service" || fatal "$name inactive"
  done
  test -z "$(systemctl --user --no-pager --no-legend list-units --state=active 'wave7-openwrt-watch-*' 'wave7-fallback-watch-*' 'wave7-napi-supervisor-*' 'wave7-qdss-supervisor-*' 'wave7-secondary-ap-supervisor-*' 'wave7-integrated-supervisor-*' 'wave7-autonomous-observer-*')" || fatal 'another supervisor active'
  tag=autonomous-$(date +%Y%m%d-%H%M%S)
  out="$base/runs/$tag"
  mkdir -m 0700 "$out"
  printf '%s\n' "$s" > "$out/preflight.txt"
  guard="wave7-autonomous-observer-$tag"
  fallback="wave7-fallback-watch-$tag"
  armed=0
  cleanup_arm() {
    if (( !armed )); then
      systemctl --user stop "$guard.service" "$fallback.service" >/dev/null 2>&1 || :
      echo ABORTED_PRE_REBOOT > "$out/status"
    fi
  }
  trap cleanup_arm EXIT
  systemd-run --user --quiet --unit="$guard" --property=RuntimeMaxSec=950 -- \
    /home/jan/scripts/wave7/secondary-ap-guard8/trial-ap.sh "$trial_kind" --observe-reboot "$boot" "$out"
  systemd-run --user --quiet --unit="$fallback" --property=RuntimeMaxSec=1000 -- \
    /home/jan/scripts/wave7/wave7-fallback-watch.sh "$tag"
  await_observers "$guard" "$fallback" "$out"
  armed=1
  echo "REBOOT_OBSERVERS_ARMED predecessor=$boot RUN_DIR=$out"
  exit 0
fi
if [[ $mode == --watch || $mode == --watch-restore ]]; then
  if [[ $mode == --watch-restore ]] && ! restore_profile; then
    fatal 'explicit restore restricted to failed 0492/0493/0494/0495/0496'
  fi
  [[ $# == 2 ]] || fatal 'watch requires old boot and directory'
  old_boot=$1
  out=$2
  [[ $old_boot =~ ^[0-9a-f-]{36}$ && $out == "$base"/runs/* ]] || fatal 'invalid watch parameters'
  mkdir -p "$out"
  exec 9>"$out/.watch.lock"
  flock -n 9 || fatal 'supervisor already running'
  log() { echo "$(date -Is) $*" | tee -a "$out/observer.log"; }
  log "ARMED predecessor=$old_boot"
  echo ARMED > "$out/status"
  trial_boot=''
  first_seen=0
  healthy_since=0
  last_attest=0
  attested=0
  rollback=0
  rollback_cause=''
  last_restore_attempt=0
  restored_boot=""
  restore_attested=0
  last_restore_attest=0
  last_errors=''
  if [[ $trunk_trial == 1 ]]; then
    trunk_counter_header > "$out/trunk-counters.tsv"
  fi
  restore() {
    local cause=$1 state=$2 check
    (( rollback == 0 )) || return 0
    # Remember the observed fault even if this boot has not been accepted.
    # Do not latch a restore as issued merely because it was requested.
    rollback_cause=$cause
    if ! rollback_eligible "$state"; then
      log ROLLBACK_DEFERRED_UNACCEPTED_BOOT
      return 1
    fi
    (( now-last_restore_attempt >= 15 )) || return 1
    last_restore_attempt=$now
    log "ROLLBACK_REQUESTED cause=$cause"
    echo ROLLBACK_REQUESTED > "$out/status"
    remote 'echo ====BOOT====; cat /proc/sys/kernel/random/boot_id; echo ====DMESG====; dmesg; echo ====ETHERNET====; ethtool lan1' > "$out/pre-rollback.txt" 2>&1 || :
    upload "$accepted" /tmp/wave7-secondary-ap-restore.bin || { log RESTORE_COPY_FAILED; return 1; }
    check=$(remote 'sha256sum /tmp/wave7-secondary-ap-restore.bin; /sbin/sysupgrade -T -n /tmp/wave7-secondary-ap-restore.bin') || { log RESTORE_PREFLIGHT_FAILED; return 1; }
    [[ $check == "$accepted_sha  /tmp/wave7-secondary-ap-restore.bin"* ]] || { log RESTORE_SHA_FAILED; return 1; }
    log RESTORE_NATIVE_SYSUPGRADE
    remote_timed '/sbin/sysupgrade -n /tmp/wave7-secondary-ap-restore.bin' > "$out/restore.log" 2>&1 || :
    # Once the remote operation may have started, never issue a blind
    # duplicate NAND write. Await the next verified healthy boot.
    rollback=1
    echo RESTORE_ISSUED > "$out/status"
  }
  for ((i=0;i<410;i++)); do
    now=$(date +%s)
    if s=$(read_state 2>/dev/null); then
      boot=$(value "$s" boot)
      rev=$(value "$s" rev)
      [[ $boot =~ ^[0-9a-f-]{36}$ ]] || { sleep 3; continue; }
      if [[ $(value "$s" kernel) == 5.4.213 ]]; then
        log "VENDOR_FALLBACK boot=$boot"; echo VENDOR_FALLBACK > "$out/status"; exit 4
      elif [[ $boot == "$old_boot" ]]; then
        (( i % 10 )) || log STILL_ORIGINAL_BOOT
      elif [[ $rev == "$accepted_rev" ]]; then
        if [[ $restored_boot != "$boot" ]]; then
          restored_boot=$boot; restore_attested=0; last_restore_attest=0
          log "ROLLBACK_BOOT boot=$boot"
        fi
        if [[ $mode != --watch-restore ]] &&
           (( !restore_attested && now-last_restore_attest >= 4 )) && [[ $(value "$s" keep) == 0 ]]; then
          last_restore_attest=$now
          if "$attestor" --run 192.168.76.1 "$accepted_rev" "$management_iface" "$management_ip" "$known" > "$out/restore-attestation.log" 2>&1; then
            restore_attested=1; log "ROLLBACK_MANAGEMENT_ATTESTED boot=$boot"
          fi
        fi
        if baseline_healthy "$s"; then
          if [[ $mode == --watch-restore ]] &&
             { ! restore_target_valid "$s" ||
               ! lease_valid "$(cat "$leasefile" 2>/dev/null || :)" "$now"; }; then
            log WAIT_RESTORED_APPROVAL_OR_LEASE
            sleep 3
            continue
          fi
          printf '%s\n' "$s" > "$out/restored-state.txt"
          log "ACCEPTED_IMAGE_BOOT_HEALTHY boot=$boot"
          echo RESTORED > "$out/status"
          exit 0
        fi
        (( i % 5 )) || log "WAIT_RESTORED_BASELINE_READY boot=$boot"
      elif [[ $mode == --watch-restore ]]; then
        log "WRONG_RESTORE_REVISION rev=$rev boot=$boot"
        echo WRONG_REVISION > "$out/status"
        exit 5
      elif [[ $rev == "$candidate_rev" ]]; then
        if [[ $trial_boot != "$boot" ]]; then
          if [[ $trunk_trial == 1 && -n $trial_boot ]]; then
            log "UNEXPECTED_REBOOT predecessor=$trial_boot new=$boot"
            rollback_cause=UNEXPECTED_REBOOT
          fi
          trial_boot=$boot; first_seen=$now; healthy_since=0
          last_attest=0; attested=0; last_errors=''
          log "TRIAL_BOOT boot=$boot"
        fi
        printf '%s\n' "$s" > "$out/latest-state.txt"
        if [[ $trunk_trial == 1 ]] && trunk_counter_row "$s" "$now" "$boot" >> "$out/trunk-counters.tsv"; then
          errors=$(trunk_error_key "$s")
          if [[ -n $last_errors && $errors != "$last_errors" ]]; then
            log "TRUNK_ERROR_COUNTER_CHANGE $last_errors->$errors"
            healthy_since=0
          fi
          last_errors=$errors
        fi
        # Authenticated AP preinit cannot commit bootfail=0 without this
        # independent key-only SSH check. Retry during the early boot; do
        # not bypass the 120-second hard deadline if no valid token arrives.
        if (( !attested && now-first_seen < 98 && now-last_attest >= 4 )) &&
           [[ $(value "$s" keep) == 0 ]]; then
          if [[ $trunk_trial == 1 ]] &&
             { [[ -n $rollback_cause ]] || ! module_matches "$s" "$candidate_module_sha" O || ! grep -Fxq "manifest_module_sha=$candidate_module_sha" <<< "$s"; }; then
            log TRUNK_ATTESTATION_BLOCKED_MODULE_OR_REBOOT
            sleep 3
            continue
          fi
          if [[ $phy_trial == 1 ]] && ! phy_matches "$s" "$candidate_phy_patch" "$candidate_fit_sha" 1; then
            log PHY_ATTESTATION_BLOCKED_IDENTITY
            sleep 3
            continue
          fi
          if [[ $relink_trial == 1 ]] && ! relink_matches "$s" "$candidate_pcs_sha" "$candidate_ppe_sha" "$candidate_relink_patch" "$candidate_down_patch" "$candidate_serial_patch"; then
            log RELINK_ATTESTATION_BLOCKED_IDENTITY
            sleep 3
            continue
          fi
          if [[ $kernel_variant_trial == 1 ]] &&
             ! kernel_variant_matches "$s" "$candidate_clock_patch" "$candidate_instant_patch" "$candidate_instant_marker" "$candidate_worker_patch" "$candidate_worker_marker" "$candidate_down_patch"; then
            log KERNEL_VARIANT_ATTESTATION_BLOCKED_IDENTITY
            sleep 3
            continue
          fi
          last_attest=$now
          if "$attestor" --run \
            192.168.76.1 "$candidate_rev" "$management_iface" "$management_ip" "$known" \
            > "$out/attestation-latest.log" 2>&1; then
            attested=1
            log "MANAGEMENT_ATTESTED boot=$boot"
            cp "$out/attestation-latest.log" "$out/attestation-success.log"
          elif (( i % 5 == 0 )); then
            log "MANAGEMENT_ATTESTATION_PENDING"
          fi
        fi
        if (( rollback )); then
          (( i % 10 )) || log AWAITING_RESTORE
        elif [[ -n $rollback_cause ]]; then
          restore "$rollback_cause" "$s" || :
        elif candidate_healthy "$s"; then
          if (( healthy_since == 0 )); then
            healthy_since=$now; log FIRST_HEALTHY; echo SOAKING > "$out/status"
          fi
          if (( now-healthy_since >= 300 )); then
            log "SOAK_PASS seconds=$((now-healthy_since))"
            echo SOAK_PASS > "$out/status"
            exit 0
          fi
        else
          healthy_since=0
          if [[ $(value "$s" noc) =~ ^[1-9][0-9]*$ ]]; then
            restore NOC_FATAL "$s" || :
          elif (( now-first_seen > 165 )) && [[ $(value "$s" keep) == 1 && $(value "$s" bootfail) == 0 ]]; then
            # Preserve the exact observed reason, including host-side
            # lab policy; do not report induced upstream loss as a port
            # failure. The strict rollback criterion is unchanged.
            printf '%s\n' "$s" > "$out/unhealthy-state.txt"
            if [[ $profile == dhcp ]] &&
               ! systemctl is-active --quiet "$upstream_unit.service"; then
              restore LAB_UPSTREAM_UNAVAILABLE "$s" || :
            elif [[ $profile == dhcp ]] &&
                 ! lease_valid "$(cat "$leasefile" 2>/dev/null || :)" "$now"; then
              restore LAB_MANAGEMENT_LEASE_INVALID "$s" || :
            else
              restore UNHEALTHY_PORT_OR_RADIO "$s" || :
            fi
          elif (( i % 5 == 0 )); then
            log "WAIT q6=$(value "$s" q6) ap=$(value "$s" ap) lan1=$(value "$s" lan1) bridge=$(value "$s" bridge)"
          fi
        fi
      else
        log "UNKNOWN_REVISION rev=$rev boot=$boot"
        echo UNKNOWN_REVISION > "$out/status"
        exit 5
      fi
    else
      healthy_since=0
      (( i % 10 )) || log ROUTER_UNREACHABLE
    fi
    sleep 3
  done
  log WATCH_TIMEOUT
  echo TIMEOUT > "$out/status"
  exit 6
fi
[[ $mode == --check || $mode == --check-baseline || $mode == --run || $mode == --restore-baseline || $mode == --check-reboot-1g || $mode == --reboot-1g ]] ||
  fatal "unknown mode $mode"
if [[ $mode == --restore-baseline ]]; then
  restore_profile && [[ $# == 0 ]] || fatal 'restore is only for failed 0492/0493/0494/0495/0496/0497/0498'
fi
[[ -r $accepted ]] || fatal 'missing accepted rollback'
[[ $(sha256sum "$accepted" | cut -d' ' -f1) == "$accepted_sha" ]] || fatal 'accepted SHA mismatch'
[[ $(tar xOf "$accepted" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || fatal 'wrong accepted board'
if [[ $mode != --check-baseline ]]; then
  [[ $candidate_sha == "$expected_candidate_sha" ]] || fatal 'candidate digest not pinned by final QA'
  [[ -r $candidate ]] || fatal 'candidate image missing'
  [[ $(sha256sum "$candidate" | cut -d' ' -f1) == "$candidate_sha" ]] || fatal 'candidate SHA mismatch'
  [[ $(tar xOf "$candidate" sysupgrade-acer_wave7/CONTROL) == BOARD=acer_wave7 ]] || fatal 'wrong candidate board'
fi
has_permanent_address "$(ip -4 -o addr show dev enp4s0f4u2u4)" 192.168.76.2/24 ||
  fatal 'permanent Asus 2.5GbE .2 peer absent'
has_permanent_address "$(ip -4 -o addr show dev "$management_iface")" "$management_ip/24" ||
  fatal 'permanent independent 1GbE management address absent'
[[ $(cat "/sys/class/net/$management_iface/carrier") == 1 ]] || fatal 'management carrier down'
s=$(read_state) || fatal 'router inaccessible'
boot=$(value "$s" boot)
[[ $boot =~ ^[0-9a-f-]{36}$ ]] || fatal 'invalid boot ID'
if [[ $mode == --restore-baseline ]]; then
  restore_source_valid "$s" || fatal "unhealthy or approved failed-experiment source: $s"
  # 0491 persisted approval record is pinned to the exact parent image
  # manifest SHA, independently extracted from its verified squashfs.
  record=$(remote 'set -eu; p=/overlay/wave7-ap-approved; test -f "$p"; test ! -L "$p"; set -- $(ls -ldn "$p"); test "$1" = -rw-------; test "$3" = 0; test "$4" = 0; sha256sum "$p"; cat /proc/sys/kernel/random/boot_id') ||
    fatal 'missing stored 0491 approval'
  restore_record_matches "$record" "$boot" ||
    fatal 'stored 0491 approval identity or source boot mismatch'
elif [[ $reboot_1g == 1 ]]; then
  reboot_source_valid "$s" ||
    fatal "1G trial reboot requires exact unapproved healthy candidate: $s"
  /home/jan/scripts/wave7/secondary-ap-guard8/peer-1g-window.sh --check ||
    fatal 'bounded 1G peer window not ready'
  record=$(remote 'set -eu; p=/overlay/wave7-ap-approved; test -f "$p"; test ! -L "$p"; set -- $(ls -ldn "$p"); test "$1" = -rw-------; test "$3" = 0; test "$4" = 0; sha256sum "$p"; cat /proc/sys/kernel/random/boot_id') ||
    fatal 'missing stored 0491 approval'
  restore_record_matches "$record" "$boot" ||
    fatal 'stored 0491 approval identity or source boot mismatch'
else
  baseline_healthy "$s" || fatal "unhealthy source: $s"
  if [[ $profile == dhcp ]]; then
    grep -Fxq approval=1 <<< "$s" || fatal 'rollback not persistently approved'
  fi
fi
if [[ $profile == dhcp ]]; then
  upstream_ready || fatal 'isolated upstream service not ready'
  if [[ $trunk_trial == 1 ]]; then
    lease_valid "$(cat "$leasefile" 2>/dev/null || :)" "$(date +%s)" || fatal 'approved DHCP rollback lease absent'
    has_permanent_address "$(ip -4 -o addr show dev "$switch_iface")" "$switch_ip/24" || fatal 'independent switch peer address absent'
    [[ $(cat "/sys/class/net/$switch_iface/carrier") == 1 ]] || fatal 'switch peer carrier down'
  elif lease_valid "$(cat "$leasefile" 2>/dev/null || :)" "$(date +%s)"; then
    fatal 'stale router DHCP lease already present'
  fi
fi
for name in wave7-q6-devcoredump-capture wave7-q6-noc-kmsg wave7-q6-noc-events; do
  systemctl --user is-active --quiet "$name.service" || fatal "$name inactive"
done
test -z "$(systemctl --user --no-pager --no-legend list-units --state=active 'wave7-openwrt-watch-*' 'wave7-fallback-watch-*' 'wave7-napi-supervisor-*' 'wave7-qdss-supervisor-*' 'wave7-secondary-ap-supervisor-*' 'wave7-integrated-supervisor-*' 'wave7-autonomous-observer-*')" || fatal 'another supervisor active'
echo "PREFLIGHT_PASS predecessor=$boot candidate=$candidate_sha mode=$mode"
[[ $mode == --run || $mode == --restore-baseline || $mode == --reboot-1g ]] || exit 0
if [[ $mode == --restore-baseline ]]; then
  tag=restore-0491-$(date +%Y%m%d-%H%M%S)
elif [[ $mode == --reboot-1g ]]; then
  tag=reboot-1g-$(date +%Y%m%d-%H%M%S)
else
  tag=secondary-ap-$(date +%Y%m%d-%H%M%S)
fi
out="$base/runs/$tag"
mkdir -p "$out"
printf '%s\n' "$s" > "$out/preflight.txt"
watch_mode=--watch
flash_image=/tmp/wave7-secondary-ap-trial.bin
pairs=("$candidate|$flash_image|$candidate_sha" "$accepted|/tmp/wave7-secondary-ap-baseline.bin|$accepted_sha")
if [[ $mode == --restore-baseline ]]; then
  watch_mode=--watch-restore
  flash_image=/tmp/wave7-secondary-ap-restore.bin
  pairs=("$accepted|$flash_image|$accepted_sha")
fi
if [[ $mode == --reboot-1g ]]; then
  # Reboot the exact already-running candidate; do not rewrite NAND.
  pairs=("$accepted|/tmp/wave7-secondary-ap-baseline.bin|$accepted_sha")
  watch_mode=--watch-reboot-1g
fi
for pair in "${pairs[@]}"; do
  IFS='|' read -r source dest digest <<< "$pair"
  upload "$source" "$dest"
  check=$(remote "sha256sum '$dest'; /sbin/sysupgrade -T -n '$dest'")
  [[ $check == "$digest  $dest"* ]] || fatal "remote sysupgrade check failed: $dest"
done
guard="wave7-secondary-ap-supervisor-$tag"
fallback="wave7-fallback-watch-$tag"
flash_started=0
cleanup() {
  local rc=$?
  if (( rc != 0 && !flash_started )); then
    systemctl --user stop "$guard.service" "$fallback.service" >/dev/null 2>&1 || :
    echo ABORTED_PRE_FLASH > "$out/status"
  fi
}
trap cleanup EXIT
systemd-run --user --quiet --unit="$guard" --property=RuntimeMaxSec=1500 -- \
  /home/jan/scripts/wave7/secondary-ap-guard8/trial-ap.sh "$trial_kind" "$watch_mode" "$boot" "$out"
systemd-run --user --quiet --unit="$fallback" --property=RuntimeMaxSec=1500 -- \
  /home/jan/scripts/wave7/wave7-fallback-watch.sh "$tag"
await_observers "$guard" "$fallback" "$out"
echo "GUARDS_ARMED $tag"
[[ $(remote 'cat /proc/sys/kernel/random/boot_id') == "$boot" ]] ||
  fatal 'source changed after observer arming'
if [[ $mode == --reboot-1g ]]; then
  /home/jan/scripts/wave7/secondary-ap-guard8/peer-1g-window.sh --check ||
    fatal 'peer window changed before reboot'
fi
flash_started=1
if [[ $mode == --reboot-1g ]]; then
  # Until both guards are armed, the only operation is a verified
  # rollback upload. Observe a new boot, never persist approval.
  set +e
  remote_timed 'sync; /sbin/reboot' > "$out/reboot.log" 2>&1
  rc=$?
  set -e
  echo "REBOOT_SSH_RC=$rc" | tee -a "$out/reboot.log"
  echo "RUN_DIR=$out"
  exit 0
fi
set +e
remote_timed "/sbin/sysupgrade -n '$flash_image'" > "$out/sysupgrade.log" 2>&1
rc=$?
set -e
echo "FLASH_SSH_RC=$rc" | tee -a "$out/sysupgrade.log"
if ! grep -q 'Commencing upgrade\. Closing all shell sessions\.' "$out/sysupgrade.log"; then
  # A refused upgrade must not be treated as an attempted flash.
  flash_started=0
  fatal "sysupgrade did not reach its actual upgrade stage"
fi
echo "RUN_DIR=$out"
