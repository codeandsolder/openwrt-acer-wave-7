#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "usage: $0 TRIAL_TAG WRAPPED_IMAGE EXPECT_KERNEL EXPECT_REV" >&2
    exit 2
}

TAG=${1:-}
LOCAL=${2:-}
EXPECT_KERNEL=${3:-}
EXPECT_REV=${4:-}
[[ -n "$TAG" && -n "$LOCAL" && -n "$EXPECT_KERNEL" && -n "$EXPECT_REV" ]] || usage
[[ $EXPECT_KERNEL =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $EXPECT_REV =~ ^[0-9a-f]{10}$ ]] || usage
[[ "$TAG" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "unsafe trial tag: $TAG" >&2; exit 2; }
[[ -f "$LOCAL" ]] || { echo "image not found: $LOCAL" >&2; exit 2; }

EXPECT=$(sha256sum "$LOCAL" | awk '{print $1}')
SIZE=$(stat -c %s "$LOCAL")
PRISTINE="/tmp/wave7-${TAG}-pristine.bin"
CHECK="/tmp/wave7-${TAG}-check.bin"
PART="${PRISTINE}.part"

KEY=/home/jan/.ssh/wave7-root-rsa
HOST=root@192.168.76.1
OPEN_WATCH=/home/jan/scripts/wave7/wave7-openwrt-watch.sh
FALLBACK_WATCH=/home/jan/scripts/wave7/wave7-fallback-watch.sh

SSH=(
  ssh -i "$KEY"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o ConnectTimeout=3
  -o ConnectionAttempts=1
  -o KexAlgorithms=diffie-hellman-group14-sha1
  -o HostKeyAlgorithms=ssh-rsa
  -o PubkeyAcceptedAlgorithms=ssh-rsa
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  "$HOST"
)
SCP=(
  scp -O -i "$KEY"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o ConnectTimeout=5
  -o KexAlgorithms=diffie-hellman-group14-sha1
  -o HostKeyAlgorithms=ssh-rsa
  -o PubkeyAcceptedAlgorithms=ssh-rsa
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

echo '=== LOCAL IMAGE ==='
printf 'tag=%s\nsize=%s\nsha256=%s\npath=%s\nexpected_kernel=%s\nexpected_revision=%s\n' "$TAG" "$SIZE" "$EXPECT" "$LOCAL" "$EXPECT_KERNEL" "$EXPECT_REV"

echo '=== LIVE BASELINE ==='
base_kernel=$("${SSH[@]}" 'uname -r')
[[ "$base_kernel" == 5.4.213 ]] || { echo "refusing: expected vendor kernel 5.4.213, got $base_kernel" >&2; exit 3; }
base_bootfail=$("${SSH[@]}" 'fw_printenv -n bootfail 2>/dev/null || true')
[[ "$base_bootfail" == 0 ]] || { echo "refusing: expected bootfail=0, got ${base_bootfail:-<empty>}" >&2; exit 3; }
"${SSH[@]}" 'uname -a; printf "bootfail="; fw_printenv -n bootfail; df -h /tmp'

echo '=== STAGING PRISTINE IMAGE ==='
"${SSH[@]}" "rm -f '$PRISTINE' '$CHECK' '$PART'"
staged=0
for attempt in 1 2; do
    if "${SCP[@]}" "$LOCAL" "$HOST:$PART"; then
        if "${SSH[@]}" sh -s -- "$PART" "$PRISTINE" "$EXPECT" "$SIZE" <<'REMOTE_STAGE'
set -eu
PART=$1
PRISTINE=$2
EXPECT=$3
SIZE=$4
for i in $(seq 1 20); do
    if [ -f "$PART" ]; then
        size=$(stat -c %s "$PART" 2>/dev/null || echo 0)
        if [ "$size" = "$SIZE" ]; then
            got=$(sha256sum "$PART" | awk '{print $1}')
            if [ "$got" = "$EXPECT" ]; then
                mv "$PART" "$PRISTINE"
                exit 0
            fi
        fi
    fi
    sleep 1
done
echo "staged image failed verification" >&2
exit 1
REMOTE_STAGE
        then
            staged=1
            break
        fi
    fi
    echo "staging attempt $attempt failed; retrying" >&2
    "${SSH[@]}" "rm -f '$PART' '$PRISTINE'" || true
done
[[ "$staged" == 1 ]] || { echo "failed to stage verified pristine image" >&2; exit 4; }
"${SSH[@]}" sh -s -- "$PRISTINE" "$EXPECT" "$SIZE" <<'REMOTE_VERIFY'
set -eu
PRISTINE=$1
EXPECT=$2
SIZE=$3
got=$(sha256sum "$PRISTINE" | awk '{print $1}')
size=$(stat -c %s "$PRISTINE")
echo "router_sha256=$got"
echo "router_size=$size"
[ "$got" = "$EXPECT" ]
[ "$size" = "$SIZE" ]
REMOTE_VERIFY

echo '=== ARMING SUPERVISED WATCHERS ==='
# Run as user units so observers outlive the flashing shell and its terminal.
# SentinelX/noninteractive sessions do not always export the user bus.
RUNTIME_DIR="/run/user/$(id -u)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-$RUNTIME_DIR}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
OPEN_UNIT="wave7-openwrt-watch-$TAG.service"
FALLBACK_UNIT="wave7-fallback-watch-$TAG.service"
systemd-run --user --unit="${OPEN_UNIT%.service}" --collect \
    --property=Type=exec --property=Restart=on-abnormal \
    --property=RestartSec=2 -- "$OPEN_WATCH" "$TAG" "$EXPECT_KERNEL" "$EXPECT_REV"
if ! systemd-run --user --unit="${FALLBACK_UNIT%.service}" --collect \
    --property=Type=exec --property=Restart=on-abnormal \
    --property=RestartSec=2 -- "$FALLBACK_WATCH" "$TAG"; then
    systemctl --user stop "$OPEN_UNIT" >/dev/null || true
    echo 'failed to start fallback watcher' >&2
    exit 5
fi
sleep 2
if ! systemctl --user is-active --quiet "$OPEN_UNIT" || \
   ! systemctl --user is-active --quiet "$FALLBACK_UNIT"; then
    systemctl --user stop "$OPEN_UNIT" "$FALLBACK_UNIT" >/dev/null || true
    echo 'watcher supervision failed; refusing flash' >&2
    exit 5
fi
printf 'openwrt_unit=%s\nfallback_unit=%s\n' "$OPEN_UNIT" "$FALLBACK_UNIT"

echo '=== VALIDATE / ARM / FLASH ==='
set +e
"${SSH[@]}" sh -s -- "$PRISTINE" "$CHECK" "$EXPECT" "$SIZE" <<'REMOTE_FLASH'
set -eu
PRISTINE=$1
CHECK=$2
EXPECT=$3
SIZE=$4
got=$(sha256sum "$PRISTINE" | awk '{print $1}')
size=$(stat -c %s "$PRISTINE")
[ "$got" = "$EXPECT" ]
[ "$size" = "$SIZE" ]
rm -f "$CHECK"
cp "$PRISTINE" "$CHECK"
echo VALIDATING_DISPOSABLE_COPY
/sbin/sysupgrade -T "$CHECK"
rm -f "$CHECK"
got=$(sha256sum "$PRISTINE" | awk '{print $1}')
[ "$got" = "$EXPECT" ] || { echo "PRISTINE_MUTATED expected=$EXPECT got=$got" >&2; exit 2; }
mount -t pstore pstore /sys/fs/pstore 2>/dev/null || true
rm -f /sys/fs/pstore/*-ramoops-* 2>/dev/null || true
fw_setenv bootfail 4
bf=$(fw_printenv -n bootfail 2>/dev/null || true)
[ "$bf" = 4 ] || { echo "BOOTFAIL_ARM_FAILED got=$bf" >&2; exit 2; }
echo "BOOTFAIL_ARMED=4"
echo "IMAGE_SHA256=$got"
echo FLASHING_NOW
/sbin/sysupgrade "$PRISTINE"
REMOTE_FLASH
flash_rc=$?
set -e

echo "flash_ssh_rc=$flash_rc"
echo "openwrt_capture=/tmp/wave7-${TAG}-openwrt-capture.txt"
echo "fallback_capture=/tmp/wave7-${TAG}-pstore.txt"
echo "openwrt_log=/tmp/wave7-${TAG}-openwrt-watch.log"
echo "fallback_log=/tmp/wave7-${TAG}-fallback-watch.log"
