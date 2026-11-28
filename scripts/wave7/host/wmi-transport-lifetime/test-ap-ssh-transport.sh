#!/usr/bin/env bash
set -euo pipefail
h=$(dirname "$(realpath "$0")")
# Execute the actual extracted transport without network access.
source <(sed -n '/^remote_stream(){/,/^remote(){/p' "$h/test-primary-client.sh" | head -n -1)
fail(){ printf '%s\n' "$*" >&2; exit 1; }
ssh(){ printf '%s\n' SSH_CALLED; }
run=/fixture/run
test "$(remote_stream true)" = SSH_CALLED
printf -v limit '%09000d' 0
test "$(remote_stream "$limit")" = SSH_CALLED
if (remote_stream "${limit}a") >/dev/null 2>&1; then
    echo 'oversize exec accepted' >&2
    exit 1
fi
# The real expanded script must travel over stdin even when all
# optional telemetry is disabled.
helper="$h/ap-control-trace.sh"
source <(sed -n '/^debugfs_reader=/,/^guard || fail/p' "$h/test-primary-client.sh" | head -n -1)
remote(){ echo 'measurement attempted SSH exec' >&2; exit 1; }
remote_stream(){
    [[ $# == 1 && $1 == 'sh -s' ]] || return 1
    local body
    body=$(cat)
    (( ${#body} > 9000 )) || return 1
    printf '%s\n' "$body" | sh -n
    [[ $body == *'capture_htt_mlo'* && $body == *'capture_htt_rate'* && $body == *'capture_tx_attempts'* &&
       $body == *'capture_reo_commands'* && $body == *'echo ==== CPU'* &&
       $body == *'echo ==== END'* ]] || return 1
    echo STREAMED_COMPLETE_SCRIPT
}
boot=7ea992e2-8942-4a76-afe9-b67e540d58d2
wireless_sha=dffaede0018713d32e4d84927118ae8064c7521d72d013fb5df17620b96b45fb
ap_link_tool=/tmp/wave7-iw.aBcDEf
for profile in 0 1; do
    ap_channel_survey=$profile
    ap_link_stats=$profile
    ap_rx_error_stats=$profile
    ap_htt_tx_stats=$profile
    ap_htt_mlo_stats=$profile
    ap_htt_rate_stats=$profile
    ap_reo_command_stats=$profile
    ap_tx_attempt_stats=$profile
    for side in before after; do
        test "$(snapshot_load "$side")" = STREAMED_COMPLETE_SCRIPT
    done
done
echo AP_SSH_TRANSPORT_PASS
