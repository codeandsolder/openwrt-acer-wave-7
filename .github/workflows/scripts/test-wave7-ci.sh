#!/usr/bin/env bash
set -euo pipefail
scripts=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
repo=$tmp/repo
git init -q "$repo"
git -C "$repo" config user.name CI
git -C "$repo" config user.email ci@example.invalid
cd "$repo"
mkdir -p target/linux/qualcommbe/ipq53xx package/example toolchain
touch target/linux/qualcommbe/ipq53xx/target.mk package/example/Makefile
echo initial > toolchain/Makefile
git add .
git commit -qm initial
base=$(git rev-parse HEAD)
echo CONFIG_TARGET_qualcommbe_ipq53xx=y > "$tmp/config"
key=$(bash "$scripts/wave7-toolchain-key.sh" "$repo" "$tmp/config")
echo patch > target/linux/qualcommbe/ipq53xx/test.patch
git add .
git commit -qm kernel
bash "$scripts/wave7-ci-plan.sh" "$repo" push '' "$base" "$tmp/plan"
grep -Fxq mode=kernel "$tmp/plan"
test "$key" = "$(bash "$scripts/wave7-toolchain-key.sh" "$repo" "$tmp/config")"
echo change > package/example/Makefile
git add .
git commit -qm package
bash "$scripts/wave7-ci-plan.sh" "$repo" push '' "$base" "$tmp/plan"
grep -Fxq mode=packages "$tmp/plan"
grep -Fxq packages=all "$tmp/plan"
echo changed > toolchain/Makefile
git add .
git commit -qm toolchain
test "$key" != "$(bash "$scripts/wave7-toolchain-key.sh" "$repo" "$tmp/config")"
git rm -q target/linux/qualcommbe/ipq53xx/target.mk
git commit -qm missing
bash "$scripts/wave7-ci-plan.sh" "$repo" push '' "$base" "$tmp/plan"
grep -Fxq mode=none "$tmp/plan"
if bash "$scripts/wave7-ci-plan.sh" "$repo" workflow_dispatch kernel '' "$tmp/plan"; then
    echo 'Missing target was accepted' >&2
    exit 1
fi
echo 'Wave 7 CI scope and toolchain provenance tests passed'
