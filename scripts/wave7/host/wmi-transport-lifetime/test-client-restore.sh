#!/usr/bin/env bash
# Exercise the actual runner's recovery function without touching the lab.
set -Eeuo pipefail
cd "$(dirname "$(realpath "$0")")"
# shellcheck disable=SC1090
source <(sed -n '/^restore_client(){/,/^}/p' test-primary-client.sh)
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
# Read by the sourced recovery function.
# shellcheck disable=SC2034
client=/fixture
# shellcheck disable=SC2034
variant='test'
boot=12345678-1234-1234-1234-123456789abc
wyse(){
    case "$1" in
        *--check-original)
            (( ++checks ))
            if (( checks >= pass_at )); then
                printf 'STACK_ORIGINAL_PASS boot=%s\n' "$boot"
                return 0
            fi
            if (( false_marker )); then echo 'STACK_ORIGINAL_PASS boot=invalid'; return 0; fi
            return 1 ;;
        *--restore) (( ++requests )); return "$request_exit" ;;
        *) return 99 ;;
    esac
}
sleep(){ :; }
for scenario in original normal dropped invalid; do
    checks=0 requests=0 request_exit=0 false_marker=0
    case "$scenario" in
        original) pass_at=1 ;;
        normal) pass_at=3 ;;
        dropped) pass_at=2; request_exit=255 ;;
        invalid) pass_at=999; false_marker=1 ;;
    esac
    if [[ $scenario == invalid ]]; then
        if restore_client 0; then exit 1; fi
        grep -qx 'verified=0' "$out/client-restore-status.txt"
    else
        restore_client 3
        if [[ $scenario == original ]]; then
            (( requests == 0 ))
            grep -qx 'already_original=1' "$out/client-restore-status.txt"
        else
            (( requests == 1 ))
            grep -qx "request_exit=$request_exit" "$out/client-restore-status.txt"
            grep -qx 'verified=1' "$out/client-restore-status.txt"
        fi
    fi
    printf 'PASS %s\n' "$scenario"
done
