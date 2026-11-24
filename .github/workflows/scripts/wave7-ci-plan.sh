#!/usr/bin/env bash
# Choose the real board and validation scope from the exact checked-out tree.
set -euo pipefail
if (( $# != 5 )); then
    echo "usage: $0 SOURCE EVENT MODE BEFORE OUTPUT" >&2
    exit 2
fi
source=$1
event=$2
mode=$3
before=$4
output=$5
cd "$source"
sha=$(git rev-parse HEAD)
printf 'sha=%s\n' "$sha" >> "$output"

if ! git cat-file -e HEAD:target/linux/qualcommbe/ipq53xx/target.mk 2>/dev/null; then
    if [[ "$event" == workflow_dispatch ]]; then
        echo "The requested source has no qualcommbe/ipq53xx target" >&2
        exit 1
    fi
    echo "No Wave 7 target in this source revision; skipping board build rather than selecting ipq95xx."
    printf 'mode=none\npackages=\n' >> "$output"
    exit 0
fi

if [[ "$event" == workflow_dispatch ]]; then
    case "$mode" in
        kernel|prebuild) packages= ;;
        packages) packages=all ;;
        *) echo "Invalid Wave 7 mode: $mode" >&2; exit 2 ;;
    esac
else
    mode=kernel
    packages=
    if [[ "$event" == pull_request ]]; then
        before=$(git rev-parse HEAD^1)
    fi
    if [[ ! "$before" =~ ^[0-9a-f]{40}$ || "$before" =~ ^0+$ ]] ||
        { ! git cat-file -e "$before^{commit}" 2>/dev/null &&
          ! git fetch --no-tags --depth=1 origin "$before"; }; then
        # Missing history is not permission to skip validation.
        mode=packages
        packages=all
    else
        changed=$(mktemp)
        trap 'rm -f "$changed"' EXIT
        git diff --no-renames --name-only -z "$before" HEAD > "$changed"
        while IFS= read -r -d '' file; do
            case "$file" in
                config/*|include/*|tools/*|toolchain/*|scripts/*|Makefile|rules.mk|Config.in|feeds.conf.default|target/Makefile|target/toolchain/*|package/Makefile)
                    mode=packages
                    packages=all
                    ;;
                package/*)
                    mode=packages
                    if [[ "$packages" == all ]]; then continue; fi
                    dir=${file%/*}
                    name=
                    while [[ "$dir" == package/* ]]; do
                        if [[ "$dir" != */src && "$dir" != */src/* ]] &&
                            git cat-file -e "HEAD:$dir/Makefile" 2>/dev/null; then
                            name=${dir##*/}
                            break
                        fi
                        dir=${dir%/*}
                    done
                    if [[ "$name" =~ ^[A-Za-z0-9_.+-]+$ ]]; then
                        packages+="$name "
                    else
                        packages=all
                    fi
                    ;;
            esac
        done < "$changed"
        if [[ "$mode" == packages && "$event" == push ]]; then packages=all; fi
        if [[ "$packages" != all && -n "$packages" ]]; then
            read -r -a names <<< "$packages"
            packages=$(printf '%s\n' "${names[@]}" | sort -u | paste -sd ' ' -)
        fi
    fi
fi
printf 'mode=%s\npackages=%s\n' "$mode" "$packages" >> "$output"
echo "Wave 7 mode: $mode; package checks: ${packages:-none}"
