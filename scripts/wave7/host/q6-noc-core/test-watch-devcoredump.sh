#!/usr/bin/env bash
# Offline fixture verifies streaming capture, deduplication, and metadata.
# Does not contact router or inject a crash.
set -Eeuo pipefail
tmp=$(mktemp -d /tmp/wave7-q6-devcore-test.XXXXXXXX)
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/captures"
cat > "$tmp/bin/ssh" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
last=''
for arg in "$@"; do last=$arg; done
case "$last" in
  *'/sys/class/devcoredump/devcd[0-9]*/data'*)
    echo devcd0
    ;;
  *'/sys/class/devcoredump/devcd0/data'*)
    cat /bin/true
    ;;
  *)
    echo 'MOCK_ROUTER_CONTEXT'
    ;;
esac
MOCK
chmod 755 "$tmp/bin/ssh"
watcher=$(cd -- "$(dirname -- "$0")" && pwd)/watch-devcoredump.sh
export WAVE7_Q6_DUMP_DIR="$tmp/captures"
export WAVE7_Q6_POLL_SECONDS=2
export PATH="$tmp/bin:$PATH"
"$watcher" --check | rg 'EXISTING_DUMP devcd0'
timeout 6 "$watcher" --run > "$tmp/log1" 2>&1 || test "$?" -eq 124
rg 'CAPTURED devcd0' "$tmp/log1"
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.elf' | wc -l) == 1 ]]
hash=$(sha256sum /bin/true | cut -d' ' -f1)
cmp /bin/true "$tmp/captures/$hash.elf"
rg 'MOCK_ROUTER_CONTEXT' "$tmp/captures/$hash.context.txt"
timeout 3 "$watcher" --run > "$tmp/log2" 2>&1 || test "$?" -eq 124
rg 'ALREADY_CAPTURED devcd0' "$tmp/log2"
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.elf' | wc -l) == 1 ]]
test -z "$(find "$tmp/captures" -maxdepth 1 -name '.capture.*' -print -quit)"
echo 'MOCK_CAPTURE_DEDUP_METADATA_PASS'
