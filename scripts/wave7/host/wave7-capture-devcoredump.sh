#!/usr/bin/env bash
# Read existing devcoredump data from the attached Wave 7; never flash or reconfigure it.
set -euo pipefail
umask 077
tag=${1:?Usage: capture-wave7-devcoredump.sh LABEL}
[[ "$tag" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,70}$ ]] || { echo "invalid label" >&2; exit 2; }
host=${WAVE7_SSH_HOST:-root@192.168.76.1}
key=${WAVE7_SSH_KEY:-/home/jan/.ssh/wave7-root-rsa}
outbase=${WAVE7_CAPTURE_DIR:-/home/jan/projects/acer-wave7-firmware/device-logs/$(date +%F)}
mkdir -p -- "$outbase"
ssh_args=(-T -i "$key" -o BatchMode=yes -o IdentitiesOnly=yes
          -o ConnectTimeout=4 -o ConnectionAttempts=1
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
stamp=$(date +%Y%m%dT%H%M%S%z)
prefix="$outbase/$tag-$stamp"
ssh "${ssh_args[@]}" "$host" 'uname -a; cat /etc/openwrt_release 2>/dev/null || true' > "$prefix-system.txt"
ssh "${ssh_args[@]}" "$host" 'dmesg' > "$prefix-dmesg.txt"
paths=$(ssh "${ssh_args[@]}" "$host" \
  'for d in /sys/class/devcoredump/devcd*/data; do [ -r "$d" ] && printf "%s\n" "$d"; done; true')
if [[ -z "$paths" ]]; then
  echo "No readable devcoredump entries; dmesg preserved under $prefix"
  exit 0
fi
count=0
while IFS= read -r path; do
  [[ "$path" =~ ^/sys/class/devcoredump/devcd[0-9]+/data$ ]] || {
    echo "unexpected devcoredump path $path" >&2
    exit 1
  }
  name=${path%/data}; name=${name##*/}
  dest="$prefix-$name.elf"
  [[ ! -e "$dest" ]] || { echo "refusing to overwrite $dest" >&2; exit 1; }
  tmp=$(mktemp "$dest.partial.XXXXXXXX")
  if ! ssh "${ssh_args[@]}" "$host" "cat '$path'" > "$tmp"; then
    rm -f -- "$tmp"
    echo "capture failed: $name" >&2
    exit 1
  fi
  if [[ ! -s "$tmp" ]]; then
    rm -f -- "$tmp"
    echo "empty dump: $name" >&2
    exit 1
  fi
  mv -- "$tmp" "$dest"
  sha256sum -- "$dest" | tee -a "$prefix-dump-sha256.txt"
  if command -v readelf >/dev/null; then
    readelf -h "$dest" | sed -n '1,22p' || true
  fi
  count=$((count + 1))
done <<< "$paths"
echo "Captured $count dump(s); dmesg and metadata: $prefix"
