#!/usr/bin/env python3
"""Exercise the actual mac80211 AQL charge and ath12k retirement helpers."""
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
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.source
    mac = root / 'net/mac80211'
    driver = root / 'drivers/net/wireless/ath/ath12k'
    sta = (mac / 'sta_info.c').read_text()
    owner = one((mac / 'sta_info.h').read_text(), r'^struct ieee80211_aql_owner \{.*?^\};')
    helpers = '\n'.join(one(sta, rf'^(?:static )?(?:void|struct ieee80211_aql_owner \*\n)\s*{name}\(.*?^\}}') for name in (
        'ieee80211_aql_update_pending_airtime', 'ieee80211_sta_update_pending_airtime',
        'ieee80211_tx_aql_get', 'ieee80211_tx_aql_put', 'ieee80211_tx_aql_clone',
        'ieee80211_tx_aql_complete'))
    core = (driver / 'core.h').read_text()
    retire = one(core, r'^static inline void ath12k_tx_aql_complete\(.*?^\}')
    free = one(core, r'^static inline void ath12k_free_txskb\(.*?^\}')
    op = one((driver / 'wifi7/hw.c').read_text(), r'^static void\s+ath12k_wifi7_mac_op_tx\(.*?^\}')
    complete = one((driver / 'wifi7/dp_tx.c').read_text(), r'^static void\nath12k_wifi7_dp_tx_complete_record\(.*?^\}')
    wmi = one((driver / 'wmi.c').read_text(), r'^static int wmi_process_mgmt_tx_comp\(.*?^\}')
    mgmt = one((driver / 'mac.c').read_text(), r'^static void ath12k_mac_tx_mgmt_free\(.*?^\}')
    assert op.index('ieee80211_tx_aql_get(') < op.index('ath12k_free_txskb(')
    assert op.index('ieee80211_tx_aql_clone(') < op.index('ath12k_wifi7_dp_tx(tmp_dp_pdev')
    assert op.index('ath12k_wifi7_dp_tx(tmp_dp_pdev') < op.index('ath12k_tx_aql_complete(hw, msdu_copied')
    assert complete.index('ath12k_wifi7_tx_retire(') < complete.index('ath12k_tx_aql_complete(')
    assert complete.index('ath12k_tx_aql_complete(') < complete.index('ieee80211_free_txskb(')
    assert complete.index('ath12k_tx_aql_complete(') < complete.index('atomic_dec_and_test(')
    for fn in (wmi, mgmt):
        assert fn.index('ath12k_tx_aql_complete(') < fn.index('memset(&info->status')
    cleanup = (driver / 'dp.c').read_text()
    assert 'ieee80211_tx_aql_put(skb_cb->aql_owner);' in cleanup
    assert 'ath12k_tx_aql_complete(ath12k_ar_to_hw(ar), skb, false);' in cleanup
    util = (mac / 'util.c').read_text()
    assert 'for (ac = 0; ac < IEEE80211_NUM_ACS; ac++)\n\t\tieee80211_handle_wake_tx_queue_ac(local, ac, true);' in util
    assert 'tasklet_kill(&local->aql_txq_tasklet);' in (mac / 'main.c').read_text()
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef struct { int value; } atomic_t;
typedef struct { unsigned value; } refcount_t;
#define IEEE80211_NUM_ACS 4
#define NL80211_EXT_FEATURE_AQL 1
#define DEFERRED_AIRTIME_REPORT 1
#define READ_ONCE(x) (x)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
static void atomic_add(int n,atomic_t *v){v->value+=n;}
static int atomic_sub_return(int n,atomic_t *v){return v->value-=n;}
static void atomic_sub(int n,atomic_t *v){v->value-=n;}
static int atomic_cmpxchg(atomic_t *v,int old,int new){int prior=v->value;if(prior==old)v->value=new;return prior;}
static void refcount_inc(refcount_t *r){assert(r->value);++r->value;}
static bool refcount_dec_and_test(refcount_t *r){assert(r->value);return !--r->value;}
static unsigned freed, warns, schedules, statuses;
static void kfree(void *p){++freed;free(p);}
#define WARN_ONCE(x,...) ((x)?(++warns,true):false)
struct ieee80211_hw { struct ieee80211_local *local; bool wiphy; bool deferred; };
struct ieee80211_sta { unsigned unused; };
struct ieee80211_tx_info { u16 estimate; bool tx_time_mc; };
struct ath12k_skb_cb { struct ieee80211_aql_owner *aql_owner; };
struct sk_buff { struct ieee80211_tx_info info; struct ath12k_skb_cb cb; u8 ac; };
#define IEEE80211_SKB_CB(s) (&(s)->info)
#define ATH12K_SKB_CB(s) (&(s)->cb)
struct ieee80211_txq { unsigned unused; };
static void ieee80211_handle_wake_tx_queue(struct ieee80211_hw *h,struct ieee80211_txq *q){(void)h;(void)q;}
static void custom_wake(struct ieee80211_hw *h,struct ieee80211_txq *q){(void)h;(void)q;}
struct ieee80211_ops { void (*wake_tx_queue)(struct ieee80211_hw *,struct ieee80211_txq *); };
struct tasklet_struct { bool scheduled; };
struct ieee80211_local {
    struct ieee80211_hw hw;
    struct ieee80211_ops *ops;
    bool aql_wake_disabled;
    struct tasklet_struct aql_txq_tasklet;
    atomic_t aql_bc_pending_airtime,aql_total_pending_airtime,aql_ac_pending_airtime[4];
};
static void tasklet_schedule(struct tasklet_struct *t){if(!t->scheduled){t->scheduled=true;++schedules;}}
static struct ieee80211_local *hw_to_local(struct ieee80211_hw *h){return h->local;}
static bool wiphy_ext_feature_isset(bool w,int f){assert(f==1);return w;}
#define ieee80211_hw_check(h,f) ((h)->deferred)
static u16 ieee80211_info_get_tx_time_est(struct ieee80211_tx_info *i){return i->estimate;}
static void ieee80211_info_set_tx_time_est(struct ieee80211_tx_info *i,u16 n){i->estimate=n;}
static u8 skb_get_queue_mapping(struct sk_buff *s){return s->ac;}
static void ieee80211_free_txskb(struct ieee80211_hw *h,struct sk_buff *s){assert(h && !s->info.estimate);++statuses;}
''' + owner + r'''
struct sta_info { struct ieee80211_sta sta; struct ieee80211_aql_owner *aql; };
''' + helpers + '\n' + retire + '\n' + free + r'''
static struct ieee80211_aql_owner *new_owner(void)
{
    struct ieee80211_aql_owner *o=calloc(1,sizeof(*o));assert(o);o->refs.value=1;return o;
}
int main(void)
{
    unsigned cases=0;
    for(unsigned ac=0;ac<4;++ac)
    for(unsigned est=0;est<=4092;est+=4)
    for(unsigned copies=0;copies<4;++copies)
    for(unsigned multicast=0;multicast<2;++multicast)
    for(unsigned remove=0;remove<2;++remove)
    for(unsigned deferred=0;deferred<2;++deferred)
    for(unsigned wake=0;wake<2;++wake){
        struct ieee80211_ops ops={.wake_tx_queue=ieee80211_handle_wake_tx_queue};
        struct ieee80211_local l={.ops=&ops};
        l.hw=(struct ieee80211_hw){.local=&l,.wiphy=true,.deferred=deferred};
        struct sta_info a={.aql=new_owner()},b={.aql=new_owner()};
        struct sk_buff frames[4]={0};
        struct ieee80211_aql_owner *o=a.aql;
        frames[0].ac=ac;
        frames[0].info=(struct ieee80211_tx_info){est,multicast};
        ieee80211_sta_update_pending_airtime(&l,multicast?NULL:&a,ac,est,false,multicast);
        frames[0].cb.aql_owner=ieee80211_tx_aql_get(multicast?NULL:&a.sta,&frames[0]);
        for(unsigned n=1;n<=copies;++n){
            frames[n]=frames[0];
            ieee80211_tx_aql_clone(&l.hw,frames[n].cb.aql_owner,&frames[n]);
        }
        unsigned amount=(copies+1)*est;
        assert(o->refs.value==1+(!multicast&&est?copies+1:0));
        assert(o->pending[ac].value==(multicast?0:(int)amount));
        assert(l.aql_bc_pending_airtime.value==(multicast?(int)amount:0));
        assert(l.aql_total_pending_airtime.value==(multicast?0:(int)amount));
        unsigned frees=freed, before=schedules;
        if(remove) ieee80211_tx_aql_put(o);
        for(unsigned n=copies+1;n>0;--n){
            unsigned idx=n-1;
            ath12k_tx_aql_complete(&l.hw,&frames[idx],wake);
            ath12k_free_txskb(&l.hw,&frames[idx]); /* second retirement is a no-op */
            assert(!frames[idx].cb.aql_owner);
            assert(b.aql->pending[ac].value==0); /* unrelated/reused station */
            assert(l.aql_total_pending_airtime.value==(multicast?0:(int)(idx*est)));
            assert(l.aql_ac_pending_airtime[ac].value==(multicast?0:(int)(idx*est)));
            assert(l.aql_bc_pending_airtime.value==(multicast?(int)(idx*est):0));
        }
        assert(schedules-before==!!(est&&wake));
        if(!remove){
            assert(o->refs.value==1 && !o->pending[ac].value);
            assert(o->completed[ac].value==(!multicast&&deferred?(int)amount:0));
            ieee80211_tx_aql_put(o);
        }
        ieee80211_tx_aql_put(b.aql);
        assert(freed-frees==2 && !warns);
        ++cases;
    }
    for(unsigned custom=0;custom<2;++custom)
    for(unsigned disabled=0;disabled<2;++disabled){
        struct ieee80211_ops ops={.wake_tx_queue=custom?custom_wake:ieee80211_handle_wake_tx_queue};
        struct ieee80211_local l={.ops=&ops,.aql_wake_disabled=disabled};
        l.hw=(struct ieee80211_hw){.local=&l,.wiphy=true};
        struct sta_info a={.aql=new_owner()};
        struct sk_buff s={.info={40,false},.ac=1};
        ieee80211_sta_update_pending_airtime(&l,&a,1,40,false,false);
        s.cb.aql_owner=ieee80211_tx_aql_get(&a.sta,&s);
        unsigned before=schedules;
        ath12k_free_txskb(&l.hw,&s);
        assert(schedules-before==(!custom&&!disabled));
        ieee80211_tx_aql_put(a.aql);
        ++cases;
    }
    printf("AQL_OWNER_PASS cases=%u status_returns=%u tasklet_wakes=%u\n",cases,statuses,schedules);
    return 0;
}
'''
    c = args.output / 'aql-owner.c'
    exe = args.output / 'aql-owner'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-c', str(c), '-o', str(c.with_suffix('.o'))], check=True)
    subprocess.run(['cc', str(c.with_suffix('.o')), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
