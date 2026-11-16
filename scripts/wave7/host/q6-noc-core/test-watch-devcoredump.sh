#!/usr/bin/env bash
# Offline test against one existing genuine Q6 core, no live hardware changes.
set -Eeuo pipefail
fixture=${WAVE7_TEST_CORE:-/home/jan/firmware/wave7/logs/q6-noc-20261110/repro2-q6-core.bin}
[[ -r $fixture ]] || { echo "Set WAVE7_TEST_CORE to an archived Q6 ELF core: $fixture" >&2; exit 2; }
[[ $(LC_ALL=C readelf -hW "$fixture") =~ Type:[[:space:]]*CORE[[:space:]] ]] || { echo "Fixture is not an ELF CORE" >&2; exit 2; }
export WAVE7_TEST_CORE="$fixture"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/wave7-q6-devcore-test.XXXXXXXX")
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
    case "${WAVE7_TEST_MODE:?}" in
      truncated) head -c 4096 "$WAVE7_TEST_CORE" ;;
      full) cat "$WAVE7_TEST_CORE" ;;
      *) exit 2 ;;
    esac
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

# SSH returning success with a truncated but valid ELF header must not be
# accepted as a complete crash core.
export WAVE7_TEST_MODE=truncated
"$watcher" --check | rg 'EXISTING_DUMP devcd0'
timeout 3 "$watcher" --run > "$tmp/truncated.log" 2>&1 || test "$?" -eq 124
rg 'FAILED_INVALID_ELF devcd0' "$tmp/truncated.log"
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.elf' | wc -l) == 0 ]]
test -z "$(find "$tmp/captures" -maxdepth 1 -name '.capture.*' -print -quit)"

# Then transfer an actual preserved ~33MiB Q6 ELF devcoredump, verify
# content-addressed naming and byte-for-byte identity.
export WAVE7_TEST_MODE=full
timeout 4 "$watcher" --run > "$tmp/full.log" 2>&1 || test "$?" -eq 124
rg 'CAPTURED devcd0' "$tmp/full.log"
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.elf' | wc -l) == 1 ]]
hash=$(sha256sum "$fixture" | cut -d' ' -f1)
cmp "$fixture" "$tmp/captures/$hash.elf"
rg 'MOCK_ROUTER_CONTEXT' "$tmp/captures/$hash.context.txt"

# A monitor restart must recognize identical core bytes, not create more.
timeout 3 "$watcher" --run > "$tmp/restart.log" 2>&1 || test "$?" -eq 124
rg 'ALREADY_CAPTURED devcd0' "$tmp/restart.log"
[[ $(find "$tmp/captures" -maxdepth 1 -name '*.elf' | wc -l) == 1 ]]
test -z "$(find "$tmp/captures" -maxdepth 1 -name '.capture.*' -print -quit)"
echo 'ARCHIVED_Q6_CORE_TRUNCATION_REJECTION_DEDUP_METADATA_PASS'
