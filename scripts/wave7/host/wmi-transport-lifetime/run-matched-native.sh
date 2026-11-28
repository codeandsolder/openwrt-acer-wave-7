#!/usr/bin/env bash
# Advance one exact native trial after its predecessor's sealed load matrix.
set -Eeuo pipefail
umask 077
fail(){ echo "MATCHED_NATIVE_FAIL $*" >&2; exit 1; }
[[ $# == 4 || $# == 5 ]] || fail "usage: $0 CANDIDATE_DIR PARENT_DIR PARENT_MATRIX OUTPUT [--parent-htt]"
candidate=$(realpath -e "$1")
parent=$(realpath -e "$2")
baseline=$(realpath -e "$3")
out=$(realpath -m "$4")
[[ $# == 4 || $5 == --parent-htt ]] || fail 'unknown option'
lab=/home/jan/firmware/wave7/trials
[[ "$candidate" == "$lab"/* && "$parent" == "$lab"/* && "$candidate" != "$parent" &&
   "$baseline" == "$parent"/harness-verification/* &&
   "$out" == "$candidate"/harness-verification/* ]] || fail 'trial directory'
h=$(dirname "$(dirname "$(realpath "$0")")")
t="$h/secondary-ap/trial-native-image.sh"
mkdir -m 700 "$out"
exec > >(tee "$out/wrapper.log") 2>&1
lock="$lab/20261120-secondary-ap-guard8/.lab-control.lock"
[[ -f $lock && ! -L $lock && -O $lock ]] || fail 'invalid lab lock'
exec 8<>"$lock"
flock -w 1800 8 || fail 'lab busy'
rg -q '^COMPLETE ' "$baseline/wrapper.log" || fail 'parent matrix incomplete'
prev=$(realpath -e "$(cat "$baseline/run-directory.txt")")
[[ "$prev" == "$parent"/runs/native-* && $(cat "$prev/status") == SOAK_PASS ]] || fail 'parent soak'
verify_case(){
    local run=$1 a=$2
    [[ "$a" == "$run"/client-ab-* && $(cat "$a/status") == exit=0 ]] || fail 'unqualified case'
    (cd "$a"; sha256sum -c SHA256SUMS >/dev/null)
    rg -qx 'verified=1' "$a/client-restore-status.txt" || fail 'client restoration'
    rg -q STACK_ORIGINAL_PASS "$a/client-original-after.txt" || fail 'client stack restoration'
}
for id in single-5 dual-5 dual-24; do
    a=$(realpath -e "$(cat "$baseline/$id-dir.txt")")
    verify_case "$prev" "$a"
    jq -e '.matched == true' "$baseline/$id-comparison.json" >/dev/null
done
# Freeze the same client helper across all candidate measurements.
local_sha=$(sha256sum "$h/secondary-ap/client-sustained.sh" | cut -d' ' -f1)
remote_sha=$(ssh -o BatchMode=yes acer "ssh -o BatchMode=yes wyse-eth 'sha256sum /home/jan/scripts/wave7/client-validation/client-sustained.sh'" | cut -d' ' -f1)
[[ "$remote_sha" == "$local_sha" ]] || fail 'client helper digest'
bash "$t" --verify-artifacts "$candidate" "$parent"
run_case(){
    local run=$1 id=$2 band=$3 variant=$4 rc=0 a
    shift 4
    echo "START $id $(date -Is)"
    bash "$h/wmi-transport-lifetime/test-primary-client.sh" "$run" --band="$band" --client-load "$variant" --ap-rx-error-stats --ap-load-series --ap-link-stats --ap-channel-survey "$@" | tee "$out/$id.log" || rc=$?
    a=$(sed -n 's/^PRIMARY_CLIENT_TEST_DIR=//p' "$out/$id.log" | tail -1)
    [[ -d "$a" && "$a" == "$run"/client-ab-* ]] || fail 'missing client result directory'
    printf '%s\n' "$a" > "$out/$id-dir.txt"
    (cd "$a"; sha256sum -c SHA256SUMS >/dev/null)
    [[ $rc == 0 ]] || fail "unqualified $id rc=$rc"
    verify_case "$run" "$a"
}
if [[ ${5:-} == --parent-htt ]]; then
    # Separate diagnostic profile: never compare its throughput as a
    # matched firmware trial. A failed request stops the sequence.
    run_case "$prev" parent-htt-5 5 --client-reconnect-teardown-privilege-trace --ap-htt-tx-stats
    a=$(cat "$out/parent-htt-5-dir.txt")
    uv run --offline --no-project python -B "$h/wmi-transport-lifetime/load-ap-delta.py" "$a" --band 5 > "$out/parent-htt-5-delta.json"
    echo "DIAGNOSTIC_COMPLETE parent-htt-5 $(date -Is)"
fi
bash "$t" --run-native "$candidate" "$parent" "$prev" | tee "$out/native.log"
run=$(sed -n 's/^RUN_DIR=//p' "$out/native.log" | tail -1)
[[ "$run" == "$candidate"/runs/native-* && $(cat "$run/status") == SOAK_PASS ]] || fail 'candidate soak'
printf '%s\n' "$run" > "$out/run-directory.txt"
awk '/^WBM_RX/ {split($8,e,"="); split($9,s,"="); if(e[1]!="entry" || s[1]!="size" || s[2]/e[2]!=8192) exit 2; found++} END {if(found!=1)exit 1}' "$run/srng-initial.txt"
echo RX_RELEASE_RING_8192_VERIFIED
for id in single-5 dual-5 dual-24; do
    case "$id" in
        single-5) band=5; variant=--client-single-link ;;
        dual-5) band=5; variant=--client-reconnect-teardown-privilege-trace ;;
        dual-24) band=24; variant=--client-reconnect-teardown-privilege-trace ;;
    esac
    run_case "$run" "$id" "$band" "$variant"
    a=$(cat "$out/$id-dir.txt")
    old=$(cat "$baseline/$id-dir.txt")
    uv run --offline --no-project python -B "$h/wmi-transport-lifetime/compare-load.py" --band "$band" "$old" "$a" > "$out/$id-comparison.json"
    jq -e '.matched == true' "$out/$id-comparison.json" >/dev/null
    echo "QUALIFIED $id $(date -Is)"
done
echo "COMPLETE $(date -Is)"
