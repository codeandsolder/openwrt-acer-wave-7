#!/usr/bin/env bash
# Build the exact MT7925 diagnostic module configuration, without enabling
# unrelated mt76 drivers from the installed kernel's configuration.
set -Eeuo pipefail
usage() {
    printf 'Usage: %s HEADERS SOURCE OUTPUT REFERENCE_SYMVERS [JOBS]\n' "${0##*/}" >&2
}
if [[ $# == 1 && $1 == --help ]]; then
    usage
    exit 0
fi
if (( $# < 4 || $# > 5 )); then
    usage
    exit 2
fi
headers=$(realpath -e -- "$1")
source=$(realpath -e -- "$2")
output=$(realpath -m -- "$3")
reference=$(realpath -e -- "$4")
jobs=${5:-8}
[[ -d $headers && -f $headers/Makefile && -d $source && -f $source/Makefile &&
   -f $reference && $jobs =~ ^[1-9][0-9]*$ &&
   $output != / && $output != "$source" && $output != "$headers" ]]
# Do not compile on a host where the strict shared-cache wrapper is absent.
[[ $(readlink -f "$(command -v clang)") == /usr/local/libexec/sccache-strict-wrappers/clang ]]
mkdir -p -- "$output"
make -C "$headers" M="$source" MO="$output" LLVM=1 "-j$jobs" \
    CONFIG_MT76_CORE=m CONFIG_MT76_USB=m CONFIG_MT76_CONNAC_LIB=m \
    CONFIG_MT792x_LIB=m CONFIG_MT792x_USB=m CONFIG_MT7925_COMMON=m \
    CONFIG_MT7925E=m CONFIG_MT7925U=m \
    CONFIG_MT76_SDIO= CONFIG_MT76x02_LIB= CONFIG_MT76x02_USB= \
    CONFIG_MT76x0_COMMON= CONFIG_MT76x2_COMMON= CONFIG_MT7603E= \
    CONFIG_MT7615_COMMON= CONFIG_MT7915E= CONFIG_MT7921_COMMON= \
    CONFIG_MT7996E= modules
cmp "$output/Module.symvers" "$reference"
printf 'MT7925_CLOSURE_ABI_PASS\n'
