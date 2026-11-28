# Passive debugfs snapshots only: never use this for files whose reads issue
# firmware requests. A failed read is discarded; only an exact EBUSY is retried.
read_debugfs(){
    local f="$1" data attempt=1
    while :; do
        if data=$(cat "$f" 2>&1); then
            printf '%s\n' "$data"
            return 0
        fi
        case "$data" in
            'cat: read error: Resource busy'|'cat: read error: Device or resource busy')
                if [ "$attempt" -lt 5 ]; then
                    attempt=$((attempt + 1))
                    # The target BusyBox has integer-only sleep and no usleep.
                    ucode -e 'exit(sleep(20) ? 0 : 1);' || return 1
                    continue
                fi
                ;;
        esac
        printf 'debugfs %s: %s\n' "$f" "$data" >&2
        return 1
    done
}
