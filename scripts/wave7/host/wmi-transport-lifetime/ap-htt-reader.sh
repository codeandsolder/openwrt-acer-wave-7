# Sourced by the edge observer. Never request stats during a load.
htt_healthy(){
    local p
    for p in 0 1 2; do
        [ "$(cat /sys/class/remoteproc/remoteproc$p/state)" = running ] || return 1
    done
    [ "$(dmesg | grep -c 'NOC ERROR DETECTED' || :)" = 0 ]
}

# One request at a time; a timeout may leave a late reply on the pdev cookie.
# Restore only the host selector after an error, then stop the entire capture.
capture_htt(){
    local profile="$1" kinds d f found dir id selector old kind rc start end rest
    case "$profile" in
        TX) kinds=1 ;;
        RATE) kinds=9 ;;
        MLO) kinds='63 64' ;;
        *) return 1 ;;
    esac
    for d in /sys/kernel/debug/ath12k/ahb-c000000.wifi /sys/kernel/debug/ath12k/ahb-soc@0:wifi; do
        found=0
        for f in "$d"/mac*/htt_stats; do
            [ -r "$f" ] || return 1
            found=1
            dir=${f%/*}
            id=${dir#/sys/kernel/debug/ath12k/}
            selector="$dir/htt_stats_type"
            for kind in $kinds; do
                htt_healthy || return 1
                old=$(cat "$selector") || return 1
                case "$profile:$old" in
                    TX:0|TX:1|RATE:1|MLO:1) ;;
                    *) return 1 ;;
                esac
                read -r start rest </proc/uptime || return 1
                case "$profile" in
                    TX) echo "HTT_BEGIN $id $start selector=$old" ;;
                    *) echo "HTT_${profile}_BEGIN $id $kind $start" ;;
                esac
                rc=0
                echo "$kind" > "$selector" || rc=$?
                if [ "$rc" = 0 ] && [ "$(cat "$selector")" != "$kind" ]; then rc=2; fi
                if [ "$rc" = 0 ]; then cat "$f" 2>&1 || rc=$?; fi
                read -r end rest </proc/uptime || return 1
                case "$profile" in
                    TX) echo "HTT_END $id $end rc=$rc" ;;
                    *) echo "HTT_${profile}_END $id $kind $end rc=$rc" ;;
                esac
                if [ "$kind" != 1 ]; then
                    echo 1 > "$selector" || return 1
                fi
                [ "$(cat "$selector")" = 1 ] || return 1
                [ "$rc" = 0 ] || return 1
                awk -v a="$start" -v b="$end" 'BEGIN {
                    if (a !~ /^[0-9]+[.][0-9][0-9]$/ || b !~ /^[0-9]+[.][0-9][0-9]$/) exit 1
                    split(a,x,"."); split(b,y,".")
                    d=(y[1]-x[1])*100+y[2]-x[2]
                    exit !(d >= 0 && d < 290)
                }' || return 1
                htt_healthy || return 1
            done
        done
        [ "$found" = 1 ] || return 1
    done
}

capture_htt_tx(){ capture_htt TX; }
capture_htt_rate(){ capture_htt RATE; }
capture_htt_mlo(){ capture_htt MLO; }
