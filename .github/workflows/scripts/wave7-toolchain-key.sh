#!/usr/bin/env bash
# Identity of the actual toolchain inputs, resolved canonical configuration,
# immutable buildworker image and the build recipe. Board/kernel patches
# outside these build-system inputs do not invalidate the compiler.
set -euo pipefail
if (( $# != 2 )); then
    echo "usage: $0 SOURCE RESOLVED_CONFIG" >&2
    exit 2
fi
source=$1
config=$2
recipe=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
{
    printf '%s\n' 'wave7-toolchain-v2' 'sha256:3d9edeb63c9bee5151b314f9620d9565657abba6e1450b2959e66bdeade286fe'
    git -C "$source" ls-tree -r -z --full-tree HEAD -- \
        Makefile rules.mk Config.in feeds.conf.default \
        include tools toolchain config scripts \
        package/Makefile package/libs/toolchain \
        target/Makefile target/toolchain \
        target/linux/qualcommbe/Makefile \
        target/linux/qualcommbe/ipq53xx/target.mk
    sha256sum "$config" "$recipe/wave7-ci-build.sh" "$recipe/wave7-toolchain-key.sh" | cut -d' ' -f1
} | sha256sum | cut -d' ' -f1
