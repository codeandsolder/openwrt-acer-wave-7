#!/usr/bin/env bash
set -Eeuo pipefail
script=$(cd -- "$(dirname -- "$0")" && pwd)/watch-noc-kmsg.sh
tmp=$(mktemp -d "${TMPDIR:-/tmp}/wave7-kmsg-test.XXXXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/captures"
cat > "$tmp/bin/ssh" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
last=''
for a in "$@"; do last=$a; done
case "$last" in
  *'test -r /dev/kmsg'*)
    echo BOOT_ID=12345678-aaaa-bbbb-cccc-0123456789ab
    echo REV=r0+38249-3b1851eda6
    ;;
  *'exec cat /dev/kmsg'*)
    echo WAVE7_KMSG_BOOT=12345678-aaaa-bbbb-cccc-0123456789ab
    echo WAVE7_KMSG_REV=r0+38249-3b1851eda6
    echo '4,311,406000000,-;NOC ERROR DETECTED'
    echo '4,312,406000200,-;not a fatal record'
    ;;
  *'====ROUTER_CONTEXT===='*)
    echo ====ROUTER_CONTEXT====
    if [[ ${WAVE7_TEST_STALE_BOOT:-0} == 1 ]]; then
      echo BOOT_ID=12345678-ffff-bbbb-cccc-0123456789ab
    else
      echo BOOT_ID=12345678-aaaa-bbbb-cccc-0123456789ab
    fi
    echo REV=r0+38249-3b1851eda6
    echo ====KERNEL_DMESG====
    echo '[ 406.000] NOC ERROR DETECTED'
    ;;
  *) exit 3 ;;
esac
MOCK
chmod 750 "$tmp/bin/ssh"
export PATH="$tmp/bin:$PATH"
export WAVE7_Q6_SSH_KEY="$tmp/bin/ssh"
export WAVE7_NOC_EVENT_DIR="$tmp/captures"
"$script" --check | rg -q 'KMSG_STREAM_CHECK_PASS'
export WAVE7_TEST_STALE_BOOT=1
timeout 4 "$script" --run > "$tmp/stale.log" 2>&1 || test "$?" -eq 124
rg -q 'KMSG_EVENT_SAVED' "$tmp/stale.log"
rg -q 'KMSG_CONTEXT_UNAVAILABLE' "$tmp/stale.log"
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.event.txt' | wc -l) == 1 ]]
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.kernel.txt' | wc -l) == 0 ]]
unset WAVE7_TEST_STALE_BOOT
timeout 4 "$script" --run > "$tmp/ok.log" 2>&1 || test "$?" -eq 124
rg -q 'KMSG_CONTEXT_ARCHIVED' "$tmp/ok.log"
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.event.txt' | wc -l) == 1 ]]
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.kernel.txt' | wc -l) == 1 ]]
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.sha256' | wc -l) == 2 ]]
( cd "$tmp/captures" && sha256sum -c -- *.sha256 )
test -z "$(find "$tmp/captures" -maxdepth 1 -name '.noc-kmsg.partial.*' -print -quit)"
echo KMSG_STREAM_EVENT_PERSISTENCE_AND_DEDUP_PASS
