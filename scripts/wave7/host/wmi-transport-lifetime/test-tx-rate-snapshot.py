#!/usr/bin/env python3
"""Differentially exercise the actual old and new WBM rate paths."""
import argparse
from pathlib import Path
import re
import subprocess


def one(text, pattern):
    matches = re.findall(pattern, text, re.M | re.S)
    if len(matches) != 1:
        raise ValueError(f'expected one match for {pattern}, got {len(matches)}')
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('parent', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    old = (args.parent / 'wifi7/dp_tx.c').read_text()
    new = (args.candidate / 'wifi7/dp_tx.c').read_text()
    old_fun = one(old, r'^static void ath12k_wifi7_dp_tx_update_txcompl\(.*?^\}')
    decode = one(new, r'^static bool ath12k_wifi7_dp_tx_decode_rate\(.*?^\}')
    snapshot = one(new, r'^static struct ieee80211_sta \*\nath12k_wifi7_dp_tx_peer_snapshot\(.*?^\}')
    complete = one(new, r'^static void ath12k_wifi7_dp_tx_complete_msdu\(.*?^\}')
    assert complete.count('ath12k_wifi7_dp_tx_peer_snapshot(') == 1
    assert 'ath12k_dp_link_peer_find_by_peerid(' not in complete
    assert 'spin_lock_bh(&dp->dp_lock)' not in complete
    assert complete.index('ath12k_wifi7_dp_tx_peer_snapshot(') < complete.index('ieee80211_tx_status_ext(')
    assert snapshot.count('spin_lock_bh(') == snapshot.count('spin_unlock_bh(') == 1
    assert snapshot.index('spin_unlock_bh(') < snapshot.index('ath12k_warn(')
    defines = '\n'.join(re.findall(r'^#define ATH12K_(?:HT|VHT|HE|EHT)_MCS_MAX\s+\d+$',
                                  (args.candidate / 'core.h').read_text(), re.M))
    assert len(defines.splitlines()) == 4
    pkt_type = one((args.candidate / 'hal.h').read_text(), r'^enum hal_tx_rate_stats_pkt_type \{.*?^\};')
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define RATE_INFO_FLAGS_MCS 1
#define RATE_INFO_FLAGS_VHT_MCS 2
#define RATE_INFO_FLAGS_HE_MCS 4
#define RATE_INFO_FLAGS_EHT_MCS 8
#define RATE_INFO_FLAGS_SHORT_GI 16
#define RATE_INFO_BW_HE_RU 20
#define RATE_INFO_BW_EHT_RU 21
#define HAL_TX_STATUS_FLAGS_RATE_STATS_VALID 1
struct rate_info {u16 legacy; u8 mcs,nss,flags,bw,he_gi,eht_gi,he_ru_alloc,eht_ru_alloc;};
struct ath12k_link_sta {unsigned peer_nss;};
struct ath12k_sta {struct ath12k_link_sta *link[4];};
struct ieee80211_sta {struct ath12k_sta priv;};
struct ath12k_dp_link_peer {struct ieee80211_sta *sta; u8 link_id; struct rate_info txrate,last_txrate;};
struct ath12k_dp {void *ab; unsigned dp_lock;};
struct ath12k_pdev_dp {struct ath12k_dp *dp; struct ath12k_dp_link_peer *peer;};
''' + defines + '\n' + pkt_type + r'''
struct hal_tx_status {unsigned flags,peer_id,pkt_type,mcs,sgi,bw,tones,ofdma;};
static unsigned locks,unlocks,lookups,warnings,conversion_calls;
#define rcu_dereference(x) (x)
#define ath12k_sta_to_ahsta(s) (&(s)->priv)
#define ath12k_dbg(...) ((void)0)
#define ATH12K_DBG_DP_TX 0
#define ath12k_warn(...) (++warnings)
static void spin_lock_bh(unsigned *p){assert(!*p);*p=1;++locks;}
static void spin_unlock_bh(unsigned *p){assert(*p);*p=0;++unlocks;}
static struct ath12k_dp_link_peer *ath12k_dp_link_peer_find_by_peerid(struct ath12k_pdev_dp *dp,unsigned id){assert(id==17);++lookups;return dp->peer;}
/* Conversion stubs intentionally distinguish all arguments. The real
 * conversion implementations are unchanged by this patch. */
static int ath12k_mac_hw_ratecode_to_legacy_rate(u8 mcs,u8 preamble,u8 *index,u16 *rate){++conversion_calls;if(mcs>=12)return -1;*index=mcs;*rate=10+10*mcs+preamble;return 0;}
static u8 ath12k_he_gi_to_nl80211_he_gi(unsigned v){++conversion_calls;return v^3;}
static u8 ath12k_mac_eht_gi_to_nl80211_eht_gi(unsigned v){++conversion_calls;return v^2;}
static u8 ath12k_mac_bw_to_mac80211_bw(unsigned v){++conversion_calls;return v^1;}
static u16 ath12k_mac_he_convert_tones_to_ru_tones(unsigned v){++conversion_calls;return v^7;}
static u8 ath12k_he_ru_tones_to_nl80211_he_ru_alloc(unsigned v){++conversion_calls;return v^11;}
static u8 ath12k_mac_eht_ru_tones_to_nl80211_eht_ru_alloc(unsigned v){++conversion_calls;return v^17;}
''' + old_fun + '\n' + decode + '\n' + snapshot + r'''
int main(void){
    struct ath12k_dp dp={0};
    struct ath12k_link_sta arsta={.peer_nss=3};
    struct ieee80211_sta sta={.priv={.link={NULL,&arsta,NULL,NULL}}};
    struct rate_info initial={.legacy=77,.mcs=12,.nss=3,.flags=99,.bw=4};
    unsigned long cases=0;
    for(unsigned type=0;type<9;type++)
    for(unsigned mcs=0;mcs<32;mcs++)
    for(unsigned sgi=0;sgi<4;sgi++)
    for(unsigned bw=0;bw<5;bw++)
    for(unsigned ofdma=0;ofdma<2;ofdma++)
    for(unsigned tones=0;tones<3;tones++)
    for(unsigned nss=0;nss<4;nss++)
    for(unsigned link=0;link<5;link++)
    for(unsigned mode=0;mode<4;mode++){
        struct hal_tx_status ts={.flags=(mode!=0),.peer_id=17,.pkt_type=type,.mcs=mcs,.sgi=sgi,.bw=bw,.tones=tones*242,.ofdma=ofdma};
        struct ath12k_dp_link_peer a={.sta=mode==2?NULL:&sta,.link_id=link,.txrate=initial,.last_txrate={.nss=nss,.legacy=123,.flags=4}},b=a;
        struct ath12k_pdev_dp p={.dp=&dp,.peer=mode==3?NULL:&a};
        warnings=conversion_calls=0;
        if(ts.flags)ath12k_wifi7_dp_tx_update_txcompl(&p,&ts);
        unsigned oldwarn=warnings,oldconv=conversion_calls;
        struct rate_info out={0};
        p.peer=mode==3?NULL:&b;
        locks=unlocks=lookups=warnings=conversion_calls=0;
        struct ieee80211_sta *got=ath12k_wifi7_dp_tx_peer_snapshot(&p,&ts,&out);
        assert(locks==1&&unlocks==1&&lookups==1&&!dp.dp_lock);
        assert(got==(mode>=2?NULL:&sta));
        assert(!memcmp(&a.txrate,&b.txrate,sizeof(a.txrate)));
        assert(!memcmp(&a.last_txrate,&b.last_txrate,sizeof(a.last_txrate)));
        assert(warnings==oldwarn&&conversion_calls==oldconv);
        if(got)assert(!memcmp(&out,&a.last_txrate,sizeof(out)));
        ++cases;
    }
    printf("TX_RATE_SNAPSHOT_PASS cases=%lu\\n",cases);
}
'''
    c = args.output / 'tx-rate.c'
    obj = args.output / 'tx-rate.o'
    exe = args.output / 'tx-rate'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
