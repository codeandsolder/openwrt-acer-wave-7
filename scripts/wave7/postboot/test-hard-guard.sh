#!/usr/bin/env bash
# Isolated, deterministic tests of the actual hard-guard shell control flow.
# ONLY a transformed copy under mktemp is run. All kernel/device writes and
# peer probes are redirected into the disposable test fixture.
set -euo pipefail
source_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
source_guard="$source_dir/wave7-postboot-hard-guard.sh"
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/mockbin"
expected=01b10604-4a1f-4b81-9909-7d2b061aa49b
trial_id=trial-a-879f5b56

cat > "$tmp/mockbin/ping" <<'MOCK'
#!/bin/sh
count=$(cat "$MOCK_CASE/ping_count")
count=$((count + 1))
printf '%s\n' "$count" > "$MOCK_CASE/ping_count"
mode=$(cat "$MOCK_CASE/ping_mode")
case "$mode" in
  good) exit 0 ;;
  bad) exit 1 ;;
  eventually-good) [ "$count" -ge 2 ] ;;
  rearm-on-success) printf 'new-trial\n' > "$MOCK_CASE/token"; exit 0 ;;
  *) exit 70 ;;
esac
MOCK
cat > "$tmp/mockbin/sleep" <<'MOCK'
#!/bin/sh
count=$(cat "$MOCK_CASE/sleep_count")
count=$((count + 1))
printf '%s\n' "$count" > "$MOCK_CASE/sleep_count"
action=$(cat "$MOCK_CASE/sleep_action")
case "$action:$count" in
  cancel-first:1|cancel-final:4) rm -f "$MOCK_CASE/token" ;;
  rearm-first:1|rearm-final:4) printf 'new-trial\n' > "$MOCK_CASE/token" ;;
  boot-changed:1) printf 'other-boot\n' > "$MOCK_CASE/boot-id" ;;
  barrier:1)
    : > "$MOCK_CASE/at-barrier"
    i=0
    while [ ! -e "$MOCK_CASE/release" ] && [ "$i" -lt 150 ]; do
      /bin/sleep 0.02
      i=$((i + 1))
    done
    [ -e "$MOCK_CASE/release" ]
    ;;
esac
MOCK
cat > "$tmp/mockbin/sync" <<'MOCK'
#!/bin/sh
exit 0
MOCK
chmod +x "$tmp/mockbin/"*

make_fixture() {
  name=$1
  case_dir="$tmp/$name"
  mkdir -p "$case_dir"
  printf '%s\n' "$expected" > "$case_dir/boot-id"
  printf '%s\n' "$trial_id" > "$case_dir/token"
  printf 'bad\n' > "$case_dir/ping_mode"
  printf 'none\n' > "$case_dir/sleep_action"
  printf '0\n' > "$case_dir/ping_count"
  printf '0\n' > "$case_dir/sleep_count"
  # Substitute ALL device paths before running the copy. There is never a
  # connection to Wave 7 and no access to a real kernel crash trigger.
  sed -e "s@/proc/sys/kernel/random/boot_id@$case_dir/boot-id@g" \
      -e "s@/tmp/wave7-postboot-trial.arm@$case_dir/token@g" \
      -e "s@/dev/kmsg@$case_dir/kmsg@g" \
      -e "s@/proc/sysrq-trigger@$case_dir/recovery-request@g" \
      "$source_guard" > "$case_dir/guard.sh"
  if rg -q '(/proc/sysrq-trigger|/dev/kmsg|/tmp/wave7-postboot-trial.arm|/proc/sys/kernel/random/boot_id)' "$case_dir/guard.sh"; then
    echo "FAIL $name: unredirected device path in test copy" >&2
    exit 1
  fi
  /bin/sh -n "$case_dir/guard.sh"
}

