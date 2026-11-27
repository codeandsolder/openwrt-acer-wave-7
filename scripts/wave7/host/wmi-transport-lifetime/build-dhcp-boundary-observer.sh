#!/usr/bin/env bash
# Build the same observer source for both isolated lab targets.
set -Eeuo pipefail
[[ $# == 2 ]] || { echo "usage: $0 OUTPUT_DIR AARCH64_OPENWRT_GCC" >&2; exit 2; }
src=$(dirname "$(realpath "$0")")
mkdir -p "$1"
out=$(realpath -e "$1")
cross=$(realpath -e "$2")
[[ -x $cross && -x /usr/bin/musl-gcc ]] || exit 2
cache=$(command -v sccache)
[[ -x $cache ]] || exit 2
tmp=$(mktemp -d "$out/.build.XXXXXXXX")
trap 'rm -f "$tmp"/{host.o,arm.o,dhcp-boundary-x86_64,dhcp-boundary-arm64}; rmdir "$tmp"' EXIT
common=(-std=c11 -O2 -Wall -Wextra -Werror)
# Acer's static glibc is built for x86-64-v3; the N4100 client has no AVX.
# Use the generic musl sysroot rather than linking Acer's libc.
"$cache" /usr/bin/musl-gcc "${common[@]}" -march=x86-64 -mtune=generic \
    -idirafter /usr/include -c "$src/dhcp-boundary-observer.c" -o "$tmp/host.o"
/usr/bin/musl-gcc -static "$tmp/host.o" -o "$tmp/dhcp-boundary-x86_64"
"$cache" "$cross" "${common[@]}" -march=armv8-a -mtune=cortex-a53 \
    -c "$src/dhcp-boundary-observer.c" -o "$tmp/arm.o"
"$cross" -static "$tmp/arm.o" -o "$tmp/dhcp-boundary-arm64"
for tool in dhcp-boundary-x86_64 dhcp-boundary-arm64; do
    ! readelf -l "$tmp/$tool" | grep -q INTERP
done
readelf -h "$tmp/dhcp-boundary-x86_64" | grep -q 'Advanced Micro Devices X86-64'
readelf -h "$tmp/dhcp-boundary-arm64" | grep -q 'AArch64'
netns=$(readlink /proc/self/ns/net)
unshare -Urn uv run --no-project --offline python -B \
    "$src/test-dhcp-boundary-observer.py" "$tmp/dhcp-boundary-x86_64" --parent-netns "$netns"
for tool in dhcp-boundary-x86_64 dhcp-boundary-arm64; do
    mv "$tmp/$tool" "$out/$tool"
done
(cd "$out" && sha256sum dhcp-boundary-x86_64 dhcp-boundary-arm64 > dhcp-boundary-binaries.sha256)
