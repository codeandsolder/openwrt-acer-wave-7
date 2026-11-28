#!/usr/bin/env bash
# Qualify a fresh channel-pinned baseline or compare an exact candidate.
# Only this isolated lab profile bypasses the 5 GHz startup HT40 scan.
set -Eeuo pipefail
umask 077
fail(){ echo "FIXED_PRIMARY_FAIL $*" >&2; exit 1; }
[[ $# == 5 || $# == 6 ]] || fail "usage: $0 --baseline|--compare|--compare-partial CANDIDATE_DIR PREDECESSOR_DIR PREDECESSOR_RUN_OR_MATRIX OUTPUT [RESUME_MATRIX]"
mode=$1
[[ $mode == --baseline || $mode == --compare || $mode == --compare-partial ]] || fail 'mode'
candidate=$(realpath -e "$2")
parent=$(realpath -e "$3")
source=$(realpath -e "$4")
out=$(realpath -m "$5")
resume=''
[[ $# == 5 ]] || resume=$(realpath -e "$6")
lab=/home/jan/firmware/wave7/trials
[[ "$candidate" == "$lab"/* && "$parent" == "$lab"/* && "$candidate" != "$parent" &&
   "$out" == "$candidate"/harness-verification/* ]] || fail 'trial directory'
[[ -z $resume || $resume == "$candidate"/harness-verification/* ]] || fail 'resume directory'
h=$(dirname "$(dirname "$(realpath "$0")")")
t="$h/secondary-ap/trial-native-image.sh"
mkdir -m 700 "$out"
exec > >(tee "$out/wrapper.log") 2>&1
lock="$lab/20261120-secondary-ap-guard8/.lab-control.lock"
[[ -f $lock && ! -L $lock && -O $lock ]] || fail 'invalid lab lock'
exec 8<>"$lock"
flock -w 1800 8 || fail 'lab busy'
manifest="$candidate/native-manifest.json"
parent_manifest="$parent/native-manifest.json"
wireless=$(jq -er '.policy_sha256["etc/config/wireless"]|select(test("^[a-f0-9]{64}$"))' "$manifest")
old_wireless=$(jq -er '.policy_sha256["etc/config/wireless"]|select(test("^[a-f0-9]{64}$"))' "$parent_manifest")
expected_rev=$(jq -er .revision "$manifest")
expected_builder=$(jq -er .builder_commit "$manifest")
[[ $expected_rev =~ ^r0\+[0-9]+-[a-f0-9]{10}-ap-dhcp-guard8$ && $expected_builder =~ ^[a-f0-9]{40}$ ]] || fail 'manifest identity'
ids=(single-5 dual-5 dual-24)
verify_restored(){
    local run=$1 a=$2
    [[ "$a" == "$run"/client-ab-* ]] || fail 'unexpected client archive'
    (cd "$a"; sha256sum -c SHA256SUMS >/dev/null) || fail 'client archive seal'
    rg -qx 'verified=1|already_original=1' "$a/client-restore-status.txt" || fail 'client restoration'
    rg -q STACK_ORIGINAL_PASS "$a/client-original-after.txt" || fail 'client stack restoration'
}
verify_case(){
    local run=$1 a=$2
    verify_restored "$run" "$a"
    [[ $(cat "$a/status") == exit=0 ]] || fail 'unqualified case'
}
declare -A comparable=()
# A diagnostic partial matrix is deliberately distinct from full matched
# qualification. A self-qualified archive may be a per-profile parent,
# but an unqualified case can never become comparison evidence.
parent_profile_eligible(){
    local matrix=$1 id=$2 a=$3
    [[ $(cat "$a/status") == exit=0 ]] || return 1
    if rg -q "^QUALIFIED $id " "$matrix/wrapper.log"; then
        return 0
    fi
    [[ $mode == --compare-partial ]] &&
        rg -q "^STANDALONE $id " "$matrix/wrapper.log"
}
if [[ $mode == --baseline ]]; then
    [[ $source == "$parent"/runs/native-* ]] || fail 'baseline predecessor run'
    prev=$source
    [[ $wireless != "$old_wireless" ]] || fail 'baseline must introduce fixed policy'
    # Re-baselining does not waive the predecessor health/restore gates.
    # Require the latest client archive to be sealed and restored.
    latest=$(find "$prev" -maxdepth 1 -type d -name 'client-ab-*' -printf '%p\n' | sort | tail -1)
    [[ -n $latest ]] || fail 'missing predecessor client case'
    (cd "$latest"; sha256sum -c SHA256SUMS >/dev/null)
    rg -qx 'verified=1|already_original=1' "$latest/client-restore-status.txt" || fail 'predecessor client restoration'
    rg -q STACK_ORIGINAL_PASS "$latest/client-original-after.txt" || fail 'predecessor client stack'
else
    [[ $source == "$parent"/harness-verification/* && $wireless == "$old_wireless" ]] || fail 'matched predecessor policy'
    terminal=$(tail -1 "$source/wrapper.log")
    if [[ $mode == --compare ]]; then
        [[ $terminal == COMPLETE\ * ]] || fail 'parent matrix incomplete'
    else
        [[ $terminal == COMPLETE\ * || $terminal == INCOMPLETE\ * ]] || fail 'parent matrix not sealed'
    fi
    prev=$(realpath -e "$(cat "$source/run-directory.txt")")
    [[ "$prev" == "$parent"/runs/native-* && $(cat "$prev/status") == SOAK_PASS ]] || fail 'parent soak'
    parent_sha=$(jq -er .image_sha256 "$parent_manifest")
    for id in "${ids[@]}"; do
        a=$(realpath -e "$(cat "$source/$id-dir.txt")")
        verify_restored "$prev" "$a"
        if ! parent_profile_eligible "$source" "$id" "$a"; then
            [[ $mode == --compare-partial ]] || fail "unqualified parent $id"
            comparable[$id]=0
            echo "PARENT_UNQUALIFIED $id"
            continue
        fi
        verify_case "$prev" "$a"
        # Recompute qualification from the sealed run, not the mutable
        # summary JSON or a label alone.
        case "$id" in single-5|dual-5) band=5 ;; dual-24) band=24 ;; esac
        uv run --offline --no-project python -B "$h/wmi-transport-lifetime/compare-load.py" --band "$band" --describe-run "$a" > "$out/parent-$id-qualified.json"
        jq -e --arg p "$a" --arg w "$wireless" --arg sha "$parent_sha"             '.path == $p and .identity.wireless_policy == $w and .image_sha256 == $sha' "$out/parent-$id-qualified.json" >/dev/null
        comparable[$id]=1
    done
    [[ ${comparable[single-5]} == 1 || ${comparable[dual-5]} == 1 || ${comparable[dual-24]} == 1 ]] || fail 'no qualified parent profile'
    latest=$(find "$prev" -maxdepth 1 -type d -name 'client-ab-*' -printf '%p\n' | sort | tail -1)
    [[ -n $latest ]] || fail 'missing latest predecessor client case'
    verify_restored "$prev" "$latest"
fi
[[ "$prev" == "$parent"/runs/native-* && $(cat "$prev/status") == SOAK_PASS ]] || fail 'parent soak'
local_sha=$(sha256sum "$h/secondary-ap/client-sustained.sh" | cut -d' ' -f1)
remote_sha=$(ssh -o BatchMode=yes acer "ssh -o BatchMode=yes wyse-eth 'sha256sum /home/jan/scripts/wave7/client-validation/client-sustained.sh'" | cut -d' ' -f1)
[[ "$remote_sha" == "$local_sha" ]] || fail 'client helper digest'
bash "$t" --verify-artifacts "$candidate" "$parent"
if [[ -n $resume ]]; then
    run=$(realpath -e "$(cat "$resume/run-directory.txt")")
else
    bash "$t" --run-native "$candidate" "$parent" "$prev" | tee "$out/native.log"
    run=$(sed -n 's/^RUN_DIR=//p' "$out/native.log" | tail -1)
fi
[[ "$run" == "$candidate"/runs/native-* && $(cat "$run/status") == SOAK_PASS ]] || fail 'candidate soak'
printf '%s\n' "$run" > "$out/run-directory.txt"
awk '/^WBM_RX/ {split($8,e,"="); split($9,s,"="); if(e[1]!="entry" || s[1]!="size" || s[2]/e[2]!=8192) exit 2; found++} END {if(found!=1)exit 1}' "$run/srng-initial.txt"
boot=$(sed -n 's/^boot=//p' "$run/last-state.txt")
[[ $boot =~ ^[a-f0-9-]{36}$ ]] || fail 'candidate boot ID'
# Attest actual geometry and generated hostapd policy before any client load.
remote(){
    ssh -T -i /home/jan/.ssh/wave7-root-rsa -o BindInterface=enp4s0f4u2u4 -o BindAddress=192.168.76.2 \
        -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=yes \
        -o "UserKnownHostsFile=$run/known_hosts" root@192.168.76.1 "$@"
}
attest(){
    remote "set -eu
        [ \"\$(cat /proc/sys/kernel/random/boot_id)\" = '$boot' ]
        [ \"\$(cat /rom/etc/openwrt_version)\" = '$expected_rev' ]
        [ \"\$(sed -n 's/^builder_commit=//p' /rom/etc/wave7-role-profile)\" = '$expected_builder' ]
        [ \"\$(sha256sum /etc/config/wireless)\" = '$wireless  /etc/config/wireless' ]
        [ \"\$(uci -q get wireless.radio1.noscan)\" = 1 ]
        [ -z \"\$(uci -q get wireless.radio0.noscan || :)\" ]
        grep -qx 'noscan=1' /var/run/hostapd-phy0.1.conf
        grep -qx 'channel=36' /var/run/hostapd-phy0.1.conf
        [ -z \"\$(iw dev ap-mld0 station dump)\" ]
        for p in 0 1 2; do [ \"\$(cat /sys/class/remoteproc/remoteproc\$p/state)\" = running ]; done
        [ \"\$(dmesg | grep -c 'NOC ERROR DETECTED' || :)\" = 0 ]
        iw dev ap-mld0 info" > "$1"
    rg -qx '[[:space:]]*channel 1 \(2412 MHz\), width: 20 MHz, center1: 2412 MHz' "$1" ||
        fail '2.4 GHz geometry'
    rg -qx '[[:space:]]*channel 36 \(5180 MHz\), width: 80 MHz, center1: 5210 MHz' "$1" ||
        fail '5 GHz geometry'
}
attest "$out/geometry-initial.txt"
echo FIXED_PRIMARY_GEOMETRY_PASS
failed=()
for id in "${ids[@]}"; do
    case "$id" in
      single-5) band=5; variant=--client-single-link ;;
      dual-5) band=5; variant=--client-reconnect-teardown-privilege-trace ;;
      dual-24) band=24; variant=--client-reconnect-teardown-privilege-trace ;;
    esac
    # Reuse only independently qualified completed cases from the same
    # sealed candidate boot; incomplete/failed cases require a fresh run.
    a=''
    if [[ -n $resume && -f "$resume/$id-dir.txt" ]] &&
       rg -q "^(QUALIFIED|STANDALONE) $id " "$resume/wrapper.log"; then
        existing=$(realpath -e "$(cat "$resume/$id-dir.txt")")
        if [[ "$existing" == "$run"/client-ab-* && $(cat "$existing/status") == exit=0 ]]; then
            verify_case "$run" "$existing"
            a=$existing
            echo "REUSE $id $a"
        fi
    fi
    if [[ -z $a ]]; then
        echo "START $id $(date -Is)"
        attest "$out/$id-geometry-before.txt"
        rc=0
        bash "$h/wmi-transport-lifetime/test-primary-client.sh" "$run" --band="$band" --client-load "$variant" --ap-rx-error-stats --ap-load-series --ap-link-stats --ap-channel-survey | tee "$out/$id.log" || rc=$?
        a=$(sed -n 's/^PRIMARY_CLIENT_TEST_DIR=//p' "$out/$id.log" | tail -1)
        [[ -d "$a" && "$a" == "$run"/client-ab-* ]] || fail 'missing client result directory'
        printf '%s\n' "$a" > "$out/$id-dir.txt"
        verify_restored "$run" "$a"
        [[ $(cat "$a/status") == "exit=$rc" ]] || fail 'client exit status mismatch'
        if (( rc )); then
            # This profile failed its connectivity/measurement gate. It
            # cannot serve as a baseline, but an independent profile may
            # run if the original stack and exact AP boot are healthy.
            attest "$out/$id-geometry-after.txt"
            echo "UNQUALIFIED $id rc=$rc $(date -Is)"
            failed+=("$id")
            continue
        fi
        verify_case "$run" "$a"
    fi
    printf '%s\n' "$a" > "$out/$id-dir.txt"
    attest "$out/$id-geometry-after.txt"
    # Every candidate must independently qualify before being used as
    # either a comparison endpoint or a new per-profile baseline.
    if ! uv run --offline --no-project python -B "$h/wmi-transport-lifetime/compare-load.py" --band "$band" --describe-run "$a" > "$out/$id-baseline.json" ||
       ! jq -e --arg w "$wireless" '.identity.wireless_policy == $w and (.identity.geometry | index("channel 36 (5180 MHz), width: 80 MHz, center1: 5210 MHz") != null)' "$out/$id-baseline.json" >/dev/null; then
        echo "UNQUALIFIED $id baseline $(date -Is)"
        failed+=("$id")
        continue
    fi
    if [[ $mode != --baseline ]]; then
        matched=0
        if [[ ${comparable[$id]} == 1 ]]; then
            old=$(realpath -e "$(cat "$source/$id-dir.txt")")
            if uv run --offline --no-project python -B "$h/wmi-transport-lifetime/compare-load.py" --band "$band" --describe-unmatched "$old" "$a" > "$out/$id-comparison.json" &&
               jq -e '.matched == true' "$out/$id-comparison.json" >/dev/null; then
                matched=1
            fi
        fi
        if (( !matched )); then
            # Explicitly record a standalone result, never promote it
            # to matched evidence or declare this matrix complete.
            echo "STANDALONE $id $(date -Is)"
            failed+=("$id")
            continue
        fi
    fi
    echo "QUALIFIED $id $(date -Is)"
done
if (( ${#failed[@]} )); then
    echo "INCOMPLETE ${failed[*]} $(date -Is)"
    exit 1
fi
echo "COMPLETE $(date -Is)"
