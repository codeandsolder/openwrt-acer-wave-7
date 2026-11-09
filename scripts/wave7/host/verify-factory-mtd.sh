#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --raw PROC_MTD | --capture WATCHER_CAPTURE" >&2
  exit 2
}

[[ $# -eq 2 ]] || usage
case "$1" in
  --raw) capture=0 ;;
  --capture) capture=1 ;;
  *) usage ;;
esac

source_file=$2
[[ -f "$source_file" ]] || usage
dir=$(cd -- "$(dirname -- "$0")" && pwd)
fixture="$dir/factory-mtd.tsv"
[[ -s "$fixture" ]] || { echo "Missing factory MTD fixture" >&2; exit 2; }

awk -v fixture="$fixture" -v capture="$capture" '
BEGIN {
    FS="[[:space:]]+"
    while ((getline line < fixture) > 0) {
        count=split(line, f, "\t")
        if (count != 3 || f[1] in expected_size) {
            print "Invalid factory fixture row: " line > "/dev/stderr"
            exit 2
        }
        expected_size[f[1]]=f[2]
        expected_erase[f[1]]=f[3]
        expected_count++
    }
    close(fixture)
    if (expected_count != 27) {
        print "Expected 27 physical factory MTD rows; found " expected_count > "/dev/stderr"
        exit 2
    }
    inside=!capture
}
capture && $0 == "===NAND_MTD===" { inside=1; section_found=1; next }
capture && inside && /^===/ { inside=0 }
inside && $1 ~ /^mtd[0-9]+:$/ {
    name=tolower($4)
    gsub(/^"|"$/, "", name)
    if (!(name in expected_size)) next

    if (seen[name]++) {
        print "Duplicate factory MTD partition: " name > "/dev/stderr"
        failed=1
        next
    }
    size=tolower($2)
    erase=tolower($3)
    if (size != expected_size[name] || erase != expected_erase[name]) {
        printf "MTD geometry mismatch for %s: got %s/%s, expected %s/%s\n", name, size, erase, expected_size[name], expected_erase[name] > "/dev/stderr"
        failed=1
    }
    matched++
}
END {
    if (capture && !section_found) {
        print "MTD section missing in watcher capture" > "/dev/stderr"
        failed=1
    }
    for (name in expected_size) {
        if (!seen[name]) {
            print "Missing factory MTD partition: " name > "/dev/stderr"
            failed=1
        }
    }
    if (failed) exit 1
    printf "Factory NAND MTD inventory matches %d recorded physical partitions\n", matched
}
' "$source_file"
