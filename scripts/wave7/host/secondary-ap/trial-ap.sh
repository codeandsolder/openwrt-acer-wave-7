#!/usr/bin/env bash
# Independent Asus guarded native trial; explicit candidate role.
set -Eeuo pipefail
umask 077
(( $# >= 2 )) || { echo "usage: $0 static|dhcp|trunk --selftest|--check|--check-baseline|--run|--arm-reboot" >&2; exit 2; }
trial_kind=$1; profile=$1; mode=$2; shift 2
root=/home/jan/firmware/wave7/trials
guard8="$root/20261120-secondary-ap-guard8"
candidate_builder=13d84dd2b19cdfd2e7d52bbe107581eaf0ddda4b
candidate_rev="r0+38346-0fbc2cc77b-ap-$profile-guard8"
accepted_mode=static
accepted_builder=''
candidate_module_sha=''
accepted_module_sha=''
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
  *) echo 'unknown candidate profile' >&2; exit 2 ;;
esac
candidate="$base/wave7-secondary-ap-$profile-guard8-sysupgrade.bin"
[[ $trial_kind != trunk ]] || candidate="$base/wave7-trunk-health-dhcp-guard8-sysupgrade.bin"
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
if [[ $trial_kind == trunk ]]; then
  # RTL8367D is the device under test, not a reliable recovery path.
  management_ip=192.168.76.2
  management_iface=enp4s0f4u2u4
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
# Read the suspect switch counters through the independent direct path.
# The second key-authenticated session must traverse the actual switch NIC.
read_state() {
  local s extra peer boot
  s=$(read_state_core) || return 1
  printf '%s\n' "$s"
  [[ $trial_kind == trunk && $(value "$s" kernel) == 6.18.60 ]] || return 0
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
    ethtool -S switch 2>/dev/null | awk '\''$1=="s00_p06_dot3StatsFCSErrors:"{print "cpu_fcs=" $2}
      $1=="s00_p06_etherStatsFragments:"{print "cpu_fragments=" $2}
      $1=="s00_p06_ifInUcastPkts:"{print "cpu_ucast=" $2}
      $1=="s00_p06_ifInMulticastPkts:"{print "cpu_mcast=" $2}
      $1=="s00_p06_ifInBroadcastPkts:"{print "cpu_bcast=" $2}
      $1=="s00_p06_etherStatsDropEvents:"{print "cpu_drops=" $2}'\''
  ') || return 1
  [[ $(value "$extra" sample_boot) == "$boot" ]] || return 1
  printf '%s\n' "$extra"
  peer=$(ssh -n -T -i "$key" -o "BindInterface=$switch_iface" -o "BindAddress=$switch_ip" \
    -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=3 -o ConnectionAttempts=1 \
    -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known" "$host" \
    'printf "%s %s\n" "$(cat /proc/sys/kernel/random/boot_id)" "${SSH_CONNECTION%% *}"' 2>/dev/null) || peer=''
  if [[ $peer == "$boot $switch_ip" ]]; then echo switch_verified=1; else echo switch_verified=0; fi
}
module_matches() {
  local s=$1 hash=$2 taint=$3
  for exp in "module_sha=$hash" "module_rom_sha=$hash" "module_taint=$taint" module_live=1 module_upper_clear=1; do
    grep -Fxq "$exp" <<< "$s" || return 1
  done
}
trunk_counters_valid() {
  local s=$1 field
  for field in cpu_fcs cpu_fragments cpu_ucast cpu_mcast cpu_bcast cpu_drops; do
    [[ $(value "$s" "$field") =~ ^[0-9]+$ ]] || return 1
  done
}
trunk_path_healthy() {
  grep -Fxq switch_verified=1 <<< "$1" &&
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
  role_healthy "$1" "$accepted_rev" "$accepted_mode" || return 1
  if [[ -n $accepted_builder ]]; then
    grep -Fxq "builder_commit=$accepted_builder" <<< "$1" || return 1
  fi
  if [[ $trial_kind == trunk ]]; then
    module_matches "$1" "$accepted_module_sha" "" && trunk_path_healthy "$1"
  fi
}
rollback_eligible() {
  local s=$1
  [[ $(value "$s" rev) == "$candidate_rev" &&
     $(value "$s" keep) == 1 && $(value "$s" bootfail) == 0 ]]
}
healthy() {
  role_healthy "$1" "$candidate_rev" "$profile" &&
    grep -Fxq "builder_commit=$candidate_builder" <<< "$1" || return 1
  if [[ $trial_kind == trunk ]]; then
    module_matches "$1" "$candidate_module_sha" O &&
      grep -Fxq "manifest_module_sha=$candidate_module_sha" <<< "$1" &&
      trunk_path_healthy "$1"
  fi
}
role_healthy() {
  local s=$1 expected_revision=$2 expected_mode=$3
  for expect in "rev=$expected_revision" kernel=6.18.60 "management_peer=$management_ip" bootfail=0 keep=1 ap=2 \
    q6=3 ping=1 noc=0 lan=1 lan_speed=2500 lan1=1 bridge=1 speed=1000 \
    role=secondary-ap "mode=$expected_mode" "proto=$expected_mode" bridge_ip=192.168.76.1/24 dnsmasq_disabled=1 \
    dhcpv4=disabled dhcpv6=disabled ra=disabled root_password='!' \
    password_auth=off root_password_auth=off overlay_ready=1; do
    grep -Fxq "$expect" <<< "$s" || return 1
  done
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
autonomous_healthy() {
  candidate_healthy "$1" &&
    grep -Fxq approval=1 <<< "$1" &&
    grep -Fxq token=0 <<< "$1" &&
    grep -Fxq local_ready=1 <<< "$1"
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
  if [[ $trial_kind == trunk ]]; then
    s+=$(printf '\nmodule_sha=%s\nmodule_rom_sha=%s\nmanifest_module_sha=%s\nmodule_taint=O\nmodule_live=1\nmodule_upper_clear=1\nswitch_verified=1\nlocal_ready=1\ncpu_fcs=0\ncpu_fragments=0\ncpu_ucast=1\ncpu_mcast=1\ncpu_bcast=1\ncpu_drops=0' "$candidate_module_sha" "$candidate_module_sha" "$candidate_module_sha")
  fi
  healthy "$s" || fatal 'good state rejected'
  for change in builder_commit=wrong management_peer=192.168.76.190 q6=2 ap=1 ping=0 noc=1 lan=0 lan_speed=1000 lan1=0 bridge=0 speed=2500 bootfail=4 role=lab mode=wrong proto=wrong bridge_ip=192.168.76.99/24 dnsmasq_disabled=0 dhcpv4=server dhcpv6=server ra=server root_password=notlocked password_auth=on root_password_auth=on overlay_ready=0; do
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
  if [[ $trial_kind == trunk ]]; then
    baseline=$(sed -e "s/^module_sha=.*/module_sha=$accepted_module_sha/" -e "s/^module_rom_sha=.*/module_rom_sha=$accepted_module_sha/" -e 's/^module_taint=.*/module_taint=/' <<< "$baseline")
    for change in module_sha=wrong module_rom_sha=wrong manifest_module_sha=wrong module_live=0 module_upper_clear=0 module_taint= switch_verified=0 local_ready=0 cpu_fcs=missing; do
      field=${change%%=*}
      bad=$(sed "s|^$field=.*|$change|" <<< "$s")
      if healthy "$bad"; then fatal "bad trunk state accepted $change"; fi
    done
  fi
  baseline_healthy "$baseline" || fatal 'healthy restored baseline rejected'
  for change in bootfail=1 keep=0 q6=2 ap=1 noc=1 lan1=0 ping=0; do
    field=$(cut -d= -f1 <<< "$change")
    bad=$(sed "s|^$field=.*|$change|" <<< "$baseline")
    if baseline_healthy "$bad"; then fatal "unhealthy restore accepted: $change"; fi
  done
  lease_valid '200 70:5a:6f:5a:bb:14 192.168.76.1 test *' 100 || fatal 'valid lease rejected'
  for bad in '99 70:5a:6f:5a:bb:14 192.168.76.1 test *' '200 00:00:00:00:00:00 192.168.76.1 test *' '200 70:5a:6f:5a:bb:14 192.168.76.2 test *' ''; do
    if lease_valid "$bad" 100; then fatal 'wrong lease accepted'; fi
  done
  # Test the autonomous acceptance predicate independently of the real
  # upstream service: static is sufficient to exercise its token checks.
  if [[ $profile == static ]]; then
    good="$s"$'\napproval=1\ntoken=0\nlocal_ready=1'
    autonomous_healthy "$good" || fatal 'autonomous healthy state rejected'
    for change in approval=0 token=1 local_ready=0; do
      field=${change%%=*}
      bad=$(sed "s|^$field=.*|$change|" <<< "$good")
      if autonomous_healthy "$bad"; then fatal "autonomous false positive: $change"; fi
    done
  fi
  echo "AP_GUARD8_SELFTEST_PASS profile=$trial_kind"
  exit 0
fi
[[ $(id -un) == jan && -r $known && -r $key ]] || fatal 'Asus jan SSH identity absent'
test -x "$attestor" ||
  fatal 'independent key-only management attestor not installed'
"$attestor" --selftest ||
  fatal 'management attestor selftest failed'

# Read-only SSH observation of a new approved boot; intentionally no
# attestor, upload, sysupgrade or manual bootfail/keep modification.
if [[ $mode == --observe-reboot ]]; then
  [[ $# == 2 && $profile == static ]] || fatal 'static reboot observer requires predecessor and run directory'
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
  [[ $profile == static && $# == 0 ]] || fatal 'only approved static reboot supported'
  s=$(read_state) || fatal 'router inaccessible'
  boot=$(value "$s" boot)
  [[ $boot =~ ^[0-9a-f-]{36}$ ]] || fatal 'invalid predecessor'
  healthy "$s" && grep -Fxq approval=1 <<< "$s" &&
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
    /home/jan/scripts/wave7/secondary-ap-guard8/trial-ap.sh static --observe-reboot "$boot" "$out"
  systemd-run --user --quiet --unit="$fallback" --property=RuntimeMaxSec=1000 -- \
    /home/jan/scripts/wave7/wave7-fallback-watch.sh "$tag"
  await_observers "$guard" "$fallback" "$out"
  armed=1
  echo "REBOOT_OBSERVERS_ARMED predecessor=$boot RUN_DIR=$out"
  exit 0
fi
if [[ $mode == --watch ]]; then
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
  if [[ $trial_kind == trunk ]]; then
    printf 'wall_epoch\tboot\tuptime\tfcs\tfragments\tucast\tmcast\tbcast\tdrops\tswitch\tkeep\n' > "$out/trunk-counters.tsv"
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
        if (( !restore_attested && now-last_restore_attest >= 4 )) && [[ $(value "$s" keep) == 0 ]]; then
          last_restore_attest=$now
          if "$attestor" --run 192.168.76.1 "$accepted_rev" "$management_iface" "$management_ip" "$known" > "$out/restore-attestation.log" 2>&1; then
            restore_attested=1; log "ROLLBACK_MANAGEMENT_ATTESTED boot=$boot"
          fi
        fi
        if baseline_healthy "$s"; then
          log "ACCEPTED_IMAGE_BOOT_HEALTHY boot=$boot"
          echo RESTORED > "$out/status"
          exit 0
        fi
        (( i % 5 )) || log "WAIT_RESTORED_BASELINE_READY boot=$boot"
      elif [[ $rev == "$candidate_rev" ]]; then
        if [[ $trial_boot != "$boot" ]]; then
          if [[ $trial_kind == trunk && -n $trial_boot ]]; then
            log "UNEXPECTED_REBOOT predecessor=$trial_boot new=$boot"
            rollback_cause=UNEXPECTED_REBOOT
          fi
          trial_boot=$boot; first_seen=$now; healthy_since=0
          last_attest=0; attested=0; last_errors=''
          log "TRIAL_BOOT boot=$boot"
        fi
        printf '%s\n' "$s" > "$out/latest-state.txt"
        if [[ $trial_kind == trunk ]] && trunk_counters_valid "$s"; then
          printf '%s\t%s' "$now" "$boot" >> "$out/trunk-counters.tsv"
          for field in uptime cpu_fcs cpu_fragments cpu_ucast cpu_mcast cpu_bcast cpu_drops switch_verified keep; do
            printf '\t%s' "$(value "$s" "$field")" >> "$out/trunk-counters.tsv"
          done
          printf '\n' >> "$out/trunk-counters.tsv"
          errors="$(value "$s" cpu_fcs):$(value "$s" cpu_fragments)"
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
          if [[ $trial_kind == trunk ]] &&
             { [[ -n $rollback_cause ]] || ! module_matches "$s" "$candidate_module_sha" O || ! grep -Fxq "manifest_module_sha=$candidate_module_sha" <<< "$s"; }; then
            log TRUNK_ATTESTATION_BLOCKED_MODULE_OR_REBOOT
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
            restore UNHEALTHY_PORT_OR_RADIO "$s" || :
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
[[ $mode == --check || $mode == --check-baseline || $mode == --run ]] || fatal "unknown mode $mode"
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
baseline_healthy "$s" || fatal "unhealthy source: $s"
if [[ $profile == dhcp ]]; then
  grep -Fxq approval=1 <<< "$s" || fatal 'rollback not persistently approved'
  upstream_ready || fatal 'isolated upstream service not ready'
  if [[ $trial_kind == trunk ]]; then
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
[[ $mode == --run ]] || exit 0
tag=secondary-ap-$(date +%Y%m%d-%H%M%S)
out="$base/runs/$tag"
mkdir -p "$out"
printf '%s\n' "$s" > "$out/preflight.txt"
for pair in "$candidate|/tmp/wave7-secondary-ap-trial.bin|$candidate_sha" "$accepted|/tmp/wave7-secondary-ap-baseline.bin|$accepted_sha"; do
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
  /home/jan/scripts/wave7/secondary-ap-guard8/trial-ap.sh "$trial_kind" --watch "$boot" "$out"
systemd-run --user --quiet --unit="$fallback" --property=RuntimeMaxSec=1500 -- \
  /home/jan/scripts/wave7/wave7-fallback-watch.sh "$tag"
await_observers "$guard" "$fallback" "$out"
echo "GUARDS_ARMED $tag"
flash_started=1
set +e
remote_timed '/sbin/sysupgrade -n /tmp/wave7-secondary-ap-trial.bin' > "$out/sysupgrade.log" 2>&1
rc=$?
set -e
echo "FLASH_SSH_RC=$rc" | tee -a "$out/sysupgrade.log"
if ! grep -q 'Commencing upgrade\. Closing all shell sessions\.' "$out/sysupgrade.log"; then
  # A refused upgrade must not be treated as an attempted flash.
  flash_started=0
  fatal "sysupgrade did not reach its actual upgrade stage"
fi
echo "RUN_DIR=$out"
