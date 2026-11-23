#!/usr/bin/env bash
set -euo pipefail
# Exact Git blob identities for the inputs that can affect the Wave 7 host
# tools and target toolchain. Ordinary kernel/board patches do not invalidate
# the compiler; changing a build-system or toolchain input does.
git ls-tree -r -z --full-tree HEAD -- \
  Makefile rules.mk Config.in feeds.conf.default \
  include tools toolchain config scripts \
  package/Makefile package/libs/toolchain \
  target/linux/qualcommbe/Makefile \
  target/linux/qualcommbe/ipq53xx/target.mk \
  .github/workflows/wave7-toolchain-image.yml \
  .github/workflows/scripts/wave7-toolchain-key.sh \
  | sha256sum | cut -d' ' -f1
