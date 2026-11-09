#!/usr/bin/env bash
set -euo pipefail

# Asus-side read-only comparison of live Wave 7 ART with the private
# Oct 28 factory NAND backup, using the existing router SSH key.
usage() {
    echo "Usage: $0 ART_FACTORY_BACKUP.bin EXPECT_REVISION_SHA10" >&2
    exit 2
}

[[ $# == 2 && $2 =~ ^[0-9a-f]{10}$ ]] || usage
backup=$1
expect_rev=$2
[[ -f $backup && $(stat -c %s -- "$backup") == 2097152 ]] || {
    echo "Expected a 2097152-byte physical ART NAND backup" >&2
    exit 2
}

script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
[[ -x $script_dir/verify-factory-mtd.sh && -s $script_dir/factory-mtd.tsv ]] || {
    echo "Missing factory MTD inventory validator or fixture" >&2
    exit 2
}

remote() {
    local cmd=$1
    ssh -n -o BatchMode=yes -o ConnectTimeout=5 -o IdentitiesOnly=yes         -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null         -i /home/jan/.ssh/wave7-root-rsa root@192.168.76.1 "$cmd"
}

kernel=$(remote 'uname -r')
[[ $kernel == 6.18.60 ]] || {
    echo "Refusing: kernel is $kernel, expected 6.18.60" >&2
    exit 3
}
release=$(remote 'cat /etc/openwrt_release')
[[ $release == *"$expect_rev"* ]] || {
    echo "Refusing: router is not expected revision $expect_rev" >&2
    exit 3
}
ecc=$(remote 'cat /sys/class/mtd/mtd18/ecc_strength')
[[ $ecc == 8 ]] || {
    echo "Refusing: mtd18 ECC strength is $ecc (BCH-8 required)" >&2
    exit 3
}
name=$(remote 'cat /sys/class/mtd/mtd18/name')
[[ $name == '0:art' ]] || {
    echo "Refusing: mtd18 name is $name, expected 0:art" >&2
    exit 3
}

workdir=$(mktemp -d "${TMPDIR:-/tmp}/wave7-art-ecc-XXXXXXXX")
trap 'rm -rf -- "$workdir"' EXIT
remote 'cat /proc/mtd' > "$workdir/proc-mtd.txt"
"$script_dir/verify-factory-mtd.sh" --raw "$workdir/proc-mtd.txt"

before=$(remote 'cat /sys/class/mtd/mtd18/ecc_failures')
corrected_before=$(remote 'cat /sys/class/mtd/mtd18/corrected_bits')
echo "ART_VERIFY_START kernel=$kernel revision=$expect_rev ecc_strength=$ecc failures=$before corrected=$corrected_before"

failed=0
for page in 2 3 4 16; do
    dd if="$backup" of="$workdir/expected" bs=2048 skip="$page" count=1 iflag=fullblock status=none
    remote "dd if=/dev/mtd18 bs=2048 skip=$page count=1 iflag=fullblock 2>/dev/null" > "$workdir/actual"
    bytes=$(stat -c %s "$workdir/actual")
    if [[ $bytes != 2048 ]]; then
        echo "ART_PAGE=$page READ_FAILED bytes=$bytes"
        failed=1
    elif cmp -s "$workdir/expected" "$workdir/actual"; then
        echo "ART_PAGE=$page MATCH"
    else
        echo "ART_PAGE=$page MISMATCH"
        failed=1
    fi
done

after=$(remote 'cat /sys/class/mtd/mtd18/ecc_failures')
corrected_after=$(remote 'cat /sys/class/mtd/mtd18/corrected_bits')
echo "ART_VERIFY_END failures_before=$before failures_after=$after corrected_before=$corrected_before corrected_after=$corrected_after"
if [[ $after != "$before" ]]; then
    echo "ART ECC failures increased during read-only verification" >&2
    failed=1
fi
if [[ $failed == 0 ]]; then
    echo 'ART_BCH8_FACTORY_MATCH=1'
else
    echo 'ART_BCH8_FACTORY_MATCH=0'
fi
exit "$failed"
