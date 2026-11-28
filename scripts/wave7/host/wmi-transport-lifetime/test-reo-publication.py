#!/usr/bin/env python3
"""Exercise the actual REO submission/completion routines with a simulated SRNG."""
import argparse
from pathlib import Path
import re
import subprocess


def extract(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='ath12k wifi7/dp_rx.c')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    source = args.source.read_text()
    ath = args.source.parent.parent
    constant = re.search(r'^#define\s+DP_REO_CMD_RING_SIZE\s+\d+', (ath/'dp.h').read_text(), re.M).group()
    header = (ath/'dp.h').read_text()
    telemetry = '\n'.join(re.search(rf'^{kind} {name} \{{.*?^\}};', header,
                                    re.M | re.S).group() for kind, name in (
        ('enum', 'ath12k_reo_cmd_kind'),
        ('struct', 'ath12k_reo_cmd_counters'),
        ('struct', 'ath12k_reo_cmd_stats'),
        ('struct', 'ath12k_reo_cmd_pending')))
    flags = '\n'.join(re.findall(r'^#define HAL_REO_CMD_UPD0_\w+\s+BIT\(\d+\)',
                                 (ath/'wifi7/hal.h').read_text(), re.M))
    actual = '\n\n'.join(extract(source, s) for s in (
        'ath12k_wifi7_reo_cmd_kind(enum',
        'int ath12k_wifi7_dp_reo_cmd_send(',
        'static void ath12k_wifi7_reo_cmd_complete('))
    actual = "static enum ath12k_reo_cmd_kind\n" + actual
    shim = r'''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#define BIT(n) (1u<<(n))
/* FLAGS */
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define WARN_ON_ONCE(x) (!!(x))
#define GFP_ATOMIC 0
#define HAL_REO_CMD_FLG_NEED_STATUS 1
#define HAL_REO_GET_QUEUE_STATS_STATUS 285
#define HAL_REO_FLUSH_CACHE_STATUS 287
#define HAL_REO_UPDATE_RX_REO_QUEUE_STATUS 172
/* CONSTANT */
enum hal_reo_cmd_type { HAL_REO_CMD_GET_QUEUE_STATS, HAL_REO_CMD_FLUSH_QUEUE,
    HAL_REO_CMD_FLUSH_CACHE, HAL_REO_CMD_UNBLOCK_CACHE, HAL_REO_CMD_FLUSH_TIMEOUT_LIST,
    HAL_REO_CMD_UPDATE_RX_QUEUE };
enum hal_reo_cmd_status { HAL_REO_CMD_SUCCESS, HAL_REO_CMD_BLOCKED, HAL_REO_CMD_FAILED, HAL_REO_CMD_RESOURCE_BLOCKED, HAL_REO_CMD_DRAIN=255 };
struct ath12k_dp;
struct ath12k_dp_rx_tid_rxq { int value; };
struct ath12k_hal_reo_cmd { int flag; u32 upd0; };
/* TELEMETRY */
struct hal_srng { int lock; struct { struct { u32 hp; } src_ring; } u;
    u32 entry_size, ring_size; bool full; unsigned published, advanced; int desc; };
struct ath12k_base;
struct ath12k_dp { struct ath12k_base *ab; struct { unsigned ring_id; } reo_cmd_ring;
    struct ath12k_reo_cmd_pending reo_cmd_pending[DP_REO_CMD_RING_SIZE]; int reo_cmd_lock;
    struct ath12k_reo_cmd_stats reo_cmd_stats; };
struct ath12k_base { struct ath12k_dp dp; struct { struct hal_srng srng_list[1]; } hal; };
struct hal_reo_status { struct { u16 cmd_num; enum hal_reo_cmd_status cmd_status; } uniform_hdr;
    struct { struct { bool err_detected; unsigned cache_controller_flush_status_err; } flush_cache; } u; };
static unsigned callbacks, warnings;
static u64 ticks;
static u64 ktime_get_ns(void) { ticks += 100; return ticks; }
#define ath12k_warn(ab,fmt,...) do { assert(ab); warnings++; } while(0)
static enum hal_reo_cmd_status last_status;
static bool eager, fail_advance, wrong_number, fail_encode, reenter;
static u16 eager_tag, eager_num;
static struct ath12k_base *active;
static void ath12k_wifi7_reo_cmd_complete(struct ath12k_dp *,u16,struct hal_reo_status *);
#define ath12k_ab_to_dp(ab) (&(ab)->dp)
static void spin_lock_bh(int *lock) { assert(!*lock); *lock=1; }
static void spin_unlock_bh(int *lock) { assert(*lock); *lock=0;
    if (active && lock==&active->dp.reo_cmd_lock && eager_num) {
        struct hal_reo_status st={.uniform_hdr={eager_num,HAL_REO_CMD_SUCCESS}};
        eager_num=0; ath12k_wifi7_reo_cmd_complete(&active->dp,eager_tag,&st);
    }
}
static void ath12k_hal_srng_access_begin(struct ath12k_base *ab,struct hal_srng *r) {
    assert(ab->dp.reo_cmd_lock && r->lock); }
static void *ath12k_hal_srng_src_peek(struct ath12k_base *ab,struct hal_srng *r) {
    assert(ab->dp.reo_cmd_lock && r->lock); return r->full?NULL:&r->desc; }
static void *ath12k_hal_srng_src_get_next_entry(struct ath12k_base *ab,struct hal_srng *r) {
    assert(ab->dp.reo_cmd_lock && r->lock); if(fail_advance) return NULL;
    r->u.src_ring.hp=(r->u.src_ring.hp+r->entry_size)%r->ring_size; r->advanced++;
    return &r->desc;
}
static int ath12k_wifi7_hal_reo_cmd_encode(struct ath12k_base *ab,void *d,enum hal_reo_cmd_type t,struct ath12k_hal_reo_cmd *c) {
    struct hal_srng *r=&ab->hal.srng_list[0]; (void)t;(void)c;
    assert(ab->dp.reo_cmd_lock && r->lock && d==&r->desc);
    if(fail_encode) return -ENOSPC;
    return r->u.src_ring.hp/r->entry_size+1+wrong_number;
}
static void ath12k_hal_srng_access_end(struct ath12k_base *ab,struct hal_srng *r) {
    assert(ab->dp.reo_cmd_lock && r->lock);
    if(r->advanced==r->published) return;
    assert(r->advanced==r->published+1); r->published++;
    unsigned slot=(r->u.src_ring.hp/r->entry_size+DP_REO_CMD_RING_SIZE-1)%DP_REO_CMD_RING_SIZE;
    if(eager && ab->dp.reo_cmd_pending[slot].status_tag) {
        assert(!eager_num); eager_tag=ab->dp.reo_cmd_pending[slot].status_tag; eager_num=slot+1;
    }
}
/* ACTUAL */
static void done(struct ath12k_dp *dp,void *ctx,enum hal_reo_cmd_status status) {
    assert(!dp->reo_cmd_lock && ((struct ath12k_dp_rx_tid_rxq *)ctx)->value==123);
    last_status=status; callbacks++;
    if(reenter) { struct ath12k_hal_reo_cmd c={0}; reenter=false;
        assert(ath12k_wifi7_dp_reo_cmd_send(dp->ab,HAL_REO_CMD_GET_QUEUE_STATS,&c,NULL,NULL)==0); }
}
static void complete(struct ath12k_base *ab,u16 tag,u16 num) {
    struct hal_reo_status st={.uniform_hdr={num,HAL_REO_CMD_SUCCESS}};
    ath12k_wifi7_reo_cmd_complete(&ab->dp,tag,&st);
}
static void init(struct ath12k_base *ab) { memset(ab,0,sizeof(*ab)); ab->dp.ab=ab;
    ab->hal.srng_list[0].entry_size=8;ab->hal.srng_list[0].ring_size=8*DP_REO_CMD_RING_SIZE;
    active=ab; eager=fail_advance=wrong_number=fail_encode=reenter=false;eager_num=0; }
int main(void) {
    struct ath12k_base a,b; struct ath12k_dp_rx_tid_rxq rx={123}; unsigned cases=0;
    const enum hal_reo_cmd_type types[]={HAL_REO_CMD_GET_QUEUE_STATS,HAL_REO_CMD_FLUSH_CACHE,HAL_REO_CMD_UPDATE_RX_QUEUE};
    const u16 tags[]={HAL_REO_GET_QUEUE_STATS_STATUS,HAL_REO_FLUSH_CACHE_STATUS,HAL_REO_UPDATE_RX_REO_QUEUE_STATUS};
    for(unsigned i=0;i<ARRAY_SIZE(types);i++) for(unsigned flags=0;flags<2;flags++)
    for(unsigned cb=0;cb<2;cb++) for(unsigned failure=0;failure<7;failure++)
    for(unsigned fast=0;fast<2;fast++) {
        init(&a); struct hal_srng *r=&a.hal.srng_list[0];
        struct ath12k_hal_reo_cmd cmd={.flag=(int)flags};
        r->full=failure==2;fail_encode=failure==3;wrong_number=failure==4;fail_advance=failure==5;eager=fast;
        unsigned before=callbacks; enum hal_reo_cmd_type t=failure==6?HAL_REO_CMD_FLUSH_QUEUE:types[i];
        int expected=failure==6?-EOPNOTSUPP:(!flags&&cb)?-EINVAL:(failure==1&&!cb)?-EINVAL:r->full?-ENOBUFS:fail_encode?-ENOSPC:wrong_number?-EINVAL:fail_advance?-EIO:0;
        assert(ath12k_wifi7_dp_reo_cmd_send(&a,t,&cmd,cb?done:NULL,(cb||failure==1)?&rx:NULL)==expected);
        assert(r->published==(expected==0)); assert(!r->lock&&!a.dp.reo_cmd_lock);
        if(expected==0&&flags) { if(!fast) {assert(a.dp.reo_cmd_pending[0].status_tag==tags[i]);
            complete(&a,tags[(i+1)%3],1); assert(a.dp.reo_cmd_pending[0].status_tag==tags[i]); }
            complete(&a,tags[i],0); complete(&a,tags[i],DP_REO_CMD_RING_SIZE+1);complete(&a,tags[i],1);complete(&a,tags[i],1); }
        assert(callbacks-before==(unsigned)(expected==0&&cb)); assert(!a.dp.reo_cmd_pending[0].status_tag);
        cases++;
    }
    init(&a); struct ath12k_hal_reo_cmd status={.flag=1},silent={0};
    for(unsigned i=0;i<DP_REO_CMD_RING_SIZE;i++) assert(!ath12k_wifi7_dp_reo_cmd_send(&a,types[2],&status,i==0?done:NULL,i==0?&rx:NULL));
    assert(ath12k_wifi7_dp_reo_cmd_send(&a,types[0],&silent,NULL,NULL)==-ENOBUFS);
    assert(a.hal.srng_list[0].published==DP_REO_CMD_RING_SIZE);
    init(&b); assert(!ath12k_wifi7_dp_reo_cmd_send(&b,types[2],&status,NULL,NULL));
    complete(&b,tags[2],1); assert(a.dp.reo_cmd_pending[0].status_tag==tags[2]);
    complete(&a,tags[2],1); assert(!ath12k_wifi7_dp_reo_cmd_send(&a,types[0],&silent,NULL,NULL));
    for(unsigned i=1;i<DP_REO_CMD_RING_SIZE;i++) complete(&a,tags[2],i+1);
    init(&a); reenter=true;eager=true;assert(!ath12k_wifi7_dp_reo_cmd_send(&a,types[0],&status,done,&rx));
    assert(a.hal.srng_list[0].published==2 && !reenter);
    for (unsigned hdr=0; hdr<3; hdr++) for (unsigned blocked=0; blocked<2; blocked++)
    for (unsigned err=0; err<4; err++) {
        init(&a); unsigned before=callbacks;
        assert(!ath12k_wifi7_dp_reo_cmd_send(&a,types[1],&status,done,&rx));
        struct hal_reo_status st={.uniform_hdr={1,(enum hal_reo_cmd_status)hdr},
            .u.flush_cache={blocked,err}};
        ath12k_wifi7_reo_cmd_complete(&a.dp,tags[1],&st);
        assert(callbacks==before+1 && last_status==(hdr==HAL_REO_CMD_SUCCESS&&(blocked||err)?HAL_REO_CMD_FAILED:hdr));
    }

    const u32 masks[] = {0,HAL_REO_CMD_UPD0_BA_WINDOW_SIZE,HAL_REO_CMD_UPD0_SSN,
        HAL_REO_CMD_UPD0_PN,HAL_REO_CMD_UPD0_PN_CHECK,HAL_REO_CMD_UPD0_VLD,
        HAL_REO_CMD_UPD0_BA_WINDOW_SIZE|HAL_REO_CMD_UPD0_PN,
        HAL_REO_CMD_UPD0_BA_WINDOW_SIZE|HAL_REO_CMD_UPD0_SSN};
    const enum ath12k_reo_cmd_kind kinds[] = {ATH12K_REO_CMD_OTHER,ATH12K_REO_CMD_BA,
        ATH12K_REO_CMD_BA,ATH12K_REO_CMD_PN,ATH12K_REO_CMD_PN,ATH12K_REO_CMD_VALID,
        ATH12K_REO_CMD_OTHER,ATH12K_REO_CMD_BA};
    for(unsigned m=0;m<ARRAY_SIZE(masks);m++) for(unsigned hdr=0;hdr<256;hdr++)
    for(unsigned cb=0;cb<2;cb++) {
        init(&a);
        struct ath12k_hal_reo_cmd cmd={.flag=1,.upd0=masks[m]};
        unsigned before=warnings, calls=callbacks;
        assert(!ath12k_wifi7_dp_reo_cmd_send(&a,types[2],&cmd,cb?done:NULL,cb?&rx:NULL));
        struct ath12k_reo_cmd_counters *c=&a.dp.reo_cmd_stats.kind[kinds[m]];
        assert(c->submitted==1 && a.dp.reo_cmd_pending[0].kind==kinds[m]);
        complete(&a,tags[1],1); assert(a.dp.reo_cmd_stats.unmatched_status==1);
        struct hal_reo_status st={.uniform_hdr={1,(enum hal_reo_cmd_status)hdr}};
        ath12k_wifi7_reo_cmd_complete(&a.dp,tags[2],&st);
        assert(c->success==(hdr==0)&&c->blocked==(hdr==1)&&c->failed==(hdr==2));
        assert(c->resource_blocked==(hdr==3)&&c->other_status==(hdr>3));
        assert(c->unhandled_failure==(hdr!=0&&!cb)&&warnings-before==(hdr!=0&&!cb));
        assert(c->max_latency_ns==100 && callbacks-calls==cb);
        assert(!a.dp.reo_cmd_pending[0].status_tag);
        complete(&a,tags[2],1); assert(a.dp.reo_cmd_stats.unmatched_status==2);
        for(unsigned i=0;i<ATH12K_REO_CMD_KINDS;i++)
            assert(a.dp.reo_cmd_stats.kind[i].submitted==(i==kinds[m]));
        cases++;
    }
    init(&a);
    a.hal.srng_list[0].full=true;
    assert(ath12k_wifi7_dp_reo_cmd_send(&a,types[0],&status,NULL,NULL)==-ENOBUFS);
    assert(a.dp.reo_cmd_stats.kind[ATH12K_REO_CMD_STATS].ring_full==1);
    a.hal.srng_list[0].full=false; fail_encode=true;
    assert(ath12k_wifi7_dp_reo_cmd_send(&a,types[0],&status,NULL,NULL)==-ENOSPC);
    assert(a.dp.reo_cmd_stats.kind[ATH12K_REO_CMD_STATS].submit_failed==1);
    fail_encode=false;
    for(unsigned i=0;i<DP_REO_CMD_RING_SIZE;i++)
        assert(!ath12k_wifi7_dp_reo_cmd_send(&a,types[0],&status,NULL,NULL));
    assert(ath12k_wifi7_dp_reo_cmd_send(&a,types[0],&silent,NULL,NULL)==-ENOBUFS);
    assert(a.dp.reo_cmd_stats.kind[ATH12K_REO_CMD_STATS].slot_busy==1);
    complete(&a,tags[0],1);
    assert(!ath12k_wifi7_dp_reo_cmd_send(&a,types[0],&silent,NULL,NULL));
    assert(a.dp.reo_cmd_stats.kind[ATH12K_REO_CMD_STATS].statusless==1);
    assert(a.dp.reo_cmd_stats.kind[ATH12K_REO_CMD_STATS].submitted==DP_REO_CMD_RING_SIZE);
    printf("REO_PUBLICATION_PASS cases=%u plus full ring, cross-radio and reentrant completion\n",cases);
}
'''
    args.output.mkdir(parents=True, exist_ok=True)
    c, obj, exe = (args.output / f'reo-publication{suffix}' for suffix in ('.c','.o',''))
    c.write_text(shim.replace('/* CONSTANT */', constant).replace('/* TELEMETRY */', telemetry).replace('/* FLAGS */', flags).replace('/* ACTUAL */', actual))
    subprocess.run(['/usr/local/bin/sccache', '/usr/bin/cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare', '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['/usr/bin/cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
