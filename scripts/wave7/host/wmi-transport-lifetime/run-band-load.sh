#!/usr/bin/env bash
# Independent RF profile characterization, not a matched driver comparison.
set -Eeuo pipefail
umask 077
fail(){ echo "BAND_LOAD_FAIL $*" >&2; exit 1; }
[[ $# == 2 || $# == 3 ]] || fail 'usage: RUN OUTPUT [RESUME_MATRIX | --rate-diagnostic]'
run=$(realpath -e "$1")
base=$(dirname "$(dirname "$run")")
out=$(realpath -m "$2")
lab=/home/jan/firmware/wave7/trials
[[ "$run" == "$lab"/*/runs/native-* && "$out" == "$base"/harness-verification/* ]] || fail 'trial directory'
resume=''
rate_diagnostic=0
if [[ $# == 3 ]]; then
    if [[ $3 == --rate-diagnostic ]]; then
        rate_diagnostic=1
    else
        resume=$(realpath -e "$3")
        [[ "$resume" == "$base"/harness-verification/* && "$resume" != "$out" ]] || fail 'resume matrix'
    fi
fi
h=$(dirname "$(dirname "$(realpath "$0")")")
lock="$lab/20261120-secondary-ap-guard8/.lab-control.lock"
[[ -f $lock && ! -L $lock && -O $lock ]] || fail 'lab lock'
if [[ ! /proc/self/fd/8 -ef "$lock" ]]; then exec 8<>"$lock"; fi
flock -w 1200 8 || fail 'lab busy'
[[ $(cat "$run/status") == SOAK_PASS ]] || fail 'AP soak incomplete'
profile=$(jq -er .band_profile "$base/native-manifest.json")
case "$profile" in
  5g80) band=5; geometry='channel 36 (5180 MHz), width: 80 MHz, center1: 5210 MHz' ;;
  5g160) band=5; geometry='channel 36 (5180 MHz), width: 160 MHz, center1: 5250 MHz' ;;
  6g80) band=6; geometry='channel 5 (5975 MHz), width: 80 MHz, center1: 5985 MHz' ;;
  6g160) band=6; geometry='channel 5 (5975 MHz), width: 160 MHz, center1: 6025 MHz' ;;
  *) fail 'unknown RF profile' ;;
esac
mkdir -m 700 "$out"
exec > >(tee "$out/wrapper.log") 2>&1
remote(){
    ssh -T -i /home/jan/.ssh/wave7-root-rsa -o BindInterface=enp4s0f4u2u4 -o BindAddress=192.168.76.2 \
        -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=yes \
        -o "UserKnownHostsFile=$run/known_hosts" root@192.168.76.1 "$@"
}
attest(){
    remote 'set -e
      iw dev ap-mld0 info
      cat /sys/kernel/debug/gpio | grep -E "gpio49 |gpio50 "
      grep -E "^(country_code|channel|op_class|he_6ghz_reg_pwr_type|ieee80211w|sae_pwe)=" /var/run/hostapd-phy0.1.conf
      [ -z "$(iw dev ap-mld0 station dump)" ]' > "$1"
    rg -Fq "$geometry" "$1" || fail 'high-band geometry'
    rg -Fq 'channel 1 (2412 MHz), width: 20 MHz, center1: 2412 MHz' "$1" || fail '2.4 GHz geometry'
    rg -qx 'country_code=PL' "$1" || fail 'country'
    rg -qx 'ieee80211w=2' "$1" || fail 'PMF'
    if [[ $band == 6 ]]; then
        rg -q 'gpio49 +: out low +func0' "$1" && rg -q 'gpio50 +: out high +func0' "$1" || fail '6 GHz RF switch'
        rg -qx 'he_6ghz_reg_pwr_type=0' "$1" || fail 'indoor LPI'
        rg -qx 'sae_pwe=[12]' "$1" || fail 'SAE H2E'
    else
        rg -q 'gpio49 +: out high +func0' "$1" && rg -q 'gpio50 +: out low +func0' "$1" || fail '5 GHz RF switch'
    fi
}
local_sha=$(sha256sum "$h/secondary-ap/client-sustained.sh" | cut -d' ' -f1)
remote_sha=$(ssh -o BatchMode=yes acer "ssh -o BatchMode=yes wyse-eth 'sha256sum /home/jan/scripts/wave7/client-validation/client-sustained.sh'" | cut -d' ' -f1)
[[ "$remote_sha" == "$local_sha" ]] || fail 'client helper digest'
ids=("single-$band" "dual-$band" dual-24)
rate_args=()
if (( rate_diagnostic )); then
    ids=("single-$band")
    rate_args=(--ap-htt-rate-stats)
    # First prove type 9 support at idle on the same guarded AP boot.
    attest "$out/probe-before.txt"
    boot=$(sed -n 's/^boot=//p' "$run/last-state.txt")
    [[ $boot =~ ^[0-9a-f-]{36}$ ]] || fail 'boot identity'
    wireless_sha=$(jq -er '.policy_sha256["etc/config/wireless"]' "$base/native-manifest.json")
    [[ $wireless_sha =~ ^[0-9a-f]{64}$ ]] || fail 'wireless digest'
    {
        printf 'set -eu\n'
        cat "$h/wmi-transport-lifetime/ap-htt-reader.sh"
        printf '[ "$(cat /proc/sys/kernel/random/boot_id)" = "%s" ]\n' "$boot"
        printf '[ "$(sha256sum /etc/config/wireless)" = "%s  /etc/config/wireless" ]\n' "$wireless_sha"
        cat <<'PROBE'
[ -z "$(iw dev ap-mld0 station dump)" ]
cat /proc/sys/kernel/random/boot_id
echo ==== HTT_TX_BEFORE
capture_htt_tx || exit 1
echo ==== HTT_RATE
capture_htt_rate || exit 1
# Enforce a distinguishable non-overlapping reset witness at idle.
ucode -e 'exit(sleep(100) ? 0 : 1);'
echo ==== HTT_TX_AFTER
capture_htt_tx || exit 1
[ -z "$(iw dev ap-mld0 station dump)" ]
echo ==== END
cat /proc/sys/kernel/random/boot_id
PROBE
    } | remote 'sh -s' > "$out/idle-htt-probe.txt" 2>&1 || fail 'HTT idle probe failed; no further requests'
    uv run --offline --no-project python -B "$h/wmi-transport-lifetime/verify-htt-rate-probe.py" "$out/idle-htt-probe.txt" "$boot" > "$out/idle-htt-probe.json" ||
        fail 'unqualified idle HTT response; no further requests'
    attest "$out/probe-after.txt"
    echo "HTT_RATE_IDLE_PASS $(date -Is)"
fi
failed=()
for id in "${ids[@]}"; do
    select_band=${id#*-}
    case "$id" in single-*) variant=--client-single-link ;; *) variant=--client-reconnect-teardown-privilege-trace ;; esac
    if [[ -n $resume ]] && rg -q "^QUALIFIED $id " "$resume/wrapper.log"; then
        a=$(realpath -e "$(cat "$resume/$id-dir.txt")")
        [[ "$a" == "$run"/client-ab-* && $(cat "$a/status") == exit=0 ]] || fail 'resume case identity'
        (cd "$a"; sha256sum -c SHA256SUMS >/dev/null) || fail 'resume case seal'
        uv run --offline --no-project python -B "$h/wmi-transport-lifetime/compare-load.py" --band "$select_band" --describe-run "$a" > "$out/$id-qualified.json"
        printf '%s\n' "$a" > "$out/$id-dir.txt"
        echo "REUSE $id $a"
        echo "QUALIFIED $id $(date -Is)"
        continue
    fi
    echo "START $id $(date -Is)"
    attest "$out/$id-before.txt"
    rc=0
    bash "$h/wmi-transport-lifetime/test-primary-client.sh" "$run" --band="$select_band" --client-load "$variant" --ap-rx-error-stats --ap-load-series --ap-link-stats --ap-channel-survey --ap-reo-command-stats --ap-tx-attempt-stats "${rate_args[@]}" | tee "$out/$id.log" || rc=$?
    a=$(sed -n 's/^PRIMARY_CLIENT_TEST_DIR=//p' "$out/$id.log" | tail -1)
    [[ "$a" == "$run"/client-ab-* && -d "$a" ]] || fail 'missing client archive'
    printf '%s\n' "$a" > "$out/$id-dir.txt"
    (cd "$a"; sha256sum -c SHA256SUMS >/dev/null) || fail 'archive seal'
    rg -q STACK_ORIGINAL_PASS "$a/client-original-after.txt" || fail 'client restoration'
    attest "$out/$id-after.txt"
    if [[ $rc != 0 ]]; then echo "UNQUALIFIED $id rc=$rc"; failed+=("$id"); continue; fi
    uv run --offline --no-project python -B "$h/wmi-transport-lifetime/compare-load.py" --band "$select_band" --describe-run "$a" > "$out/$id-qualified.json"
    echo "QUALIFIED $id $(date -Is)"
    if (( rate_diagnostic )); then
        jq -e 'all(.phases[]; .htt_rate.qualified == true and .htt_tx.qualified == true) and
               any(.phases.downlink.htt_rate.radios | to_entries[];
                   (.key | startswith("ahb-soc@0:wifi/")) and (.value.histogram_delta.tx_nss | add > 0))'             "$out/$id-qualified.json" >/dev/null || fail 'rate telemetry unqualified or no TX rate activity'
        echo "HTT_RATE_DIAGNOSTIC_QUALIFIED $(date -Is)"
    fi
done
if (( ${#failed[@]} )); then
    echo "BAND_LOAD_INCOMPLETE ${failed[*]} $(date -Is)"
    exit 1
fi
echo "BAND_LOAD_COMPLETE $(date -Is)"
