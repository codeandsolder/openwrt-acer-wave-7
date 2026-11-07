#!/bin/sh
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
manifest="$repo/scripts/wave7/firmware.sha256"

verify_tree() {
    dir=$1
    [ -d "$dir" ] || { echo "Missing Wave 7 ath12k firmware: $dir" >&2; exit 1; }

    expected=$(sed -n 's/^[[:xdigit:]]\{64\}  //p' "$manifest" | LC_ALL=C sort)
    actual=$(cd "$dir" && find . -type f -printf '%P\n' | LC_ALL=C sort)
    [ "$actual" = "$expected" ] || {
        echo "Wave 7 firmware file set mismatch in $dir" >&2
        printf 'Expected:\n%s\nFound:\n%s\n' "$expected" "$actual" >&2
        exit 1
    }

    (cd "$dir" && sha256sum --check --status "$manifest") || {
        echo "Wave 7 firmware checksum mismatch in $dir" >&2
        exit 1
    }
}

case "${1:-stage}" in
    stage)
        source="${WAVE7_FIRMWARE_SOURCE:-$HOME/firmware/wave7/vendor-radio/ath12k}"
        verify_tree "$source"
        overlay="$repo/files/lib/firmware/ath12k"
        mkdir -p "$overlay"
        rsync -a --delete "$source/" "$overlay/"
        verify_tree "$overlay"
        printf 'Staged %s verified Wave 7 firmware files from %s\n' "$(printf '%s\n' "$expected" | wc -l)" "$source"
        ;;
    verify-root)
        [ "$#" -eq 2 ] || { echo "Usage: $0 verify-root ROOTFS" >&2; exit 2; }
        verify_tree "$2/lib/firmware/ath12k"
        ;;
    *)
        echo "Usage: $0 [stage | verify-root ROOTFS]" >&2
        exit 2
        ;;
esac
