#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
phy=$tmp
source <(sed -n '/^sample(){/,/^}/p; /^drained(){/,/^}/p' ap-aql-profile.sh)
cat > "$phy/aql_pending" <<'EOF'
AC     AQL pending
VO     0 us
VI     0 us
BE     0 us
BK     0 us
BC/MC  0 us
total  0 us
EOF
drained
sed -i 's/^BE     0/BE     123/' "$phy/aql_pending"
sample
[[ $be == 123 && $total == 0 ]]
if drained; then exit 1; fi
sed -i 's/^BE     123/BE     4294967295/' "$phy/aql_pending"
if sample; then exit 1; fi
sed -i 's/^BE     4294967295/BE     0/' "$phy/aql_pending"
printf 'BE     0 us\n' >> "$phy/aql_pending"
if sample; then exit 1; fi
now=100.25
seconds=335
source <(sed -n '/^whole=/p; /^end=/p' ap-aql-profile.sh)
[[ $end == 435 ]]
printf 'AQL_PROFILE_SHELL_PASS\n'
