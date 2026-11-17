#!/usr/bin/env bash
# Independent Asus-side raw QDSS capture from the IPQ5332 AHB device.
# Existing Q6 ELF devcore collector remains responsible for ELF dumps.
set -Eeuo pipefail
umask 077
mode=${1:---check}
[[ $mode == --check || $mode == --run || $mode == --selftest ]] || {
    echo 'usage: watch-qdss-devcore.sh --check|--run|--selftest' >&2; exit 2;
}
root=${WAVE7_QDSS_CAPTURE_DIR:-/home/jan/firmware/wave7/captures/qdss-umacnoc}
key=${WAVE7_QDSS_SSH_KEY:-/home/jan/.ssh/wave7-root-rsa}
host=${WAVE7_QDSS_ROUTER:-root@192.168.76.1}
poll=${WAVE7_QDSS_POLL_SECONDS:-2}
max_size=1048576
ssh_opts=(-n -T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes
    -o ConnectTimeout=3 -o ConnectionAttempts=1
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
    -o LogLevel=ERROR)
[[ $poll =~ ^[0-9]+$ ]] && (( poll >= 1 && poll <= 60 )) || exit 2
# shellcheck disable=SC2029
remote() { ssh "${ssh_opts[@]}" "$host" "$@"; }
log() { printf '%s %s\n' "$(date -Is)" "$*"; }

validate_data() {
    local f=$1 len
    len=$(stat -c %s -- "$f")
    (( len > 0 && len <= max_size )) || return 1
    # Complete Q6 ELF cores belong to the existing collector, which
    # validates ELF program headers. Don't treat them as raw QDSS.
    [[ $(head -c 4 -- "$f" | od -An -tx1 | tr -d ' \n') != 7f454c46 ]]
}
list_candidates() {
    # shellcheck disable=SC2016
    remote 'for dir in /sys/class/devcoredump/devcd[0-9]*; do
        test -d "$dir" || continue
        test -r "$dir/data" || continue
        dev="$(readlink -f "$dir/device" 2>/dev/null || :)"
        case "$dev" in
          *c000000.wifi*) printf "%s|%s\n" "${dir##*/}" "$dev";;
        esac
    done'
}
if [[ $mode == --selftest ]]; then
    f=$(mktemp)
    trap 'rm -f -- "$f"' EXIT
    printf '\x00\x01\x02\x03\x04' > "$f"
    validate_data "$f"
    printf '\177ELF\x00\x00' > "$f"
    if validate_data "$f"; then exit 1; fi
    : > "$f"
    if validate_data "$f"; then exit 1; fi
    echo 'QDSS_CAPTURE_VALIDATOR_PASS'
    exit 0
fi
[[ -r $key ]] || { log 'missing SSH identity'; exit 2; }
if [[ $mode == --check ]]; then
    remote 'test -r /etc/openwrt_version; test -r /proc/sys/kernel/random/boot_id; test -d /sys/class/devcoredump'
    log 'QDSS_CAPTURE_PREFLIGHT_PASS'
    list_candidates || :
    exit 0
fi

mkdir -p -- "$root"
exec 9>"$root/.collector.lock"
flock -n 9 || { log 'QDSS_CAPTURE_LOCK_HELD'; exit 3; }
declare -A completed=()
partial=''
cleanup() { [[ -z $partial ]] || rm -f -- "$partial"; }
trap cleanup EXIT
trap 'exit 143' TERM
log "QDSS_CAPTURE_START dir=$root poll=${poll}s"
while :; do
    if entries=$(list_candidates 2>/dev/null); then
        while IFS='|' read -r device sys_device; do
            [[ $device =~ ^devcd[0-9]+$ ]] || continue
            [[ $sys_device == *c000000.wifi* ]] || continue
            [[ -v completed[$device] ]] && continue
            file=$(mktemp "$root/.qdss.partial.XXXXXXXX")
            partial=$file
            if ! remote "cat /sys/class/devcoredump/$device/data" > "$file"; then
                rm -f -- "$file"; partial=''
                log "QDSS_CAPTURE_READ_FAILED $device"
                continue
            fi
            if [[ $(head -c 4 -- "$file" | od -An -tx1 | tr -d ' \n') == 7f454c46 ]]; then
                log "QDSS_CAPTURE_SKIPPED_ELF $device"
                rm -f -- "$file"; partial=''
                completed[$device]=1
                continue
            fi
            if ! validate_data "$file"; then
                log "QDSS_CAPTURE_RETRY_INCOMPLETE $device size=$(stat -c %s "$file")"
                rm -f -- "$file"; partial=''
                continue
            fi
            second=$(mktemp "$root/.qdss.check.XXXXXXXX")
            # Re-read the same snapshot to reject incomplete SSH transfers.
            if ! remote "cat /sys/class/devcoredump/$device/data" > "$second" ||
                ! cmp -s "$file" "$second"; then
                rm -f -- "$second" "$file"; partial=''
                log "QDSS_CAPTURE_SNAPSHOT_CHANGED $device"
                continue
            fi
            rm -f -- "$second"
            read -r sha _ < <(sha256sum "$file")
            dest="$root/$sha.bin"
            if [[ -e $dest ]]; then
                if ! cmp -s "$file" "$dest"; then
                    log "QDSS_CAPTURE_HASH_COLLISION $device sha=$sha"
                    exit 5
                fi
                rm -f "$file"
                log "QDSS_CAPTURE_ALREADY_ARCHIVED $device sha=$sha"
            else
                mv -- "$file" "$dest"
                log "QDSS_CAPTURED $device sha=$sha bytes=$(stat -c %s "$dest")"
            fi
            partial=''
            if [[ ! -e $root/$sha.context.txt ]]; then
                {
                    echo "observed_utc=$(date -u -Is)"
                    echo "remote=$host"
                    echo "devcore=$device"
                    echo "sys_device=$sys_device"
                    echo "sha256=$sha"
                    echo "bytes=$(stat -c %s "$dest")"
                    # shellcheck disable=SC2016
                    remote 'echo boot=$(cat /proc/sys/kernel/random/boot_id);
                        echo revision=$(cat /etc/openwrt_version);
                        echo kernel=$(uname -r);
                        echo q6=$(for p in /sys/class/remoteproc/remoteproc0 /sys/class/remoteproc/remoteproc1 /sys/class/remoteproc/remoteproc2; do
                            cat "$p/state"; done | tr "\n" ",");
                        dmesg | tail -n 100' || :
                } > "$root/$sha.context.txt"
            fi
            completed[$device]=1
        done <<< "$entries"
    else
        log 'QDSS_CAPTURE_ROUTER_UNREACHABLE'
    fi
    sleep "$poll"
done
