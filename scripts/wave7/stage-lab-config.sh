#!/bin/sh
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
source_dir=${WAVE7_LAB_CONFIG_SOURCE:-$HOME/firmware/wave7/configs/working-61855-a668b62dec}
target_dir="$repo/files/etc/config"

for name in network wireless; do
    [ -s "$source_dir/$name" ] || {
        echo "Missing private Wave 7 lab config: $source_dir/$name" >&2
        exit 1
    }
done

# Keep exact known-working LAN/MLO semantics; don't publish lab secrets.
grep -Fq "192.168.76.1/24" "$source_dir/network"
grep -Fq "option mlo '1'" "$source_dir/wireless"
grep -Fq "option device 'radio0 radio1'" "$source_dir/wireless"
grep -Fq "option encryption 'sae'" "$source_dir/wireless"
grep -Fq "option ieee80211w '2'" "$source_dir/wireless"
grep -Fq "option ssid 'Wave7-MLO-Lab'" "$source_dir/wireless"
grep -Eq "^[[:space:]]*option key " "$source_dir/wireless"

# The private overlay must not make /etc itself inaccessible to
# non-root daemons (ubusd, netifd, etc.). Keep file permissions separate.
# Explicitly restore modes even if these directories already exist.
install -d -m 0755 "$repo/files/etc" "$target_dir"
for name in network wireless; do
    cp "$source_dir/$name" "$target_dir/$name.tmp"
    chmod 0600 "$target_dir/$name.tmp"
    mv -f "$target_dir/$name.tmp" "$target_dir/$name"
    cmp -s "$source_dir/$name" "$target_dir/$name"
done
echo "Staged the private Wave 7 LAN + two-link WPA3-MLO lab config"
