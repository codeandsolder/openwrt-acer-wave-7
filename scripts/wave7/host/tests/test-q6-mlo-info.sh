#!/usr/bin/env bash
set -Eeuo pipefail
guard=$(dirname "$0")/../q6-recovery-guard.sh
good=$(cat <<'TEXT'
Interface ap-mld0
 type AP
 MLD with links:
  - link ID  0 link addr 70:5a:6f:5a:bb:16
    channel 1 (2412 MHz), width: 20 MHz
    txpower 18.00 dBm
  - link ID  1 link addr 4e:5a:6f:5a:bb:16
    channel 40 (5200 MHz), width: 80 MHz
    txpower 18.00 dBm
 Radios: 0 1
TEXT
)
if ! printf '%s\n' "$good" | /bin/sh "$guard" --test-mlo-info; then
  echo 'healthy MLO rejected' >&2; exit 1
fi
fail() {
  if printf '%s\n' "$1" | /bin/sh "$guard" --test-mlo-info; then
    echo "invalid MLO accepted: $2" >&2; exit 1
  fi
}
fail "$(printf '%s\n' "$good" | sed '0,/txpower 18.00/s/txpower 18.00/txpower 0.00/')" "first link powered down"
fail "$(printf '%s\n' "$good" | sed '/- link ID  1/,$d')" 'missing second link'
fail "$(printf '%s\n' "$good" | sed 's/txpower 18.00/txpower 0.00/g')" 'both links powered down'
fail "$(printf '%s\n' "$good" | sed '/- link ID  1/,/txpower 18.00/d')" 'no link1 despite link0 power'
fail "$(printf '%s\n' "$good" | sed 's/- link ID  1/- link ID  0/')" 'duplicate link0'
fail "$(printf '%s\n' "$good" | sed '/- link ID  1/,$d' | sed '$a\Interface unrelated\n txpower 18.00 dBm')" 'other interface does not count'
echo Q6_MLO_GUARD_TESTS_PASS
