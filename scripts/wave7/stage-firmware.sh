#!/bin/sh
set -eu

repo=$(CDPATH="" cd -- "$(dirname -- "$0")/../.." && pwd)
vendor_manifest="$repo/scripts/wave7/firmware.sha256"
diagnostic_manifest="$repo/scripts/wave7/diagnostic-firmware.sha256"
diagnostic_source="$repo/scripts/wave7/diagnostic-firmware"

# Every staged file must be included by exactly one pinned manifest.
# Vendor blobs remain private; opt-in diagnostic configs are distinct.
verify_tree() {
    dir=$1
    shift
    [ -d "$dir" ] || {
        echo "Missing Wave 7 ath12k firmware: $dir" >&2
        exit 1
    }

    expected=$(
        for manifest do
            sed -n 's/^[[:xdigit:]]\{64\}  //p' "$manifest"
        done | LC_ALL=C sort
    )
    actual=$(cd "$dir" && find . -type f -printf '%P\n' | LC_ALL=C sort)
    [ "$actual" = "$expected" ] || {
        echo "Wave 7 firmware file set mismatch in $dir" >&2
        printf 'Expected:\n%s\nFound:\n%s\n' "$expected" "$actual" >&2
        exit 1
    }

    for manifest do
        (cd "$dir" && sha256sum --check --status "$manifest") || {
            echo "Wave 7 firmware checksum mismatch in $dir: $manifest" >&2
            exit 1
        }
    done
}

mode=stage
[ "$#" -eq 0 ] || mode=$1
case "$mode" in
    stage)
        source="$HOME/firmware/wave7/vendor-radio/ath12k"
        [ -z "$(printenv WAVE7_FIRMWARE_SOURCE || :)" ] || source="$WAVE7_FIRMWARE_SOURCE"
        verify_tree "$source" "$vendor_manifest"
        verify_tree "$diagnostic_source" "$diagnostic_manifest"

        overlay="$repo/files/lib/firmware/ath12k"
        mkdir -p "$overlay"
        rsync -a --delete "$source/" "$overlay/"
        rsync -a "$diagnostic_source/" "$overlay/"
        verify_tree "$overlay" "$vendor_manifest" "$diagnostic_manifest"
        count=$(printf '%s\n' "$expected" | wc -l)
        printf 'Staged %s verified Wave 7 firmware and diagnostic files\n' "$count"
        ;;
    verify-root)
        [ "$#" -eq 2 ] || {
            echo "Usage: $0 verify-root ROOTFS" >&2
            exit 2
        }
        verify_tree "$2/lib/firmware/ath12k" "$vendor_manifest" "$diagnostic_manifest"
        ;;
    *)
        echo "Usage: $0 [stage | verify-root ROOTFS]" >&2
        exit 2
        ;;
esac
