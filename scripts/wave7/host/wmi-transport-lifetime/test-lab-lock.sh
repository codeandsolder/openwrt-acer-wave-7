#!/usr/bin/env bash
# Check the actual runner's locking behavior without touching the lab.
set -Eeuo pipefail
cd "$(dirname "$(realpath "$0")")"
lab=$(mktemp -d)
trap 'rm -rf "$lab"' EXIT
fail(){ exit 17; }
# shellcheck disable=SC1090
source <(sed -n '/^acquire_lab_lock(){/,/^}/p' test-primary-client.sh)
touch "$lab/.lab-control.lock" "$lab/other"
# A wrapper can stage and execute with one held open file description.
(
    exec 8<>"$lab/.lab-control.lock"
    flock -n 8
    (
        acquire_lab_lock
        [[ /proc/self/fd/8 -ef "$lab/.lab-control.lock" ]]
    )
    # Independently opened fd 8 must not bypass the held lock.
    if (exec 8<>"$lab/other"; acquire_lab_lock); then
        echo 'independent opener unexpectedly acquired lock' >&2
        exit 1
    else
        [[ $? == 17 ]]
    fi
)
# Ordinary invocation works without inherited lock or fd.
(
    exec 8>&-
    acquire_lab_lock
    [[ /proc/self/fd/8 -ef "$lab/.lab-control.lock" ]]
)
echo LAB_LOCK_SELFTEST_PASS
