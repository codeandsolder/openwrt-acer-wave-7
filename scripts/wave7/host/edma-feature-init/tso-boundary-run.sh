#!/usr/bin/env bash
# Execute only after the guarded candidate's terminal soak and archival.
# Disable receive aggregation to make the physical TCP segment witness literal.
set -Eeuo pipefail
[[ $(id -u) == 0 && $# == 3 ]] || { echo 'usage: tso-boundary-run.sh RUN_DIRECTORY PEER_BINARY ATTEMPT (root)' >&2; exit 2; }
script_dir=$(dirname "$(realpath "$0")")
run=$(realpath -e "$1"); binary=$(realpath -e "$2"); attempt=$3
[[ $attempt =~ ^[1-9][0-9]*$ ]]
[[ $run == /home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8/edma-tso-limits-dhcp-guard8/runs/* ]]
[[ $(cat "$run/status") == SOAK_PASS && -r $run/evidence.sha256 ]]
# Hold the same lock from before temporary link tuning until after cleanup.
# The unprivileged witness verifies the inherited descriptor and all boot pins.
lock=/home/jan/firmware/wave7/trials/20261120-secondary-ap-guard8/.lab-control.lock
[[ -f $lock && ! -L $lock && $(stat -c %U "$lock") == jan ]]
exec 8<>"$lock"
flock -n 8 || { echo 'lab control busy' >&2; exit 2; }
cd "$script_dir"
interfaces=(enp4s0f4u2u4 enp4s0f4u2u2u4)
changed=()
cleanup() {
    local failed=0
    for d in "${changed[@]}"; do
        ethtool -K "$d" gro on && ethtool -k "$d" | rg -x 'generic-receive-offload: on' || failed=1
    done
    return "$failed"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
for d in "${interfaces[@]}"; do
    ethtool -k "$d" | rg -x 'generic-receive-offload: on'
    changed+=("$d")
    ethtool -K "$d" gro off
done
runuser -u jan -- /usr/bin/uv run --no-project python -B "$script_dir/tso-boundary-witness.py" "$run" "$binary" --attempt "$attempt" --lock-fd 8
