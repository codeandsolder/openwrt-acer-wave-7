#!/usr/bin/env bash
set -u
tag=$1
old=$2
rev=$3
log=/tmp/wave7-$tag-bootid-gate.log
key=/home/jan/.ssh/wave7-root-rsa
printf '%s gate-start old=%s expected=%s\n' "$(date -Is)" "$old" "$rev" > "$log"
for _ in $(seq 1 600); do
  state=$(ssh -n -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=2     -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@192.168.76.1     'uname -r; cat /proc/sys/kernel/random/boot_id; sed -n "s/^DISTRIB_REVISION=//p" /etc/openwrt_release' 2>/dev/null || true)
  kernel=$(printf '%s\n' "$state" | sed -n '1p')
  boot=$(printf '%s\n' "$state" | sed -n '2p')
  seen=$(printf '%s\n' "$state" | sed -n '3p')
  if [[ $kernel == 5.4.213 ]]; then
    printf '%s VENDOR_FALLBACK\n' "$(date -Is)" >> "$log"
    exit 3
  fi
  if [[ $kernel == 6.18.60 && $boot != "$old" && $boot =~ ^[0-9a-f-]{36}$ && $seen == *"$rev"* ]]; then
    printf '%s NEW_TARGET_BOOT=%s %s\n' "$(date -Is)" "$boot" "$seen" >> "$log"
    exit 0
  fi
  sleep 2
done
printf '%s NO_NEW_TARGET_BOOT\n' "$(date -Is)" >> "$log"
exit 4
