#!/usr/bin/env bash
# Exercise the actual image's firstboot odhcpd migration with its own UCI.
# No router mutation, root privileges, or host /etc/config writes.
set -euo pipefail
if [[ $# != 3 ]]; then
    echo "usage: $0 UNSQUASHFS NATIVE_SYSUPGRADE WORK_PARENT" >&2
    exit 2
fi
unsq=$(realpath "$1")
image=$(realpath "$2")
parent=$(realpath "$3")
work=$(mktemp -d "$parent/dhcp-migration-XXXXXX")
trap 'rm -rf "$work"' EXIT
cd "$work"
tar xOf "$image" sysupgrade-acer_wave7/root > root.sq
"$unsq" -no-progress -d root root.sq lib sbin/uci etc/config/dhcp etc/uci-defaults/15_odhcpd >/dev/null
# jshn is only used by the other branch, which migrates historical PIO
# files or creates a DHCP server from scratch. Neither branch is valid
# for the pre-staged AP policy exercised here.
sed '/^\. \/usr\/share\/libubox\/jshn.sh$/d' root/etc/uci-defaults/15_odhcpd > migration.sh
mkdir old new old-save new-save overrides
sed '/option piodir /d; /option hostsdir /d' root/etc/config/dhcp > old/dhcp
cp root/etc/config/dhcp new/dhcp
cp old/dhcp old.before
cp new/dhcp new.before
for config in old new; do
    sh -c '
        conf=$1
        uci() {
            qemu-aarch64 -L "$PWD/root" "$PWD/root/sbin/uci" \
                -c "$PWD/$conf" -C "$PWD/overrides" -t "$PWD/$conf-save" "$@"
        }
        run_migration() { . ./migration.sh; }
        run_migration
    ' sh "$config"
done
if cmp -s old.before old/dhcp; then
    echo "negative control did not exercise the migration" >&2
    exit 1
fi
cmp new.before new/dhcp
diff -u old.before old/dhcp || test "$?" = 1
echo EXACT_TARGET_UCI_MIGRATION_PASS
