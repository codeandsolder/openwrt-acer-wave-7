#!/bin/sh
# Exercise the exact AP reader without a running AP or real debugfs.
set -eu
h=$(dirname "$(realpath "$0")")
. "$h/ap-debugfs-reader.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat(){
    [ "$1" = /fixture/counter ] || return 99
    read -r n < "$tmp/reads"
    n=$((n + 1))
    printf '%s\n' "$n" > "$tmp/reads"
    if [ "$n" -le "$busy" ]; then
        printf '%s\n' "$error" >&2
        return 1
    fi
    printf '%s\n' 'line one' 'line two'
}
ucode(){
    [ "$#" = 2 ] && [ "$1" = -e ] &&
        [ "$2" = 'exit(sleep(20) ? 0 : 1);' ] || return 99
    read -r n < "$tmp/delays"
    printf '%s\n' "$((n + 1))" > "$tmp/delays"
    return "$delay_rc"
}
for scenario in clean one_busy four_busy exhausted alternate permanent partial delay_failure; do
    printf '0\n' > "$tmp/reads"
    printf '0\n' > "$tmp/delays"
    error='cat: read error: Resource busy'
    delay_rc=0
    rc=0
    case "$scenario" in
        clean) busy=0; reads=1; delays=0 ;;
        one_busy) busy=1; reads=2; delays=1 ;;
        four_busy) busy=4; reads=5; delays=4 ;;
        exhausted) busy=5; reads=5; delays=4; rc=1 ;;
        alternate) busy=2; reads=3; delays=2; error='cat: read error: Device or resource busy' ;;
        permanent) busy=1; reads=1; delays=0; rc=1; error='cat: read error: No such device' ;;
        partial) busy=1; reads=1; delays=0; rc=1; error='partial output
cat: read error: Resource busy' ;;
        delay_failure) busy=1; reads=1; delays=1; rc=1; delay_rc=1 ;;
    esac
    actual_rc=0
    read_debugfs /fixture/counter > "$tmp/result" 2> "$tmp/error" || actual_rc=$?
    [ "$actual_rc" = "$rc" ]
    read -r actual < "$tmp/reads"; [ "$actual" = "$reads" ]
    read -r actual < "$tmp/delays"; [ "$actual" = "$delays" ]
    if [ "$rc" = 0 ]; then
        [ "$(command cat "$tmp/result")" = "$(printf '%s\n' 'line one' 'line two')" ]
        [ ! -s "$tmp/error" ]
    else
        [ ! -s "$tmp/result" ]
        if [ "$delay_rc" = 0 ]; then
            grep -q '^debugfs /fixture/counter:' "$tmp/error"
        fi
    fi
done
printf 'AP_DEBUGFS_RETRY_PASS\n'