run() {
  name=$1
  want_rc=$2
  want_recovery=$3
  make_fixture "$name"
  case "$name" in
    missing-token) rm "$case_dir/token" ;;
    wrong-token) printf 'wrong-boot\n' > "$case_dir/token" ;;
    wrong-boot) printf 'wrong-boot\n' > "$case_dir/boot-id" ;;
    healthy) printf 'good\n' > "$case_dir/ping_mode" ;;
    transient) printf 'eventually-good\n' > "$case_dir/ping_mode" ;;
    cancel-first) printf 'cancel-first\n' > "$case_dir/sleep_action" ;;
    cancel-final) printf 'cancel-final\n' > "$case_dir/sleep_action" ;;
    rearm-first) printf 'rearm-first\n' > "$case_dir/sleep_action" ;;
    rearm-final) printf 'rearm-final\n' > "$case_dir/sleep_action" ;;
    rearm-on-success) printf 'rearm-on-success\n' > "$case_dir/ping_mode" ;;
    boot-changed) printf 'boot-changed\n' > "$case_dir/sleep_action" ;;
  esac
  set +e
  MOCK_CASE="$case_dir" PATH="$tmp/mockbin:$PATH" \
    timeout 5 /bin/sh "$case_dir/guard.sh" "$expected" "$trial_id" \
    > "$case_dir/stdout" 2> "$case_dir/stderr"
  rc=$?
  set -e
  if [ "$rc" -ne "$want_rc" ]; then
    echo "FAIL $name: exit=$rc expected=$want_rc" >&2
    cat "$case_dir/stderr" >&2
    exit 1
  fi
  if [ "$want_recovery" = yes ]; then
    [ -f "$case_dir/recovery-request" ] &&
      [ "$(cat "$case_dir/recovery-request")" = c ] || {
        echo "FAIL $name: no fixture recovery request" >&2
        exit 1
      }
  elif [ -e "$case_dir/recovery-request" ]; then
    echo "FAIL $name: unexpected recovery request" >&2
    exit 1
  fi
  case "$name" in
    rearm-*)
      [ "$(cat "$case_dir/token")" = new-trial ] || {
        echo "FAIL $name: old guard consumed the replacement token" >&2
        exit 1
      }
      ;;
  esac
  printf 'PASS %s\n' "$name"
}

run missing-token 2 no
run wrong-token 2 no
run wrong-boot 2 no
run healthy 0 no
run transient 0 no
run persistent 5 yes
run cancel-first 0 no
run cancel-final 0 no
run boot-changed 0 no
run rearm-first 0 no
run rearm-final 0 no
run rearm-on-success 0 no

make_fixture async-cancellation
printf 'barrier\n' > "$case_dir/sleep_action"
MOCK_CASE="$case_dir" PATH="$tmp/mockbin:$PATH" \
  /bin/sh "$case_dir/guard.sh" "$expected" "$trial_id" \
  > "$case_dir/stdout" 2> "$case_dir/stderr" &
pid=$!
i=0
while [ ! -e "$case_dir/at-barrier" ] && [ "$i" -lt 100 ]; do
  /bin/sleep 0.02
  i=$((i + 1))
done
if [ ! -e "$case_dir/at-barrier" ]; then
  kill "$pid" 2>/dev/null || :
  echo "FAIL async-cancellation: process never reached its sleep barrier" >&2
  exit 1
fi
rm -f "$case_dir/token"
: > "$case_dir/release"
wait "$pid"
test ! -e "$case_dir/recovery-request"
printf 'PASS async-cancellation (real child process, token withdrawn during sleep)\n'
# The operational launcher must pin the exact script bytes we just tested.
launcher="$source_dir/controlled-postboot-link-flap.sh"
for file in "$source_guard" "$source_dir/wave7-postboot-link-monitor.sh"; do
  digest=$(sha256sum "$file")
  digest=${digest%% *}
  if ! rg -Fq "$digest" "$launcher"; then
    echo "FAIL launcher lacks pinned SHA256 for $file" >&2
    exit 1
  fi
done
printf 'PASS launcher pins exact monitor and guard source hashes\n'
echo '13 isolated hard-guard cases PASS; no router state touched'
