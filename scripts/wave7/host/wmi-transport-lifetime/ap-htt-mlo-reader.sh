# Sourced as a POSIX function by the lab edge observer.
capture_htt_mlo(){
    for d in /sys/kernel/debug/ath12k/ahb-c000000.wifi /sys/kernel/debug/ath12k/ahb-soc@0:wifi; do
        found=0
        for f in "$d"/mac*/htt_stats; do
            [ -r "$f" ] || return 1
            found=1
            dir=${f%/*}
            id=${dir#/sys/kernel/debug/ath12k/}
            selector="$dir/htt_stats_type"
            [ "$(cat "$selector")" = 1 ] || return 1
            for kind in 63 64; do
                for p in 0 1 2; do
                    [ "$(cat /sys/class/remoteproc/remoteproc$p/state)" = running ] || return 1
                done
                [ "$(dmesg | grep -c 'NOC ERROR DETECTED' || :)" = 0 ] || return 1
                read -r start rest </proc/uptime || return 1
                echo "HTT_MLO_BEGIN $id $kind $start"
                rc=0
                echo "$kind" > "$selector" || rc=$?
                if [ "$rc" = 0 ] && [ "$(cat "$selector")" != "$kind" ]; then rc=2; fi
                if [ "$rc" = 0 ]; then cat "$f" 2>&1 || rc=$?; fi
                read -r end rest </proc/uptime || return 1
                echo "HTT_MLO_END $id $kind $end rc=$rc"
                # Restore only the host selector, never request reset or
                # another firmware response following an ambiguous reply.
                echo 1 > "$selector" || return 1
                [ "$(cat "$selector")" = 1 ] || return 1
                [ "$rc" = 0 ] || return 1
                awk -v a="$start" -v b="$end" 'BEGIN {exit !(b >= a && b-a < 2.9)}' || return 1
            done
        done
        [ "$found" = 1 ] || return 1
    done
    for p in 0 1 2; do
        [ "$(cat /sys/class/remoteproc/remoteproc$p/state)" = running ] || return 1
    done
    [ "$(dmesg | grep -c 'NOC ERROR DETECTED' || :)" = 0 ]
}
