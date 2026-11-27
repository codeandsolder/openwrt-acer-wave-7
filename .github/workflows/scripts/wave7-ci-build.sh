#!/usr/bin/env bash
# Run inside the pinned OpenWrt buildworker as buildbot, in the source root.
set -euo pipefail
shopt -s nullglob
cache=.wave7-toolchain-cache
recipe=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
build() {
    make -j"$(nproc)" BUILD_LOG=1 "$@" ||
        ret=$? .github/workflows/scripts/show_build_failures.sh
}
configure() {
    cat > .config <<'CONFIG'
CONFIG_TARGET_qualcommbe=y
CONFIG_TARGET_qualcommbe_ipq53xx=y
CONFIG_DEVEL=y
CONFIG_AUTOREMOVE=y
CONFIG_CCACHE=y
CONFIG_KERNEL_WERROR=y
CONFIG_ALL_KMODS=y
CONFIG
    if [[ "$1" == packages ]]; then printf '%s\n' CONFIG_ALL=y >> .config; fi
    make defconfig
    grep -Fxq CONFIG_TARGET_qualcommbe=y .config
    grep -Fxq CONFIG_TARGET_qualcommbe_ipq53xx=y .config || {
        echo "Kconfig did not select the Wave 7 subtarget" >&2
        exit 1
    }
}
check_tree() {
    local destination=$1
    if git diff --exit-code; then return; fi
    mkdir -p "$destination"
    while IFS= read -r -d '' file; do
        if [[ -f "$file" ]]; then cp --parents -- "$file" "$destination/"; fi
    done < <(git diff --name-only -z)
    echo "Source fixups are required; see the uploaded artifacts" >&2
    return 1
}
case "${1:-}" in
    identity)
        # Fixed toolchain configuration, independent of kernel/package mode.
        configure kernel
        key=$(bash "$recipe/wave7-toolchain-key.sh" "$PWD" "$PWD/.config")
        printf 'key=%s\n' "$key" >> "$2"
        ;;
    prepare)
        key=$2
        [[ "$key" =~ ^[0-9a-f]{64}$ ]]
        if [[ "${3:-}" == true ]]; then
            test "$(cat "$cache/inputs")" = "$key"
            (cd "$cache" && sha256sum -c SHA256SUMS)
            ./scripts/ext-tools.sh --tools "$cache/host-tools.tar.zst"
            echo "Restored source-matched Wave 7 host tools and compiler"
        else
            mkdir -p "$cache"
            build tools/install
            build toolchain/install
            build target/toolchain/compile
            archives=(bin/targets/qualcommbe/ipq53xx/openwrt-toolchain*.tar.*)
            (( ${#archives[@]} == 1 ))
            mv -- "${archives[0]}" "$cache/toolchain.tar.zst"
            tar -I 'zstd -T0 -3' -cf "$cache/host-tools.tar.zst" staging_dir/host build_dir/host
            printf '%s\n' "$key" > "$cache/inputs"
            (cd "$cache" && sha256sum host-tools.tar.zst toolchain.tar.zst > SHA256SUMS)
        fi
        ;;
    validate)
        mode=$2
        packages=$3
        [[ "$mode" == kernel || "$mode" == packages ]]
        configure "$mode"
        # Both cold and warm validation use the exact same external compiler.
        # Remove the now-exported native toolchain build directories to keep
        # enough runner disk space for the actual kernel/packages.
        find build_dir staging_dir -mindepth 1 -maxdepth 1 -type d -name 'toolchain-*' -exec rm -rf -- {} +
        mkdir -p .wave7-external
        tar -xf "$cache/toolchain.tar.zst" -C .wave7-external
        toolchains=(.wave7-external/openwrt-toolchain*/toolchain-*)
        (( ${#toolchains[@]} == 1 ))
        ./scripts/ext-toolchain.sh --toolchain "$PWD/${toolchains[0]}" --overwrite-config --config qualcommbe/ipq53xx
        grep -Fxq CONFIG_TARGET_qualcommbe_ipq53xx=y .config
        grep -Fxq CONFIG_EXTERNAL_TOOLCHAIN=y .config
        # Use the archive's actual digest, not a mutable version label.
        compiler=$(sha256sum "$cache/toolchain.tar.zst" | cut -d' ' -f1)
        mkdir -p staging_dir/host/etc .ccache
        cat > staging_dir/host/etc/ccache.conf <<CONFIG
compiler_type=gcc
compiler_check=string:$compiler
max_size=2G
depend_mode=true
CONFIG
        export CCACHE_DIR="$PWD/.ccache"
        export CCACHE_CONFIGPATH2="$PWD/staging_dir/host/etc/ccache.conf"
        export MAKEFLAGS="CC_VERSION_TEXT=$compiler"
        ./scripts/diffconfig.sh
        build tools/install
        build toolchain/install
        if [[ "$mode" == packages ]]; then
            if [[ "$packages" == all ]]; then
                build package/download package/check FIXUP=1
            else
                for package in $packages; do
                    [[ "$package" =~ ^[A-Za-z0-9_.+-]+$ ]]
                    build "package/$package/download" "package/$package/check" FIXUP=1
                done
            fi
            check_tree packages-fixed
        fi
        make target/linux/refresh V=s
        check_tree qualcommbe-ipq53xx-refreshed
        # Quilt refresh prepares a patch-editing tree; compile the ordinary
        # pristine patched kernel, not the quilt-mode work tree.
        make target/linux/clean
        build target/compile
        build package/linux/compile
        if TOPDIR="$PWD" make -C target/linux dtb -q >/dev/null 2>&1; then
            build target/linux/dtb
        else
            result=$?
            if (( result == 1 )); then build target/linux/dtb; fi
        fi
        if [[ "$mode" == packages ]]; then build; fi
        staging_dir/host/bin/ccache -vv --show-stats
        ;;
    *) echo "usage: $0 identity|prepare|validate ..." >&2; exit 2 ;;
esac
