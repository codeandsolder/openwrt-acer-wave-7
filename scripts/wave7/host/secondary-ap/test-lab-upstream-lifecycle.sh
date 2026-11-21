#!/usr/bin/env bash
# Exercise the actual scope-specific unit lifecycle helper, not systemd.
set -euo pipefail
source_file="$(dirname "$(realpath "$0")")/lab-upstream.sh"
helper=$(awk '/^prepare_upstream_unit\(\) \{$/{emit=1} emit{print} emit && /^\}$/{exit}' "$source_file")
[[ $helper == 'prepare_upstream_unit() {'* && $helper == *'}' ]]
eval "$helper"
unit=wave7-lab-upstream-guard8
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
marker=$tmp/reset
systemctl() {
  if [[ $1 == reset-failed ]]; then
    [[ $2 == "$unit.service" ]]
    : > "$marker"
    return 0
  fi
  [[ $1 == show && $2 == "$unit.service" && $3 == -p && $5 == --value ]]
  case "$4" in
    LoadState)
      if [[ -e $marker && $collected == yes ]]; then echo not-found; else echo "$load"; fi ;;
    ActiveState) echo "$active" ;;
    Transient) echo "$transient" ;;
    Result) echo "$result" ;;
    MainPID) echo "$pid" ;;
    FragmentPath) echo "$fragment" ;;
    *) return 1 ;;
  esac
}
sleep() { :; }
load=loaded active=failed transient=yes result=timeout pid=0
fragment=/run/systemd/transient/$unit.service
collected=yes
prepare_upstream_unit
[[ -e $marker ]]
rm "$marker"
load=not-found
prepare_upstream_unit
[[ ! -e $marker ]]
load=loaded
for field in active transient result pid fragment; do
  old=${!field}
  printf -v "$field" '%s' wrong
  if prepare_upstream_unit 2>"$tmp/error"; then
    echo "accepted unexpected $field" >&2
    exit 1
  fi
  [[ ! -e $marker ]]
  printf -v "$field" '%s' "$old"
done
collected=no
if prepare_upstream_unit 2>"$tmp/error"; then
  echo 'accepted an uncollected unit' >&2
  exit 1
fi
[[ -e $marker ]]
echo LAB_UPSTREAM_LIFECYCLE_SELFTEST_PASS
