#!/usr/bin/env python3
"""Exercise actual deferred WMM storage and replay, with mocked firmware transport."""
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
    parser.add_argument('source', type=Path)
    parser.add_argument('tree', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    mac = (args.source / 'mac.c').read_text()
    core = (args.source / 'core.h').read_text()
    wmi = (args.tree / 'drivers/net/wireless/ath/ath12k/wmi.h').read_text()
    ieee = (args.tree / 'include/linux/ieee80211.h').read_text()
    ieee_he = (args.tree / 'include/linux/ieee80211-he.h').read_text()
    mac80211 = (args.tree / 'include/net/mac80211.h').read_text()
    decl = '\n'.join((
        one(ieee, r'^#define IEEE80211_NUM_ACS\s+\d+$'),
        one(mac80211, r'^enum ieee80211_ac_numbers \{.*?^\};'),
        one(ieee_he, r'^struct ieee80211_he_mu_edca_param_ac_rec \{.*?^\} __packed;'),
        one(mac80211, r'^struct ieee80211_tx_queue_params \{.*?^\};'),
        one(core, r'^struct ath12k_tx_conf \{.*?^\};'),
        one(wmi, r'^struct wmi_wmm_params_arg \{.*?^\};'),
        one(wmi, r'^struct wmi_wmm_params_all_arg \{.*?^\};'),
    ))
    funcs = '\n'.join(one(mac, rf'^static (?:int|void) {name}\(.*?^\}}') for name in (
        'ath12k_mac_set_wmm_params', 'ath12k_mac_conf_tx',
        'ath12k_mac_cache_tx_conf', 'ath12k_mac_flush_tx_conf'))
    # Require the production callers to use the tested helpers.
    assert 'return ath12k_mac_cache_tx_conf(&cache->tx_conf, ac, params);' in mac
    assert 'ath12k_mac_flush_tx_conf(arvif, &cache->tx_conf);' in mac
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define __packed __attribute__((packed))
#define BIT(n) (1UL << (n))
#define WARN_ON(x) (x)
#define lockdep_assert_wiphy(x) ((void)0)
''' + decl + r'''
struct ath12k_base { int unused; };
struct ath12k { struct ath12k_base *ab; unsigned pdev_idx; };
struct ath12k_link_vif {
    struct ath12k *ar;
    u32 vdev_id;
    struct wmi_wmm_params_all_arg wmm_params;
};
static unsigned sends, calls, warned, uapsd_ac[4], uapsd_enabled[4];
static int send_error, uapsd_error;
static u32 sent_vdev;
static struct wmi_wmm_params_all_arg sent;
#define ath12k_warn(ab, ...) ((void)(ab), ++warned)
static int ath12k_wmi_send_wmm_update_cmd(struct ath12k *ar, u32 vdev_id,
                                         struct wmi_wmm_params_all_arg *params)
{
    assert(ar);
    assert(!calls);
    sends++;
    sent_vdev=vdev_id;
    sent=*params;
    return send_error;
}
static int ath12k_conf_tx_uapsd(struct ath12k_link_vif *arvif, u16 ac, bool enable)
{
    assert(sends==1 && !send_error && calls<4 && arvif->vdev_id==sent_vdev);
    uapsd_ac[calls]=ac;
    uapsd_enabled[calls++]=enable;
    return uapsd_error == ac+1 ? -EIO : 0;
}
''' + funcs + r'''
static struct wmi_wmm_params_arg *slot(struct wmi_wmm_params_all_arg *p, unsigned ac)
{
    struct wmi_wmm_params_arg *slots[] = {&p->ac_vo,&p->ac_vi,&p->ac_be,&p->ac_bk};
    assert(ac<4);
    return slots[ac];
}
static void reset(void)
{
    sends=calls=warned=0;
    send_error=uapsd_error=0;
    memset(&sent,0,sizeof(sent));
}
static void check_params(struct wmi_wmm_params_arg *p,
                         const struct ieee80211_tx_queue_params *q)
{
    assert(p->cwmin==q->cw_min && p->cwmax==q->cw_max &&
           p->aifs==q->aifs && p->txop==q->txop);
}
int main(void)
{
    struct ath12k ar={0};
    unsigned cases=0;
    /* Every ordered sequence of up to six updates, including duplicates.
     * Each category has distinct parameters and every update a new value.
     * A separate link is deliberately interleaved with the tested link.
     */
    for(unsigned len=0, count=1;len<=6;++len,count*=4)
    for(unsigned seq=0;seq<count;++seq) {
        struct ath12k_tx_conf cache={0}, other={0};
        struct ieee80211_tx_queue_params expected[4]={0};
        struct ath12k_link_vif vif={.ar=&ar,.vdev_id=23};
        struct wmi_wmm_params_all_arg initial={0};
        unsigned mask=0, code=seq;
        for(unsigned ac=0;ac<4;++ac) {
            struct wmi_wmm_params_arg *p=slot(&initial,ac);
            *p=(struct wmi_wmm_params_arg){.cwmin=15,.cwmax=1023,.aifs=2,.txop=0,
                                         .acm=1,.no_ack=1};
        }
        vif.wmm_params=initial;
        for(unsigned i=0;i<len;++i,code/=4) {
            unsigned ac=code%4;
            struct ieee80211_tx_queue_params q={
                .cw_min=7+i+ac,.cw_max=127+i+ac,.aifs=2+i,
                .txop=47+i*3+ac,.uapsd=(i+ac)%2,.acm=true,.mu_edca=true,
                .mu_edca_param_rec={.aifsn=3,.ecw_min_max=8,.mu_edca_timer=12}
            };
            assert(ath12k_mac_cache_tx_conf(&cache,ac,&q)==0);
            expected[ac]=q;
            mask|=1U<<ac;
            q.txop=65535;
            assert(ath12k_mac_cache_tx_conf(&other,ac,&q)==0);
        }
        assert(cache.changed==mask);
        for(unsigned ac=0;ac<4;++ac)
            if(mask&BIT(ac)) {
                const struct ieee80211_tx_queue_params *q=&cache.tx_queue_params[ac];
                assert(q->txop==expected[ac].txop && q->uapsd==expected[ac].uapsd);
                assert(q->mu_edca && q->acm && q->mu_edca_param_rec.mu_edca_timer==12);
            }
        for(unsigned ac=4;ac<65536;ac+=8191)
            assert(ath12k_mac_cache_tx_conf(&cache,ac,&expected[0])==-EINVAL);
        assert(cache.changed==mask);
        reset();
        ath12k_mac_flush_tx_conf(&vif,&cache);
        assert(sends==!!mask && calls==(unsigned)__builtin_popcount(mask) && !warned);
        for(unsigned ac=0,j=0;ac<4;++ac) {
            struct wmi_wmm_params_arg *p=slot(&vif.wmm_params,ac);
            if(mask&BIT(ac)) {
                check_params(p,&expected[ac]);
                assert(uapsd_ac[j]==ac && uapsd_enabled[j++]==expected[ac].uapsd);
            } else {
                struct wmi_wmm_params_arg *old=slot(&initial,ac);
                assert(p->cwmin==old->cwmin && p->cwmax==old->cwmax &&
                       p->aifs==old->aifs && p->txop==old->txop);
            }
            assert(p->acm==1 && p->no_ack==1);
            if(mask) {
                struct wmi_wmm_params_arg *wire=slot(&sent,ac);
                assert(wire->cwmin==p->cwmin && wire->cwmax==p->cwmax &&
                       wire->aifs==p->aifs && wire->txop==p->txop);
            }
        }
        if(mask) {
            reset(); send_error=-EIO;
            ath12k_mac_flush_tx_conf(&vif,&cache);
            assert(sends==1 && calls==0 && warned==1);
            for(unsigned ac=0;ac<4;++ac) {
                reset(); uapsd_error=ac+1;
                ath12k_mac_flush_tx_conf(&vif,&cache);
                assert(sends==1 && calls==(unsigned)__builtin_popcount(mask));
                assert(warned==!!(mask&BIT(ac)));
            }
        }
        ++cases;
    }
    for(unsigned ac=0;ac<4;++ac) {
        struct ath12k_link_vif vif={.ar=&ar,.vdev_id=5};
        struct ieee80211_tx_queue_params q={.cw_min=7,.cw_max=15,.aifs=2,
                                            .txop=47,.uapsd=true};
        reset();
        assert(ath12k_mac_conf_tx(&vif,ac,&q)==0 && sends==1 && calls==1);
        check_params(slot(&sent,ac),&q);
        assert(uapsd_ac[0]==ac && uapsd_enabled[0]);
        reset(); send_error=-EIO;
        assert(ath12k_mac_conf_tx(&vif,ac,&q)==-EIO && sends==1 && !calls);
        reset(); uapsd_error=ac+1;
        assert(ath12k_mac_conf_tx(&vif,ac,&q)==-EIO && sends==1 && calls==1);
    }
    puts("WMM_CACHE_PASS");
    printf("ordered sequences=%u (success, WMI failure, each U-APSD failure)\\n",cases);
}
'''
    c = args.output / 'wmm-cache.c'
    obj = args.output / 'wmm-cache.o'
    exe = args.output / 'wmm-cache'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=gnu11', '-O2', '-Wall',
                    '-Wextra', '-Werror', '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
