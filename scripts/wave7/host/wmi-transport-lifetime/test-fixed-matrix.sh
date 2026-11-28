#!/usr/bin/env bash
set -Eeuo pipefail
h=$(dirname "$(realpath "$0")")
source <(sed -n '/^parent_profile_eligible(){/,/^}/p' "$h/run-fixed-primary-matrix.sh")
d=$(mktemp -d)
trap 'rm -rf -- "$d"' EXIT
mkdir "$d/matrix" "$d/case"
printf 'exit=0\n' > "$d/case/status"
printf 'QUALIFIED single-5 fixture\nSTANDALONE dual-5 fixture\nUNQUALIFIED dual-24 fixture\nINCOMPLETE dual-5 dual-24 fixture\n' > "$d/matrix/wrapper.log"
for mode in --compare --compare-partial; do
    parent_profile_eligible "$d/matrix" single-5 "$d/case"
    if [[ $mode == --compare-partial ]]; then
        parent_profile_eligible "$d/matrix" dual-5 "$d/case"
    else
        if parent_profile_eligible "$d/matrix" dual-5 "$d/case"; then exit 1; fi
    fi
    if parent_profile_eligible "$d/matrix" dual-24 "$d/case"; then exit 1; fi
done
printf 'exit=1\n' > "$d/case/status"
for mode in --compare --compare-partial; do
    if parent_profile_eligible "$d/matrix" single-5 "$d/case"; then exit 1; fi
done
echo FIXED_MATRIX_ELIGIBILITY_PASS
