#!/usr/bin/env bash
# Replay the known isolated lab DHCPv4/v6 and RS solicitations only.
# Requires the existing lab service and the direct peer's pinned topology.
set -Eeuo pipefail
umask 077
[[ $(id -u) == 0 && $# == 1 ]] || { echo 'usage (root): wire-policy.sh NEW_OUTPUT_DIR' >&2; exit 2; }
base=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8
upstream=/home/jan/scripts/wave7/secondary-ap-guard8/lab-upstream.sh
unit=wave7-lab-upstream-guard8.service
direct=enp4s0f4u2u4
switch=enp4s0f4u2u2u4
pcap="$base/client-wire/solicit-direct.pcap"
digest=f3808227e5f88faa33903aed4709229943464acd894d52d5cd4aeeb2813fb7f0
out=$(realpath -m "$1")
[[ $out == "$base"/trunk-health-dhcp-guard8/wire-policy-* && ! -e $out ]] || exit 2
[[ $(sha256sum "$pcap" | cut -d' ' -f1) == "$digest" ]] || exit 2
[[ $(cat /sys/class/net/$direct/address) == 00:e0:4c:68:00:6d ]]
[[ $(cat /sys/class/net/$switch/address) == 00:e0:4c:68:01:45 ]]
ip -6 -o addr show dev "$direct" scope link | rg -Fq 'fe80::9ca3:a7e5:c496:a37b/64'
for dev in "$direct" "$switch"; do
  [[ $(cat /sys/class/net/"$dev"/carrier) == 1 && ! -e /sys/class/net/"$dev"/master ]]
  ! ip -4 route show default | rg -q "dev $dev( |$)"
  ! ip -6 route show default | rg -q "dev $dev( |$)"
done
"$upstream" --check
systemctl is-active --quiet "$unit"
# At least 45s of current management lease remains, even if the test fails.
awk -v now="$(date +%s)" '$1>now+45 && $2=="70:5a:6f:5a:bb:14" && $3=="192.168.76.1"{ok=1} END{exit !ok}' "$base/upstream/dnsmasq.leases"
install -d -m 0700 -o jan -g jan "$out"
stopped=0
pids=()
cleanup() {
  local rc=$?
  trap - EXIT
  for pid in "${pids[@]}"; do kill -INT "$pid" 2>/dev/null || :; wait "$pid" 2>/dev/null || :; done
  if (( stopped )); then
    "$upstream" --start || rc=1
    systemctl is-active --quiet "$unit" || rc=1
  fi
  chown jan:jan "$out"/*
  exit "$rc"
}
trap cleanup EXIT
# Stop only our dedicated service; capture the same solicitation traffic
# independently on each physical port, not an aggregate Linux bridge.
"$upstream" --stop
stopped=1
filter='(udp and (port 67 or port 68 or port 546 or port 547)) or (icmp6 and (ip6[40]==133 or ip6[40]==134))'
for name in direct switch; do
  dev=${!name}
  tcpdump -Z jan -n -i "$dev" -U -s 384 -w "$out/$name.pcap" "$filter" 2>"$out/$name.log" &
  pids+=("$!")
done
for _ in {1..20}; do
  if rg -q 'listening on' "$out/direct.log" && rg -q 'listening on' "$out/switch.log"; then break; fi
  sleep .1
done
rg -q 'listening on' "$out/direct.log"
rg -q 'listening on' "$out/switch.log"
# The immutable replay was captured from this exact direct NIC. Check
# packet lengths, Ethernet source/destination and protocol before send.
 /usr/bin/uv run --no-project --offline --python /usr/bin/python3 python - "$pcap" "$direct" <<'PY'
import socket, struct, sys, time
from pathlib import Path
data=Path(sys.argv[1]).read_bytes()
assert data[:4]==bytes.fromhex("d4c3b2a1")
assert struct.unpack_from("<I", data, 20)[0]==1
source=bytes.fromhex("00e04c68006d")
frames=[]
pos=24
while pos<len(data):
    _,_,captured,original=struct.unpack_from("<IIII",data,pos)
    pos+=16
    assert captured==original and pos+captured<=len(data)
    frame=data[pos:pos+captured]
    pos+=captured
    assert frame[6:12]==source
    eth=frame[12:14]
    if eth==b"\x08\x00":
        assert frame[:6]==b"\xff"*6 and frame[23]==17
        assert struct.unpack_from("!HH",frame,34)==(68,67)
        assert frame[42]==1 and b"\x35\x01\x01" in frame[278:]
        kind="discover"
    else:
        assert eth==b"\x86\xdd"
        if frame[20]==58:
            assert frame[:6]==bytes.fromhex("333300000002") and frame[54]==133
            kind="rs"
        else:
            assert frame[20]==17 and frame[:6]==bytes.fromhex("333300010002")
            assert struct.unpack_from("!HH",frame,54)==(546,547) and frame[62]==1
            kind="solicit"
    frames.append((kind,frame))
assert [kind for kind,_ in frames]==["discover","rs","solicit"]*3
with socket.socket(socket.AF_PACKET,socket.SOCK_RAW) as sock:
    sock.bind((sys.argv[2],0))
    for i,(_,frame) in enumerate(frames):
        if i and i%3==0: time.sleep(2)
        assert sock.send(frame)==len(frame)
print("SENT_NINE_SOLICITATIONS")
PY
sleep 5
for pid in "${pids[@]}"; do kill -INT "$pid"; wait "$pid"; done
pids=()
for name in direct switch; do
  tcpdump -nn -e -vvv -r "$out/$name.pcap" >"$out/$name.txt" 2>/dev/null
  # Only exact solicits are counted; unrelated DHCP client retries are
  # allowed. Every server-originated DHCP/RA packet fails the test.
  [[ $(rg -c 'xid 0x7a017a01' "$out/$name.txt") == 3 ]]
  [[ $(rg -c 'router solicitation.*length 16' "$out/$name.txt") == 3 ]]
  [[ $(rg -c 'dhcp6 solicit.*xid=7a017a' "$out/$name.txt") == 3 ]]
  [[ -z $(tcpdump -nn -r "$out/$name.pcap" 'udp src port 67 or udp src port 547 or (icmp6 and ip6[40]==134)' 2>/dev/null) ]]
done
(cd "$out"; sha256sum direct.pcap switch.pcap direct.txt switch.txt > SHA256SUMS; sha256sum -c SHA256SUMS)
echo AP_WIRE_POLICY_PASS
